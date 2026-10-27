# mp-mcp: the Materials Project for any AI assistant

An MCP server that gives Claude, Gemini, Codex and other AI clients the whole Materials Project: every REST endpoint with every filter, the band structures, densities of states, phonons, phase diagrams and other objects that `mp-api` returns, and MP's own documentation.

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

Guards: at most 500 rows and 20,000 characters per query (cut to fit, with a note), a 60-second timeout on every MP call, objects of at most 50 MB, and read-only access. The whole tool listing is about 4,400 characters, so connecting the server costs a conversation about 1,100 tokens.

## Design

Each choice below follows from what an AI assistant needs in order to answer a materials question correctly, and from what goes wrong when it does not have it.

- **The API describes itself; this repository writes none of it down.** Endpoints, filters, field names and their descriptions are read from MP's OpenAPI spec at startup, and object methods from the installed `mp-api`. MP adds endpoints and fields with every release; a hand-written tool list goes stale and silently hides data, while a tool generated from the live spec cannot drift from it.
- **Five general tools, not one per endpoint.** A client pays for the tool listing in context on every conversation. Thirty-seven endpoints with 846 parameters as separate tools would cost tens of thousands of tokens and still leave filters out; `list_endpoints`, `describe_endpoint` and `query` cost about 1,100 tokens and reach all of it, and the model reads the details of only the endpoint it needs, when it needs them.
- **Everything needed to form a correct call is returned as text the model can read.** Filter names with MP's own descriptions, field names, whether the endpoint sorts, whether its fields are documented. REST APIs ignore parameters they do not know, so a guessed filter name produces a plausible but wrong answer with no error; a model that can see the real names does not have to guess.
- **The model chooses fields and limits; the server bounds them.** Rows, characters, time and object size all have ceilings, and when a result is cut the response says so and how to narrow it. An unbounded result floods the conversation and ends it; a bounded one with a note lets the model ask again more precisely.
- **Objects come in two registers.** Band structures, densities of states, phonons, phase diagrams and Wulff shapes are not tables. The summary answers the question in the chat (gap, transition, imaginary modes, stable phases) with the plot a person would draw; the JSON is the complete pymatgen object for an agent that continues in Python; a structure can also come as CIF or POSCAR, since that is how people hand structures to other programs.
- **Keys belong to callers.** An MP key is personal: it carries the holder's rate limit and their access to restricted datasets. The hosted server therefore has no key of its own and forwards each request under the caller's header, so one user can never spend or expose another's; the local server finds a key the way `mp-api` does, so existing users need no setup.
- **Read-only, and nothing persists.** The server can change nothing at MP, writes nothing about its users, and download links expire. Anything reachable from a chat window should be safe to point an untrusted conversation at.
- **Errors are loud and in plain words; nothing fails silently.** Asking to sort an endpoint that cannot sort is an error, not an unsorted list, because the model would otherwise report the list as sorted. Timeouts, bad arguments and upstream failures say what happened and what to change.
- **Identifiers as people know them.** MP stores AlphaIDs; responses are requested in the `mp-149` form wherever the API allows, because that is the form in papers, on the website and in users' notes.
- **Startup never depends on the network.** The spec falls back to a bundled snapshot and object discovery runs offline, so an MP outage degrades answers rather than taking every conversation down with the server.
- **Methodology comes from MP's documentation, not from a paraphrase.** How a hull energy or a band gap is computed changes between releases; the docs tools read MP's documentation server live.

## Your API key

Every request runs under the caller's own MP API key (get one at <https://next-gen.materialsproject.org/api>).

- **Hosted** (`MP_MCP_HOSTED=1`, set in the container): the key comes only from the caller's `X-API-KEY` header and goes straight to the MP API on that request. The server stores nothing and never falls back to a key of its own.
- **Local**: the caller's header if present, else `MP_API_KEY`, else `PMG_MAPI_KEY` in `~/.config/.pmgrc.yaml`. Anyone who already uses `mp-api` needs no setup.

## Use it

### Claude Code (recommended): the plugin

