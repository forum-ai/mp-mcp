"""The Materials Project MCP server.

Five tools reach all of the MP API, and MP's own docs server is mounted beside them:

  list_endpoints     every REST endpoint, from the live OpenAPI spec
  describe_endpoint  one endpoint's parameters and returned fields, with their descriptions
  query              run one endpoint with filters, chosen fields and a row limit
  list_objects       the mp-api get_* methods for band structures, DOS, phonons, phase diagrams...
  get_object         call one, as a readable summary with a plot, as full pymatgen JSON, or as cif/poscar
  docs_search        search MP's documentation, through the docs site's own MCP server
  docs_page          read one documentation page
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from typing import Annotated, Any, Literal

import anyio
import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from fastmcp.utilities.types import Image
from mcp.types import TextContent, ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from mp_mcp import objects, spec
from mp_mcp.keys import MissingKey, api_key, hosted

log = logging.getLogger("mp_mcp")

MAX_ROWS = int(os.environ.get("MP_MCP_MAX_ROWS", 500))
MAX_CHARS = int(os.environ.get("MP_MCP_MAX_CHARS", 20_000))
TIMEOUT = float(os.environ.get("MP_MCP_TIMEOUT", 60))
ID_FORMAT = os.environ.get("MP_MCP_ID_FORMAT", "legacy")  # MP stores AlphaIDs (mp-aaaaaaft); people know mp-149
DOCS_MCP = os.environ.get("MP_MCP_DOCS_URL", "https://docs.materialsproject.org/~gitbook/mcp")
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

# The query tool's own arguments, and the query-string names an endpoint may declare for them.
# An argument is sent only under a name the endpoint's spec lists; the first match wins.
CONTROL = {"fields": ("_fields",), "limit": ("_limit", "limit"), "sort": ("_sort_fields",), "id_format": ("id_format",)}


def _t(text: str) -> TextContent:
    return TextContent(type="text", text=text)

INSTRUCTIONS = """\
Live access to the Materials Project (MP): computed structures and properties of inorganic \
materials and molecules. Use it for any question about a material's stability, band gap, \
band structure, elastic, dielectric, magnetic, phonon, electrode or surface properties, \
synthesis or similar materials. Work in this order: list_endpoints, describe_endpoint for \
the one you need, then query with a few fields and a small limit. /materials/summary/ holds \
most properties of a material in one document (energy_above_hull, band_gap, is_stable, k_vrh, \
ordering, ...); /materials/thermo/ returns one document per functional (thermo_types). For a \
count, query with limit=1 and read the total; for more rows than the limit, pass _skip in params. \
For band structures, densities of states, phonons, phase diagrams and other objects, use \
list_objects and get_object; a structure comes as cif or poscar with format='cif'. For how MP \
computes a value, use docs_search. Cite material_ids."""


