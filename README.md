# mp-mcp: the Materials Project for any AI assistant

An MCP server that gives Claude, Gemini, Codex and other AI clients the whole Materials Project: every REST endpoint with every filter, the band structures, densities of states, phonons, phase diagrams and other objects that `mp-api` returns, and MP's own documentation.

Nothing about the API is written down in this repository. At startup the server reads the MP API's own OpenAPI spec (`https://api.materialsproject.org/openapi.json`: 37 endpoints, 846 described parameters today) and walks the installed `mp-api` client for its object methods. A new endpoint, filter or field appears the next time the server restarts, with no code change.

## Tools

| Tool | What it does |
|---|---|
| `list_endpoints` | Every MP REST endpoint, one line each |
| `describe_endpoint(path, search)` | One endpoint's filters and returned fields, with the descriptions MP publishes |
| `query(path, fields, params, limit, sort, body)` | Runs one endpoint; returns the total number of matches and the rows as JSON |
| `list_objects(search)` | The `mp-api` methods that return whole objects (36 today) |
| `get_object(method, args, format)` | Calls one. `summary`: readable text plus a plot. `json`: the full pymatgen object (`as_dict`), inline when small, else a file or a download link |
| `docs_search(query)`, `docs_page(url)` | MP's documentation, through the docs site's own MCP server |

A typical session: `list_endpoints`, then `describe_endpoint("/materials/summary/", "gap")`, then

```
query("/materials/summary/", fields=["material_id", "formula_pretty", "band_gap"],
      params={"elements": "Ba,O", "nelements_max": 3, "is_stable": true, "band_gap_min": 2, "band_gap_max": 3})
```

Guards: at most 500 rows and 20,000 characters per query (cut to fit, with a note), a 60-second timeout, and read-only access. The whole tool listing is about 4,400 characters, so connecting the server costs a conversation about 1,100 tokens.

## Your API key

Every request runs under the caller's own MP API key (get one at <https://next-gen.materialsproject.org/api>).

- **Hosted** (`MP_MCP_HOSTED=1`, set in the container): the key comes only from the caller's `X-API-KEY` header and goes straight to the MP API on that request. The server stores nothing and never falls back to a key of its own.
- **Local**: the caller's header if present, else `MP_API_KEY`, else `PMG_MAPI_KEY` in `~/.config/.pmgrc.yaml`. Anyone who already uses `mp-api` needs no setup.

## Use it

### Claude Code (recommended): the plugin

```
/plugin install mp-mcp --marketplace forum-ai/mp-mcp
```