You need [uv](https://docs.astral.sh/uv/) installed, and, while this repository is private, a GitHub login that git can use:

```
gh auth login
gh auth setup-git
```

Then, inside a Claude Code session:

```
/plugin marketplace add forum-ai/mp-mcp
/plugin install mp-mcp@forum-ai-mp-mcp
```

(On Claude Code 2.1.275 or later, `/plugin install mp-mcp --marketplace forum-ai/mp-mcp` does both in one step.) Claude Code asks for your MP API key when it installs the plugin and keeps it in your system keychain; if no prompt appears, run `/plugin configure mp-mcp@forum-ai-mp-mcp`. After that the server is available in every project, and Claude uses it on its own whenever a question needs Materials Project data. The plugin runs the server on your machine, outside Claude Code's sandbox, with your key in its environment; the first start takes a minute while `uv` builds the environment. In a permission allowlist its tools are named `mcp__plugin_mp-mcp_materials-project__<tool>`.

### Claude Code: the hosted server

```
claude mcp add --transport http --scope user materials-project https://YOUR-SERVICE-URL/mcp --header "X-API-KEY: YOUR_MP_KEY"
```

### Claude Desktop and claude.ai

Settings → Connectors → Add custom connector, with the URL `https://YOUR-SERVICE-URL/mcp`. A static `X-API-KEY` header there is an organization-level beta ("Request headers"); without it, use Claude Code or run the server locally.

### Gemini CLI (`~/.gemini/settings.json`)

```json
{ "mcpServers": { "materials-project": {
    "httpUrl": "https://YOUR-SERVICE-URL/mcp",
    "headers": { "X-API-KEY": "YOUR_MP_KEY" } } } }
```

### Google Antigravity (`mcp_config.json`)

```json
{ "mcpServers": { "materials-project": {
    "serverUrl": "https://YOUR-SERVICE-URL/mcp",
    "headers": { "X-API-KEY": "YOUR_MP_KEY" } } } }
```

### Any MCP client, locally

```
uv run mp-mcp                                  # stdio
uv run mp-mcp --transport http --port 8000     # http://127.0.0.1:8000/mcp, this machine only
```

A local HTTP server answers with your own key, so it listens on `127.0.0.1` unless you pass `--host`.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `MP_MCP_HOSTED` | unset (`1` in the container) | Accept keys only from the caller's `X-API-KEY` header; listen on all interfaces |
| `MP_MCP_PUBLIC_URL` | the request's own URL | Base URL for download links of large objects; set it to the service's https URL when hosted |
| `MP_MCP_TRANSPORT` | `stdio` (`http` in the container) | `stdio` or `http` |
| `PORT`, `HOST` | `8000`, `127.0.0.1` (`0.0.0.0` when hosted) | HTTP listen address; the MCP endpoint is `/mcp`, the health check `/health` |
| `MP_API_ENDPOINT` | `https://api.materialsproject.org` | MP API to call |
| `MP_MCP_SPEC_URL` | `MP_API_ENDPOINT/openapi.json` | Spec to read at startup; `bundled` uses the snapshot in the package |
| `MP_MCP_MAX_ROWS`, `MP_MCP_MAX_CHARS`, `MP_MCP_TIMEOUT` | `500`, `20000`, `60` | Query guards; the timeout also applies to `get_object` |
| `MP_MCP_INLINE_BYTES`, `MP_MCP_LINK_TTL` | `50000`, `3600` | Largest JSON object returned inline; lifetime of a download link in seconds |
| `MP_MCP_MAX_OBJECT_BYTES`, `MP_MCP_STORE_BYTES` | `50000000`, `256000000` | Largest object served at all; memory the hosted server gives to download links (oldest go first) |
| `MP_MCP_OUTPUT_DIR` | `~/.cache/mp-mcp/objects` | Where a local server writes large objects |
| `MP_MCP_ID_FORMAT` | `legacy` | MP stores identifiers as AlphaIDs (`mp-aaaaaaft`) and returns them that way unless asked; `legacy` asks for `mp-149`-style ids on the 25 endpoints that offer the choice. Empty to leave them as stored |
| `MP_MCP_DOCS_URL` | `https://docs.materialsproject.org/~gitbook/mcp` | MP's docs MCP server; empty to turn the docs tools off |

If the live spec cannot be fetched at startup, the server uses the snapshot in `src/mp_mcp/openapi_snapshot.json` and says so in `/health`. Startup needs no network at all.

## Deploy on AWS

This runs the server on Amazon ECS Express Mode, which gives it an address ending in `.ecs.us-east-2.on.aws`. Express Mode creates the load balancer, HTTPS certificate, scaling and logs itself. Every command below is run from a terminal in a clone of this repository, one at a time, in order. Replace `ACCOUNT_ID` with the 12-digit AWS account number everywhere it appears (step 1 prints it).

**What you need before you start:**

- The [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html), logged in to your AWS account (`aws configure`, then `aws sts get-caller-identity` prints your account without error).
- [Docker Desktop](https://docs.docker.com/desktop/), running (the whale icon in the menu bar).
- The account's default VPC in `us-east-2` must still exist (it does unless someone deleted it; Express Mode puts its load balancer there).

**Step 1. Find your account number.**

```
aws sts get-caller-identity --query Account --output text
```

Copy the 12 digits it prints; they replace `ACCOUNT_ID` below.

**Step 2. Create a place for the image (once).**

```
aws ecr create-repository --repository-name mp-mcp --region us-east-2
```

If it says the repository already exists, that is fine.

**Step 3. Build the image and upload it.**

```
aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin ACCOUNT_ID.dkr.ecr.us-east-2.amazonaws.com
docker build --platform linux/amd64 -t ACCOUNT_ID.dkr.ecr.us-east-2.amazonaws.com/mp-mcp:v1 .
docker push ACCOUNT_ID.dkr.ecr.us-east-2.amazonaws.com/mp-mcp:v1
```

The build takes a few minutes the first time. The last line of the push ends with a `sha256:` digest when it worked.

**Step 4. Create the two roles ECS needs (once).** First check whether they already exist:

```
aws iam get-role --role-name ecsTaskExecutionRole --query Role.Arn --output text
aws iam get-role --role-name ecsInfrastructureRoleForExpressServices --query Role.Arn --output text
```

If both print an ARN, skip to step 5. If one says `NoSuchEntity`, create it (these are the exact roles and policies from AWS's Express Mode tutorial):

```
aws iam create-role --role-name ecsTaskExecutionRole --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name ecsTaskExecutionRole --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
aws iam create-role --role-name ecsInfrastructureRoleForExpressServices --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name ecsInfrastructureRoleForExpressServices --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices
```

Then wait one minute before step 5: new roles take a moment to become usable, and the first `create` can fail with "unable to assume" if you are too quick. If that happens, wait and run step 5 again.

**Step 5. Create the service.**

```
aws ecs create-express-gateway-service --region us-east-2 \
  --service-name mp-mcp \
  --execution-role-arn arn:aws:iam::ACCOUNT_ID:role/ecsTaskExecutionRole \
  --infrastructure-role-arn arn:aws:iam::ACCOUNT_ID:role/ecsInfrastructureRoleForExpressServices \
  --primary-container '{"image":"ACCOUNT_ID.dkr.ecr.us-east-2.amazonaws.com/mp-mcp:v1","containerPort":8000,"environment":[{"name":"MP_MCP_HOSTED","value":"1"}]}' \
  --cpu 1 --memory 2 \
  --health-check-path /health \
  --scaling-target '{"minTaskCount":1,"maxTaskCount":1}' \
  --monitor-resources
```

`--cpu 1 --memory 2` means 1 vCPU and 2 GB; the server uses about 450 MB once it has loaded pymatgen, so the smaller default would be tight. It takes a few minutes and shows progress; press `q` or Ctrl-C when the status reads `ACTIVE` (that only stops the display, not the service).

**Step 6. Write down the service's two addresses.** Run

```
aws ecs describe-express-gateway-service --region us-east-2 --service-arn arn:aws:ecs:us-east-2:ACCOUNT_ID:service/default/mp-mcp --query 'service.activeConfigurations[0].ingressPaths[0].endpoint' --output text
```

It prints the service's URL, which looks like `https://mp-mcp-abc123.ecs.us-east-2.on.aws`; call it `SERVICE_URL` below. The service ARN is the one in the command: `arn:aws:ecs:us-east-2:ACCOUNT_ID:service/default/mp-mcp`, called `SERVICE_ARN` below. If the `describe` command says the service does not exist, step 5 did not finish; look at its output.

One task is enough for a group, and it keeps the download links for large objects working: those links live in the memory of the task that made them. Raise `maxTaskCount` only after moving that store to S3.

**Step 7. Tell the server its public address**, so its download links use https.

```
aws ecs update-express-gateway-service --region us-east-2 --service-arn SERVICE_ARN \
  --primary-container '{"image":"ACCOUNT_ID.dkr.ecr.us-east-2.amazonaws.com/mp-mcp:v1","containerPort":8000,"environment":[{"name":"MP_MCP_HOSTED","value":"1"},{"name":"MP_MCP_PUBLIC_URL","value":"SERVICE_URL"}]}' \
  --monitor-resources
```

**Step 8. Check that it works.**

```
curl SERVICE_URL/health
```

should print something like `{"status":"ok","endpoints":37,"object_methods":36,"spec":"https://api.materialsproject.org/openapi.json"}`. Then connect a client (see "Use it" above) with `SERVICE_URL/mcp` and ask something like "What is the band gap of mp-149 according to the Materials Project?". The MCP Inspector (`npx @modelcontextprotocol/inspector`) also connects to the URL and lists the tools.

**Step 9. Make every merge to `main` deploy itself (optional, recommended).** The workflow in `.github/workflows/deploy.yml` builds, pushes and updates the service after the tests pass. In the GitHub repository, under Settings → Secrets and variables → Actions:

- Secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (an IAM user allowed to push to the ECR repository and update the ECS service)
- Variables: `AWS_DEPLOY` = `true`, `AWS_REGION` = `us-east-2`, `ECR_REPOSITORY` = `mp-mcp`, `ECS_SERVICE_ARN` = `SERVICE_ARN`, `PUBLIC_URL` = `SERVICE_URL`

To deploy by hand instead, repeat step 3 with a new tag (`:v2`) and step 7 with that tag.

**Step 10. Use your own domain name (optional).** To serve this from a name you own, such as `mp-mcp.materialscopilot.org`, point that name at `SERVICE_URL` in your DNS provider. If an older service was behind that name, retire it once clients have moved.

**When something goes wrong.** `aws ecs describe-express-gateway-service --region us-east-2 --service-arn SERVICE_ARN` shows the status; the logs are in CloudWatch, in the log group that output names. A 503 from the address means no healthy task: check the logs for a startup error, and check that `SERVICE_URL/health` answers. A server that cannot reach the MP spec still starts, from the bundled snapshot, and `/health` then reports `"spec": "bundled snapshot"`. To remove everything, `aws ecs delete-express-gateway-service --region us-east-2 --service-arn SERVICE_ARN --monitor-resources`.

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
