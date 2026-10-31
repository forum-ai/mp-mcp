# mp-mcp: running, deploying and releasing

This file is for people who run, change or release the server. To use it, see the [README](README.md).

Nothing about the API is written down in this repository. At startup the server reads the MP API's own OpenAPI spec (`https://api.materialsproject.org/openapi.json`: 37 endpoints, 846 described parameters today) and walks the installed `mp-api` client for its object methods. A new endpoint, filter or field appears the next time the server restarts, with no code change.

## Tools

| Tool | What it does |
|---|---|
| `list_endpoints` | Every MP REST endpoint, one line each |
| `describe_endpoint(path, search)` | One endpoint's filters and returned fields, with the descriptions MP publishes, and whether it supports sorting |
| `query(path, fields, params, limit, sort, body)` | Runs one endpoint; returns the total number of matches and the rows as JSON. `limit=1` gives just the count; `_skip` in `params` pages further |
| `list_objects(search)` | The `mp-api` methods that return whole objects (36 today) |
| `get_object(method, args, format)` | Calls one. `summary`: readable text plus a plot. `json`: the full pymatgen object (`as_dict`), inline when small, else a file or a download link. `cif` or `poscar`: a structure as that format |
| `docs_search(query)`, `docs_page(url)` | MP's documentation, through the docs site's own MCP server |

A typical session: `list_endpoints`, then `describe_endpoint("/materials/summary/", "gap")`, then

```
query("/materials/summary/", fields=["material_id", "formula_pretty", "band_gap"],
      params={"elements": "Ba,O", "nelements_max": 3, "is_stable": true, "band_gap_min": 2, "band_gap_max": 3})
```

and for a structure file, `get_object("get_structure_by_material_id", {"material_id": "mp-149", "conventional_unit_cell": true}, format="cif")`.