Claude Code asks for your MP API key once and keeps it in your system keychain. After that the server is available in every project, and Claude uses it on its own whenever a question needs Materials Project data. The plugin runs the server on your machine, so it needs [uv](https://docs.astral.sh/uv/), and, while this repository is private, a GitHub login that can read `forum-ai` (`gh auth login`).

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
uv run mp-mcp --transport http --port 8000     # http://localhost:8000/mcp
```

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `MP_MCP_HOSTED` | unset (`1` in the container) | Accept keys only from the caller's `X-API-KEY` header |
| `MP_MCP_PUBLIC_URL` | the request's own URL | Base URL for download links of large objects; set it to the service's https URL when hosted |
| `MP_MCP_TRANSPORT` | `stdio` (`http` in the container) | `stdio` or `http` |
| `PORT`, `HOST` | `8000`, `0.0.0.0` | HTTP listen address; the MCP endpoint is `/mcp`, the health check `/health` |
| `MP_API_ENDPOINT` | `https://api.materialsproject.org` | MP API to call |
| `MP_MCP_SPEC_URL` | `MP_API_ENDPOINT/openapi.json` | Spec to read at startup; `bundled` uses the snapshot in the package |
| `MP_MCP_MAX_ROWS`, `MP_MCP_MAX_CHARS`, `MP_MCP_TIMEOUT` | `500`, `20000`, `60` | Query guards |
| `MP_MCP_INLINE_BYTES`, `MP_MCP_LINK_TTL` | `50000`, `3600` | Largest JSON object returned inline; lifetime of a download link in seconds |
| `MP_MCP_OUTPUT_DIR` | `./mp_objects` | Where a local server writes large objects |
| `MP_MCP_DOCS_URL` | `https://docs.materialsproject.org/~gitbook/mcp` | MP's docs MCP server; empty to turn the docs tools off |

If the live spec cannot be fetched at startup, the server uses the snapshot in `src/mp_mcp/openapi_snapshot.json` and says so in `/health`.

## Deploy on AWS

This runs the server on Amazon ECS Express Mode, the same service the current chatbot runs on (its address ends in `.ecs.us-east-2.on.aws`). Express Mode creates the load balancer, HTTPS certificate, scaling and logs itself. Every command below is run from a terminal in a clone of this repository. Replace `ACCOUNT_ID` with the 12-digit AWS account number (`aws sts get-caller-identity --query Account --output text` prints it).

**What you need:** the AWS CLI v2, logged in to the account that runs the current server (`aws configure`), and Docker. The steps use `us-east-2`, where the current server runs.

**Step 1. Create a place for the image (once).**

```
aws ecr create-repository --repository-name mp-mcp --region us-east-2
```

**Step 2. Build the image and upload it.**

```
aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin ACCOUNT_ID.dkr.ecr.us-east-2.amazonaws.com
docker build --platform linux/amd64 -t ACCOUNT_ID.dkr.ecr.us-east-2.amazonaws.com/mp-mcp:v1 .
docker push ACCOUNT_ID.dkr.ecr.us-east-2.amazonaws.com/mp-mcp:v1
```

**Step 3. Create the two roles ECS needs (once; skip if they already exist).** Running `aws iam get-role --role-name ecsTaskExecutionRole` tells you whether they exist.

```
aws iam create-role --role-name ecsTaskExecutionRole --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name ecsTaskExecutionRole --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
aws iam create-role --role-name ecsInfrastructureRoleForExpressServices --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name ecsInfrastructureRoleForExpressServices --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices
```

If the next step then fails with an "unable to assume" error, wait a minute for the roles to propagate and run it again.

**Step 4. Create the service.**

```
aws ecs create-express-gateway-service --region us-east-2 \
  --service-name mp-mcp \
  --execution-role-arn arn:aws:iam::ACCOUNT_ID:role/ecsTaskExecutionRole \
  --infrastructure-role-arn arn:aws:iam::ACCOUNT_ID:role/ecsInfrastructureRoleForExpressServices \
  --primary-container '{"image":"ACCOUNT_ID.dkr.ecr.us-east-2.amazonaws.com/mp-mcp:v1","containerPort":8000,"environment":[{"name":"MP_MCP_HOSTED","value":"1"}]}' \
  --health-check-path /health \
  --scaling-target '{"minTaskCount":1,"maxTaskCount":1}' \
  --monitor-resources
```

It takes a few minutes. When the status reads `ACTIVE`, note two things from the output: the service ARN (`arn:aws:ecs:us-east-2:...:service/default/mp-mcp`) and the URL (`https://mp-mcp-....ecs.us-east-2.on.aws`). If you interrupted the monitor, `aws ecs describe-express-gateway-service --service-arn SERVICE_ARN --region us-east-2` shows both again.

One task is enough for a group, and it keeps the download links for large objects working: those links live in the memory of the task that made them. Raise `maxTaskCount` only after moving that store to S3.

**Step 5. Tell the server its public address**, so its download links use https.

```
aws ecs update-express-gateway-service --region us-east-2 --service-arn SERVICE_ARN \
  --primary-container '{"image":"ACCOUNT_ID.dkr.ecr.us-east-2.amazonaws.com/mp-mcp:v1","containerPort":8000,"environment":[{"name":"MP_MCP_HOSTED","value":"1"},{"name":"MP_MCP_PUBLIC_URL","value":"https://SERVICE_URL"}]}' \
  --monitor-resources
```

**Step 6. Check that it works.**

```
curl https://SERVICE_URL/health
```

should print something like `{"status":"ok","endpoints":37,"object_methods":36,"spec":"https://api.materialsproject.org/openapi.json"}`. Then connect a client (see "Use it" above) with `https://SERVICE_URL/mcp` and ask something like "What is the band gap of mp-149 according to the Materials Project?". The MCP Inspector (`npx @modelcontextprotocol/inspector`) also connects to the URL and lists the tools.

**Step 7. Make every merge to `main` deploy itself (optional, recommended).** The workflow in `.github/workflows/deploy.yml` builds, pushes and updates the service after the tests pass. In the GitHub repository, under Settings → Secrets and variables → Actions:

- Secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (an IAM user allowed to push to the ECR repository and update the ECS service)
- Variables: `AWS_DEPLOY` = `true`, `AWS_REGION` = `us-east-2`, `ECR_REPOSITORY` = `mp-mcp`, `ECS_SERVICE_ARN` = the ARN from step 4, `PUBLIC_URL` = `https://SERVICE_URL`

To deploy by hand instead, repeat step 2 with a new tag (`:v2`) and step 5 with that tag.

**Step 8. Keep the old address (optional).** To serve this from `mp-mcp.materialscopilot.org` like the current server, point that name at the new service URL the same way it points at the current load balancer today. Retire the old service once clients have moved.

**When something goes wrong.** The logs are in CloudWatch, in the log group the `describe-express-gateway-service` output names. A 503 from the address means no healthy task. Check the logs for a startup error, and check that `/health` answers. A server that cannot reach the MP spec still starts, from the bundled snapshot, and `/health` then reports `"spec": "bundled snapshot"`.

## Development

```
uv venv && uv pip install -e ".[test]"
pytest -q -W ignore
```

The tests run offline against the bundled spec snapshot and a stubbed MP API. CI runs them and builds the container on every push.

| File | Holds |
|---|---|
| `src/mp_mcp/spec.py` | Reading the OpenAPI spec into endpoints, parameters and fields |
| `src/mp_mcp/keys.py` | Whose key a request uses |
| `src/mp_mcp/objects.py` | Finding `mp-api` object methods, summaries and plots, large-object delivery |
| `src/mp_mcp/server.py` | The tools, the download and health routes, and the command line |
| `bakeoff/` | Five questions and a live answer key for comparing setups |

The only hand-written parts are the server's instruction paragraph, the summary for each pymatgen object type (band structure, DOS, phonons, phase diagram, structure, entries), and the guards. Everything an endpoint accepts or returns comes from MP.

## Comparing it with other setups

`bakeoff/` holds five questions that run from a control (silicon) to a screen the old MP MCP could not express (stable Ba ternary oxides with 2–3 eV gaps). It has a script that computes the answer key from the live API (`MP_API_KEY=... ./bakeoff/make_answer_key.sh`) and a scoring sheet. Run the same model with no tools, with the old server and with this one.