LANDING = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Materials Project MCP server</title>
<style>body{{font-family:system-ui,sans-serif;max-width:44em;margin:3em auto;padding:0 1em;line-height:1.5}}code,pre{{background:#f3f3f3;padding:.1em .3em}}pre{{padding:.6em;overflow-x:auto}}h2{{margin-top:1.6em}}</style></head>
<body><h1>Materials Project MCP server</h1>
<p>Live <a href="https://materialsproject.org">Materials Project</a> data for AI assistants: {n} REST endpoints with every filter, {m} object methods (band structures, densities of states, phonons, phase diagrams, structures as CIF), and MP's documentation. Built by FORUM-AI. You need a <a href="https://next-gen.materialsproject.org/api">Materials Project API key</a>; every request runs under your own key and the server keeps none.</p>
<h2>Claude Code</h2>
<ol><li>Type <code>/plugin install mp-mcp --marketplace forum-ai/mp-mcp</code>.</li><li>Paste your key when asked.</li><li>Ask a materials question.</li></ol>
<h2>Gemini CLI</h2>
<ol><li><code>gemini extensions install https://github.com/forum-ai/mp-mcp</code></li><li>Enter your key when asked.</li><li>Ask a materials question.</li></ol>
<h2>Codex</h2>
<ol><li>Add to <code>~/.codex/config.toml</code>:<pre>[mcp_servers.materials-project]
url = "{base}/mcp"
env_http_headers = {{ "X-API-KEY" = "MP_API_KEY" }}</pre></li><li><code>export MP_API_KEY=your_key</code> in your shell profile.</li><li>Ask a materials question.</li></ol>
<h2>Any other MCP client</h2>
<p>Connect to <code>{base}/mcp</code> (Streamable HTTP) with your key in an <code>X-API-KEY</code> header.</p>
<p><a href="{base}/health">health</a> · <a href="https://github.com/forum-ai/mp-mcp">source and full instructions</a></p></body></html>"""


def _coerce(v: Any) -> Any:
    """A filter value as the MP API wants it on the query string."""
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, (list, tuple)):
        return ",".join(str(_coerce(x)) for x in v)
    return v


def _rows(payload: Any) -> tuple[list, Any]:
    """The documents and the total count from whatever JSON the API returned: normally
    {"data": [...], "meta": {"total_doc": n}}, but a bare list or a single document also work."""
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    rows = data if isinstance(data, list) else [data] if data else []
    total = (payload.get("meta") or {}).get("total_doc") if isinstance(payload, dict) else None
    return rows, total


def _fit(rows: list, budget: int) -> tuple[str, int, str]:
    """As many leading rows as fit in budget characters, as a JSON list, with a note when
    some were left out; a first row that alone exceeds the budget is cut."""
    parts = [json.dumps(r, default=str) for r in rows]
    shown, used = 0, 2
    while shown < len(parts) and used + len(parts[shown]) + (2 if shown else 0) <= budget:
        used += len(parts[shown]) + (2 if shown else 0)
        shown += 1
    if parts and shown == 0:
        return (f"[{parts[0][:budget]}... [{len(parts[0]):,} characters; ask for fewer fields]]", 1,
                " Cut to 1 row and truncated it to fit; ask for fewer fields.")
    note = "" if shown == len(parts) else f" Cut to {shown} rows to fit; ask for fewer fields or rows."
    return "[" + ", ".join(parts[:shown]) + "]", shown, note


def build_server(spec_url: str | None = None, mount_docs: bool = True) -> FastMCP:
    api_spec, source = spec.load_spec(spec_url)
    eps = spec.endpoints(api_spec)
    methods = objects.discover()
    store = objects.Store()
    log.info("Loaded %d endpoints from %s and %d object methods from mp-api", len(eps), source, len(methods))

    mcp = FastMCP("materials-project", instructions=INSTRUCTIONS)

    def endpoint(path: str) -> spec.Endpoint:
        ep = eps.get(spec.normalize(path))
        if ep is None:
            raise ToolError(f"No endpoint {path!r}. Use a path from list_endpoints, e.g. /materials/summary/.")
        return ep

    def key() -> str:
        try:
            return api_key()
        except MissingKey as exc:
            raise ToolError(str(exc)) from None

    def control(ep: spec.Endpoint, arg: str) -> str | None:
        """The query-string name this endpoint declares for one of query's arguments, or None."""
        return next((n for n in CONTROL[arg] if ep.has_param(n)), None)

    @mcp.tool(annotations=READ_ONLY)
    def list_endpoints():
        """List every Materials Project REST endpoint with a one-line summary.
        Each path can be passed to describe_endpoint and query."""
        lines = [f"{ep.method} {ep.path}  {ep.summary}" for ep in eps.values()]
        return f"{len(lines)} endpoints (MP API, {source}):\n" + "\n".join(lines)

    @mcp.tool(annotations=READ_ONLY)
    def describe_endpoint(
        path: Annotated[str, Field(description="Endpoint path from list_endpoints, e.g. /materials/summary/")],
        search: Annotated[str, Field(description="Optional text to keep only matching parameters and fields, e.g. 'gap'")] = "",
    ):
        """Describe one endpoint: its query parameters (filters) and the fields its documents
        return, each with type and description, all read from the MP API's own spec. Parameters
        starting with _ control paging and projection; query sets _fields and _limit for you."""
        ep = endpoint(path)
        s = search.lower()

        def keep(name: str, info: dict[str, Any]) -> bool:
            return not s or s in name.lower() or s in info.get("description", "").lower()

        params = [p for p in ep.params if not p["name"].startswith("_") and keep(p["name"], p)]
        fields = {n: f for n, f in ep.fields.items() if keep(n, f)}
        out = [f"{ep.method} {ep.path}  {ep.summary}", "", f"Filters ({len(params)}):"]
        out += [f"  {p['name']} ({p['type']}): {p['description']}" for p in params]
        if ep.body:
            out += ["", f"Request body: {ep.body.get('description') or ep.body.get('title') or 'JSON object'}"]
        out += ["", "Sorting: " + ("pass sort='-field' to query; also filter on that field (e.g. field_min) so documents "
                                   "without it are left out." if control(ep, "sort")
                                   else "not supported by this endpoint; sort the rows yourself.")]
        if not ep.fields:
            out += ["", "Returned fields: not described in MP's spec. query returns the whole documents; leave fields empty."]
        else:
            out += ["", f"Returned fields ({len(fields)}), for the fields argument of query:"]
            out += [f"  {n} ({f['type']}): {f['description']}" for n, f in fields.items()]
        return "\n".join(out)

    @mcp.tool(annotations=READ_ONLY)
    async def query(
        path: Annotated[str, Field(description="Endpoint path from list_endpoints")],
        fields: Annotated[list[str] | None, Field(description="Returned fields to include (see describe_endpoint). Ask only for what you need; empty means the whole document.")] = None,
        params: Annotated[dict[str, Any] | None, Field(description="Filters from describe_endpoint, e.g. {'elements': 'Ba,O', 'nelements_max': 3, 'is_stable': True, 'band_gap_min': 2, 'band_gap_max': 3}. Lists become comma-separated. _skip pages past the limit.")] = None,
        limit: Annotated[int, Field(description=f"Maximum rows to return (at most {MAX_ROWS}). Use 1 to get just the total count.", ge=1)] = 20,
        sort: Annotated[str, Field(description="Optional comma-separated fields to sort by; prefix - for descending, e.g. '-band_gap'. Only some endpoints support it (describe_endpoint says).")] = "",
        body: Annotated[dict[str, Any] | None, Field(description="JSON body, only for POST endpoints such as /materials/core/find_structure/ (a pymatgen Structure as_dict)")] = None,
    ):
        """Run one Materials Project endpoint and return matching documents as JSON rows,
        with the total number of matches. Filters, fields and paths are exactly those of the
        MP API (describe_endpoint lists them)."""
        ep = endpoint(path)
        q: dict[str, Any] = {k: _coerce(v) for k, v in (params or {}).items() if v is not None}
        if fields and (name := control(ep, "fields")):
            q[name] = ",".join(fields)
        if name := control(ep, "limit"):
            q[name] = min(limit, MAX_ROWS)
        if sort:
            if not (name := control(ep, "sort")):
                raise ToolError(f"{ep.path} does not support sorting. Fetch the rows and sort them yourself, "
                                "or sort on /materials/summary/, which carries most properties and supports sort.")
            q[name] = sort
        if ID_FORMAT and (name := control(ep, "id_format")):
            q.setdefault(name, ID_FORMAT)
        headers = {"x-api-key": key(), "user-agent": "mp-mcp"}
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            try:
                r = await client.request(ep.method, f"{spec.API_ROOT}{ep.path}", params=q, headers=headers,
                                         json=body if ep.method != "GET" else None)
            except httpx.TimeoutException:
                raise ToolError(f"MP took longer than {TIMEOUT:.0f} s. Add filters or lower the limit.") from None
            except httpx.HTTPError as exc:
                raise ToolError(f"Could not reach the MP API ({type(exc).__name__}: {exc}). Try again shortly.") from None
        if r.status_code >= 400:
            raise ToolError(f"MP API returned {r.status_code}: {r.text[:500]}")
        try:
            rows, total = _rows(r.json())
        except ValueError:
            raise ToolError(f"MP API returned something that is not JSON (status {r.status_code}): {r.text[:300]}") from None
        text, shown, note = _fit(rows, MAX_CHARS)
        return f"{total if total is not None else '?'} matches; {shown} returned.{note}\n{text}"

    @mcp.tool(annotations=READ_ONLY)
    def list_objects(
        search: Annotated[str, Field(description="Optional text to filter by, e.g. 'bandstructure', 'phonon', 'phase_diagram', 'pourbaix'")] = "",
    ):
        """List the mp-api methods that return whole objects rather than query rows: band
        structures, densities of states, phonon band structures and DOS, phase diagrams,
        entries, Pourbaix entries, Wulff shapes, structures. Each line is a method name and
        its signature, for get_object."""
        return objects.describe(methods, search)

    @mcp.tool(annotations=READ_ONLY)
    async def get_object(
        method: Annotated[str, Field(description="Method name from list_objects, e.g. get_bandstructure_by_material_id or materials.thermo.get_phase_diagram_from_chemsys")],
        args: Annotated[dict[str, Any] | None, Field(description="Keyword arguments for the method, e.g. {'material_id': 'mp-149'} or {'material_id': 'mp-149', 'conventional_unit_cell': True}")] = None,
        format: Annotated[Literal["summary", "json", "cif", "poscar"], Field(description="summary: readable text plus a plot. json: the full pymatgen object (as_dict), inline when small, else a file path or download link; load it with monty.serialization.loadfn. cif or poscar: a structure as that text format (structures only).")] = "summary",
    ) -> list:
        """Call one mp-api object method and return its result: a short readable summary with
        a plot, the complete pymatgen object in JSON, or (for structures) a CIF or POSCAR."""
        if method not in methods:
            raise ToolError(f"No method {method!r}. Use a name from list_objects.")
        k = key()
        obj: Any = None
        with anyio.move_on_after(TIMEOUT) as scope:
            try:
                obj = await anyio.to_thread.run_sync(objects.call, k, method, args or {}, abandon_on_cancel=True)
            except TypeError as exc:
                raise ToolError(f"Bad arguments for {method}: {exc}") from None
            except Exception as exc:
                raise ToolError(f"{method} failed: {exc}") from None
        if scope.cancelled_caught:
            raise ToolError(f"{method} took longer than {TIMEOUT:.0f} s. Narrow the request (a smaller chemical system, "
                            "one material) or fetch it with mp-api directly.")
        if format in objects.STRUCTURE_FORMATS:
            try:
                return [_t(objects.structure_text(obj, format))]
            except TypeError as exc:
                raise ToolError(str(exc)) from None
        if format == "summary":
            text, png = await anyio.to_thread.run_sync(objects.summarize, obj)
            return [_t(text), Image(data=png, format="png")] if png else [_t(text)]
        try:
            data = await anyio.to_thread.run_sync(objects.to_json, obj)
        except objects.TooLarge as exc:
            raise ToolError(str(exc)) from None
        except (TypeError, ValueError) as exc:
            raise ToolError(f"{method} returned something that cannot be written as JSON ({exc}). Ask for the summary.") from None
        if len(data) <= objects.INLINE_LIMIT:
            return [_t(data.decode())]
        name = f"{method.replace('.', '_')}.json"
        try:
            request = get_http_request()
        except RuntimeError:
            request = None
        if request is None:  # stdio: the user's own machine
            path = objects.local_file(data, method, args or {})
            return [_t(f"{len(data):,} bytes written to {path}. Load it with monty.serialization.loadfn('{path}').")]
        base = os.environ.get("MP_MCP_PUBLIC_URL", "").rstrip("/") or str(request.base_url).rstrip("/")
        token = store.put(data, name)
        return [_t(f"{len(data):,} bytes. Download within {objects.LINK_TTL // 60} minutes: {base}/objects/{token} "
                f"(save as {name}, then monty.serialization.loadfn).")]

    @mcp.custom_route("/objects/{token}", methods=["GET"])
    async def download(request: Request) -> Response:
        item = store.get(request.path_params["token"])
        if item is None:
            return JSONResponse({"error": "expired or unknown link"}, status_code=404)
        data, name = item
        return Response(data, media_type="application/json",
                        headers={"content-disposition": f'attachment; filename="{name}"'})

    @mcp.custom_route("/", methods=["GET"])
    async def home(request: Request) -> Response:
        base = os.environ.get("MP_MCP_PUBLIC_URL", "").rstrip("/") or str(request.base_url).rstrip("/")
        return HTMLResponse(LANDING.format(base=base, n=len(eps), m=len(methods)))

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> Response:
        return JSONResponse({"status": "ok", "endpoints": len(eps), "object_methods": len(methods), "spec": source})

    if mount_docs and DOCS_MCP:
        # MP's documentation site runs its own MCP server (GitBook); these two tools call it,
        # so its search and pages arrive over this one connection.
        async def docs_call(tool: str, args: dict[str, Any]) -> str:
            from fastmcp import Client

            try:
                async with Client(DOCS_MCP, timeout=TIMEOUT) as c:
                    r = await c.call_tool(tool, args)
            except Exception as exc:
                raise ToolError(f"MP docs server unavailable ({exc}). Try https://docs.materialsproject.org/llms.txt") from None
            return "\n".join(getattr(b, "text", "") for b in r.content)

        @mcp.tool(annotations=READ_ONLY)
        async def docs_search(
            query: Annotated[str, Field(description="What to look up, e.g. 'energy above hull' or 'r2SCAN mixing scheme'")],
        ):
            """Search the Materials Project documentation (methodology, data definitions, API
            usage) and return matching passages with links to their pages."""
            return await docs_call("searchDocumentation", {"query": query})

        @mcp.tool(annotations=READ_ONLY)
        async def docs_page(
            url: Annotated[str, Field(description="A docs.materialsproject.org page URL, e.g. one returned by docs_search")],
        ):
            """Read one Materials Project documentation page in full, as markdown."""
            return await docs_call("getPage", {"url": url})
    return mcp


def main() -> None:
    ap = argparse.ArgumentParser(description="Materials Project MCP server")
    ap.add_argument("--transport", choices=["stdio", "http"], default=os.environ.get("MP_MCP_TRANSPORT", "stdio"))
    ap.add_argument("--host", default=os.environ.get("HOST"),
                    help="HTTP listen address. Default: 0.0.0.0 when MP_MCP_HOSTED=1, else 127.0.0.1 (the server's own key must not be reachable from other machines)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    server = build_server()
    if a.transport == "http":
        host = a.host or ("0.0.0.0" if hosted() else "127.0.0.1")
        if not hosted():
            log.warning("Serving over HTTP without MP_MCP_HOSTED=1: callers without a key use this server's key. "
                        "Listening on %s only.", host)
        server.run(transport="http", host=host, port=a.port, path="/mcp", stateless_http=True)
    else:
        server.run()


if __name__ == "__main__":
    main()