Guards: at most 500 rows and 20,000 characters per query (cut to fit, with a note), a 55-second timeout on every MP call (under the 60 seconds most clients wait for a tool, so the server's own message arrives first), objects of at most 50 MB, and read-only access. The whole tool listing is about 4,600 characters, so connecting the server costs a conversation about 1,150 tokens. Every tool is marked to load up front (`anthropic/alwaysLoad`), so a client that defers MCP tools behind a search step, as Claude Code does by default, still has them in view from the first turn; the instructions tell the model to use them rather than write `mp-api` code.

## Design

Each choice below follows from what an AI assistant needs in order to answer a materials question correctly, and from what goes wrong when it does not have it.

- **The API describes itself; this repository writes none of it down.** Endpoints, filters, field names and their descriptions are read from MP's OpenAPI spec at startup, and object methods from the installed `mp-api`. MP adds endpoints and fields with every release; a hand-written tool list goes stale and silently hides data, while a tool generated from the live spec cannot drift from it.
- **Five general tools, not one per endpoint.** A client pays for the tool listing in context on every conversation. Thirty-seven endpoints with 846 parameters as separate tools would cost tens of thousands of tokens and still leave filters out; the seven tools together cost about 1,150 tokens and reach all of it, and the model reads the details of only the endpoint it needs, when it needs them.
- **Everything needed to form a correct call is returned as text the model can read.** Filter names with MP's own descriptions, field names, whether the endpoint sorts, whether its fields are documented. REST APIs ignore parameters they do not know, so a guessed filter name produces a plausible but wrong answer with no error; a model that can see the real names does not have to guess.
- **The model chooses fields and limits; the server bounds them.** Rows, characters, time and object size all have ceilings, and when a result is cut the response says so and how to narrow it. An unbounded result floods the conversation and ends it; a bounded one with a note lets the model ask again more precisely.
- **Objects come in two registers.** Band structures, densities of states, phonons, phase diagrams and Wulff shapes are not tables. The summary answers the question in the chat (gap, transition, imaginary modes, stable phases) with the plot a person would draw; the JSON is the complete pymatgen object for an agent that continues in Python; a structure can also come as CIF or POSCAR, since that is how people hand structures to other programs.
- **Keys belong to callers.** An MP key is personal: it carries the holder's rate limit and their access to restricted datasets. The hosted server therefore has no key of its own and forwards each request under the caller's header, so one user can never spend or expose another's; the local server finds a key the way `mp-api` does, so existing users need no setup.
- **Read-only, and nothing persists.** The server can change nothing at MP, writes nothing about its users, and download links expire. Anything reachable from a chat window should be safe to point an untrusted conversation at.
- **Errors are loud and in plain words; nothing fails silently.** Asking to sort an endpoint that cannot sort is an error, not an unsorted list, because the model would otherwise report the list as sorted. Timeouts, bad arguments and upstream failures say what happened and what to change.
- **Identifiers as MP stores them.** MP's identifiers are AlphaIDs (`mp-aaaaaaft`); responses carry them as stored. Queries accept the older `mp-149` form as well, and a caller matching a paper or a user's own notes can ask for results in that form with `id_format=legacy`, on the endpoints that offer it.
- **Startup never depends on the network.** The spec falls back to a bundled snapshot and object discovery runs offline, so an MP outage degrades answers rather than taking every conversation down with the server.
- **Methodology comes from MP's documentation, not from a paraphrase.** How a hull energy or a band gap is computed changes between releases; the docs tools read MP's documentation server live.

## Whose key a request uses

Every request runs under the caller's own MP API key (get one at <https://next-gen.materialsproject.org/api>).

The caller sends the key in an `X-API-KEY` header or as `Authorization: Bearer <key>`, the form clients with a token field send (Codex, the OpenAI and Claude APIs); `X-API-KEY` wins if both arrive.

- **Hosted** (`MP_MCP_HOSTED=1`, set in the container): the key comes only from the caller's header and goes straight to the MP API on that request. The server stores nothing and never falls back to a key of its own.
- **Local**: the caller's header if present, else `MP_API_KEY`, else `PMG_MAPI_KEY` in `~/.config/.pmgrc.yaml`. Anyone who already uses `mp-api` needs no setup.

## Run the server yourself

```
uv run mp-mcp                                  # stdio
uv run mp-mcp --transport http --port 8000     # http://127.0.0.1:8000/mcp, this machine only
```

A local HTTP server answers with your own key, so it listens on `127.0.0.1` unless you pass `--host`. To run the server from a checkout inside Claude Code instead of the hosted one (for development), `claude mcp add --scope user materials-project -e MP_API_KEY=YOUR_KEY -- uv run --project /path/to/mp-mcp mp-mcp`.

To point Claude Code at the hosted server without the plugin (no skill, key stored in `~/.claude.json`):

```
claude mcp add --transport http --scope user materials-project https://mp.forum-ai.org/mcp --header "X-API-KEY: YOUR_MP_KEY"
```

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `MP_MCP_HOSTED` | unset (`1` in the container) | Accept keys only from the caller's `X-API-KEY` or `Authorization: Bearer` header; listen on all interfaces |
| `MP_MCP_PUBLIC_URL` | the request's own URL | Base URL for download links of large objects; set it to the service's https URL when hosted |
| `MP_MCP_TRANSPORT` | `stdio` (`http` in the container) | `stdio` or `http` |
| `PORT`, `HOST` | `8000`, `127.0.0.1` (`0.0.0.0` when hosted) | HTTP listen address; the MCP endpoint is `/mcp`, the health check `/health` |
| `MP_API_ENDPOINT` | `https://api.materialsproject.org` | MP API to call |
| `MP_MCP_SPEC_URL` | `MP_API_ENDPOINT/openapi.json` | Spec to read at startup; `bundled` uses the snapshot in the package |
| `MP_MCP_MAX_ROWS`, `MP_MCP_MAX_CHARS`, `MP_MCP_TIMEOUT` | `500`, `20000`, `55` | Query guards; the timeout also applies to `get_object` |
| `MP_MCP_INLINE_BYTES`, `MP_MCP_LINK_TTL` | `50000`, `3600` | Largest JSON object returned inline; lifetime of a download link in seconds |
| `MP_MCP_MAX_OBJECT_BYTES`, `MP_MCP_STORE_BYTES` | `50000000`, `256000000` | Largest object served at all; memory the hosted server gives to download links (oldest go first) |
| `MP_MCP_OUTPUT_DIR` | `~/.cache/mp-mcp/objects` | Where a local server writes large objects |
| `MP_MCP_ID_FORMAT` | unset | Identifier form requested on every query, on the 25 endpoints that offer `id_format`. Unset: as MP stores them (AlphaIDs). `legacy`: the older `mp-149` form. A caller's own `id_format` in `params` always wins |
| `MP_MCP_DOCS_URL` | `https://docs.materialsproject.org/~gitbook/mcp` | MP's docs MCP server; empty to turn the docs tools off |

If the live spec cannot be fetched at startup, the server uses the snapshot in `src/mp_mcp/openapi_snapshot.json` and says so in `/health`. Startup needs no network at all.

## Deploy on AWS

The server runs as one container on Amazon ECS Express Mode, which creates the load balancer, HTTPS certificate, scaling and logs itself. The whole job is: build the image and upload it, create the service, give it the name `mp.forum-ai.org`, and check it. Run every command below from a terminal in a clone of this repository, one at a time, in order.

**You need:** the [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) logged in to the FORUM-AI account (`aws configure`); [Docker Desktop](https://docs.docker.com/desktop/), running; and a login to the DNS provider for `forum-ai.org`.

**Placeholders.** Commands below contain these words in capitals. Replace each with the value you wrote down at the step named.

| Placeholder | What it is | Where you get it |
|---|---|---|
| `ACCOUNT_ID` | the 12-digit AWS account number | `aws sts get-caller-identity --query Account --output text` |
| `SERVICE_URL` | the service's own address, `https://mp-mcp-....ecs.us-east-2.on.aws` | step 5 |
| `SERVICE_ARN` | `arn:aws:ecs:us-east-2:ACCOUNT_ID:service/default/mp-mcp` | fixed, once you know `ACCOUNT_ID` |
| `CERT_ARN` | the certificate's ARN | step 6 |
| `LB_DNS` | the load balancer's DNS name, ending in `elb.amazonaws.com` | step 6 |

**Step 1. Create a place for the image (once).**

```
aws ecr create-repository --repository-name mp-mcp --region us-east-2
```

"Repository already exists" is fine.

**Step 2. Build the image and upload it.**

```
aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin ACCOUNT_ID.dkr.ecr.us-east-2.amazonaws.com
docker build --platform linux/amd64 -t ACCOUNT_ID.dkr.ecr.us-east-2.amazonaws.com/mp-mcp:v1 .
docker push ACCOUNT_ID.dkr.ecr.us-east-2.amazonaws.com/mp-mcp:v1
```

The first build takes a few minutes. The push is done when its last line shows a `sha256:` digest.

**Step 3. Create the two roles ECS needs (once).** Check first:

```
aws iam get-role --role-name ecsTaskExecutionRole --query Role.Arn --output text
aws iam get-role --role-name ecsInfrastructureRoleForExpressServices --query Role.Arn --output text
```

If both print an ARN, go to step 4. For any that says `NoSuchEntity`, run its two lines (these are the roles and policies from AWS's own Express Mode tutorial):

```
aws iam create-role --role-name ecsTaskExecutionRole --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name ecsTaskExecutionRole --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
```

```
aws iam create-role --role-name ecsInfrastructureRoleForExpressServices --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name ecsInfrastructureRoleForExpressServices --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices
```

Then wait one minute before step 4; a brand-new role can make the next command fail with "unable to assume", and running it again fixes it.

**Step 4. Create the service.**

```
aws ecs create-express-gateway-service --region us-east-2 \
  --service-name mp-mcp \
  --execution-role-arn arn:aws:iam::ACCOUNT_ID:role/ecsTaskExecutionRole \
  --infrastructure-role-arn arn:aws:iam::ACCOUNT_ID:role/ecsInfrastructureRoleForExpressServices \
  --primary-container '{"image":"ACCOUNT_ID.dkr.ecr.us-east-2.amazonaws.com/mp-mcp:v1","containerPort":8000,"environment":[{"name":"MP_MCP_HOSTED","value":"1"},{"name":"MP_MCP_PUBLIC_URL","value":"https://mp.forum-ai.org"}]}' \
  --cpu 1 --memory 2 \
  --health-check-path /health \
  --scaling-target '{"minTaskCount":1,"maxTaskCount":1}' \
  --monitor-resources
```

1 vCPU and 2 GB (the server uses about 450 MB). It takes a few minutes and shows progress; press `q` when the status reads `ACTIVE` (that only closes the display). One task is enough for a group and keeps download links for large objects working, since those live in the task's memory.

**Step 5. Check it at its own address.**

```
aws ecs describe-express-gateway-service --region us-east-2 --service-arn SERVICE_ARN --query 'service.activeConfigurations[0].ingressPaths[0].endpoint' --output text
```

prints `SERVICE_URL`. Then `curl SERVICE_URL/health` should print `{"status":"ok","endpoints":37,...}`.

**Step 6. Give it the name `mp.forum-ai.org`.** Required before the plugin works: it connects to `https://mp.forum-ai.org/mcp` and nothing else. A certificate, one load-balancer change and one DNS record, after AWS's guide [Updating Resources Outside of Express Mode](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-advanced-customization.html).

6a. Request the certificate and print the DNS record that proves you own the name:

```
aws acm request-certificate --region us-east-2 --domain-name mp.forum-ai.org --validation-method DNS --query CertificateArn --output text
aws acm describe-certificate --region us-east-2 --certificate-arn CERT_ARN --query 'Certificate.DomainValidationOptions[0].ResourceRecord' --output table
```

At the DNS provider, add a CNAME with exactly that Name and Value. Within a few minutes `aws acm describe-certificate --region us-east-2 --certificate-arn CERT_ARN --query Certificate.Status --output text` prints `ISSUED`. Wait for that.

6b. In the AWS console: EC2 → Load balancers → the one whose name contains `mp-mcp`. Write down its DNS name (`LB_DNS`). On its HTTPS:443 listener: under Certificates, add `CERT_ARN`; under Rules, edit the rule that forwards to the service and add `mp.forum-ai.org` as a second value of its Host header condition.

6c. At the DNS provider, add a CNAME `mp` pointing at `LB_DNS`.

**Step 7. Check it at the name.** `curl https://mp.forum-ai.org/health` prints the same line as step 5, and `https://mp.forum-ai.org` in a browser shows the server's own page. The `.on.aws` address keeps working too.

**Step 8. Make every merge to `main` deploy itself (optional).** In the GitHub repository, Settings → Secrets and variables → Actions: secrets `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` (an IAM user allowed to push to the ECR repository and update the service); variables `AWS_DEPLOY` = `true`, `AWS_REGION` = `us-east-2`, `ECR_REPOSITORY` = `mp-mcp`, `ECS_SERVICE_ARN` = `SERVICE_ARN`, `PUBLIC_URL` = `https://mp.forum-ai.org`. The workflow in `.github/workflows/deploy.yml` then builds, pushes and updates the service after the tests pass.

**Step 9. To update by hand instead**, repeat step 2 with a new tag (`:v2`), then:

```
aws ecs update-express-gateway-service --region us-east-2 --service-arn SERVICE_ARN \
  --primary-container '{"image":"ACCOUNT_ID.dkr.ecr.us-east-2.amazonaws.com/mp-mcp:v2","containerPort":8000,"environment":[{"name":"MP_MCP_HOSTED","value":"1"},{"name":"MP_MCP_PUBLIC_URL","value":"https://mp.forum-ai.org"}]}' \
  --cpu 1 --memory 2 --health-check-path /health \
  --monitor-resources
```

**When something goes wrong.** `aws ecs describe-express-gateway-service --region us-east-2 --service-arn SERVICE_ARN` shows the status; the logs are in CloudWatch, in the log group that output names. A 503 means no healthy task: look for a startup error in the logs and check that `/health` answers. A server that cannot reach the MP spec still starts from its bundled snapshot and says `"spec": "bundled snapshot"` in `/health`. To remove everything: `aws ecs delete-express-gateway-service --region us-east-2 --service-arn SERVICE_ARN --monitor-resources`.

## Releasing a new plugin version

The server and the plugins release separately. A merge to `main` redeploys the server (step 8 above), and every installed plugin reaches the new server at once, because a plugin only points at `https://mp.forum-ai.org/mcp`. New tools, fixes and changes to the server's instructions therefore need no plugin release. Release the plugin when something a client installs changes: the skill in `skills/`, a manifest, the key prompt or the URL.

These files are what clients install:

| File | Read by |
|---|---|
| `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | Claude Code |
| `plugin.json`, `mcp.json`, `.agents/plugins/marketplace.json` | Codex |
| `.antigravity-plugin/plugin.json`, `mcp_config.json` | Antigravity |
| `gemini-extension.json` | Gemini CLI |
| `skills/materials-project/SKILL.md` | all four |

Each client reads only its own manifest, so the version appears in five places: `pyproject.toml` and the four `plugin.json`-style files. Claude's marketplace entry carries no version on purpose; Claude Code reads it from `.claude-plugin/plugin.json`, and setting it in both is an error.

**Step 1. Set the new version, on a branch.**

```
python scripts/bump_version.py 0.5.0
```

It writes the version into all five files.

**Step 2. Check it.**

```
pytest -q -W ignore
claude plugin validate .
```

`tests/test_versions.py` fails if any file disagrees with `pyproject.toml`.

**Step 3. Merge it.** Open a pull request, wait for the `test` check, and merge.

**Step 4. Tag it, on GitHub.** Releases → Draft a new release → new tag `v0.5.0` on `main` → Publish release. Published tags are never moved or deleted.

**Step 5. Install it from scratch once,** in Claude Code, with the README's commands, and ask one question.

Installed copies update this way:

- **Claude Code:** users stay on their copy until the version string changes, which is why step 1 is what releases it. They get the new one with `claude plugin marketplace update forum-ai-mp-mcp`, or on their own if they turned on auto-update for the marketplace (`/plugin` → Marketplaces → Enable auto-update).
- **Gemini CLI:** it offers the update when `main` moves; `gemini extensions update mp-mcp` takes it at once.
- **Codex:** `codex plugin marketplace upgrade forum-ai-mp-mcp`.
- **Antigravity:** its documentation does not say how plugins installed from GitHub update; uninstalling and installing again works.

## Development

```
uv venv && uv pip install -e ".[test]"
pytest -q -W ignore
```

The tests run offline against the bundled spec snapshot and a stubbed MP API. CI runs them and builds the container on every push. With your key exported, `uv run evaluation/smoke_test.py` runs every tool against the live API (see `evaluation/README.md`).

| File | Holds |
|---|---|
| `src/mp_mcp/spec.py` | Reading the OpenAPI spec into endpoints, parameters and fields |
| `src/mp_mcp/keys.py` | Whose key a request uses |
| `src/mp_mcp/objects.py` | Finding `mp-api` object methods, summaries, plots and structure formats, large-object delivery |
| `scripts/bump_version.py` | Sets the release version in every file that carries one |
| `src/mp_mcp/server.py` | The tools, the download and health routes, and the command line |
| `evaluation/` | The live smoke test, and twelve questions with an answer key for comparing setups |

The only hand-written parts are the server's instruction paragraph, the summary for each pymatgen object type (band structure, DOS, phonons, phase diagram, structure, charge density, entries), and the guards. Everything an endpoint accepts or returns comes from MP.

## Evaluating it

`evaluation/` holds a live smoke test of every tool and twelve questions, from a control (silicon) through property screens, rankings and whole objects (a sorted list of the stiffest binary oxides, silicon's phonon dispersion, a CIF of the conventional cell). With your key exported:

```
export MP_API_KEY=your_key_here
uv run evaluation/smoke_test.py      # every tool against the live API, pass/fail per request
uv run evaluation/answer_key.py      # writes evaluation/answer_key.md, the correct answers for today's database
```

`evaluation/README.md` has the prompts, what each one tests, and the scoring sheet for running the same model with no tools, with other MP connectors and with this one.
