import json

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from mp_mcp import objects
from tests.conftest import call, payload, text


async def test_tool_listing_is_small(mcp):
    async with Client(mcp) as c:
        tools = await c.list_tools()
    names = {t.name for t in tools}
    assert names == {"list_endpoints", "describe_endpoint", "query", "list_objects", "get_object"}
    size = sum(len(json.dumps([t.name, t.description, t.inputSchema, t.outputSchema])) for t in tools)
    assert size < 6000
    for t in tools:  # every parameter tells the model what it is
        for name, prop in t.inputSchema.get("properties", {}).items():
            assert prop.get("description"), f"{t.name}.{name} has no description"


async def test_list_and_describe(mcp):
    listing = text(await call(mcp, "list_endpoints", {}))
    assert "/materials/summary/" in listing and "/materials/phonon/" in listing
    desc = text(await call(mcp, "describe_endpoint", {"path": "materials/summary", "search": "gap"}))
    assert "band_gap_min" in desc and "band_gap (number)" in desc
    with pytest.raises(ToolError):
        await call(mcp, "describe_endpoint", {"path": "/no/such/"})


async def test_query_passes_filters_fields_and_key(mcp, mp_api):
    out = await call(mcp, "query", {
        "path": "/materials/summary/", "fields": ["material_id", "band_gap"], "limit": 5,
        "params": {"elements": ["Ba", "O"], "nelements_max": 3, "is_stable": True, "band_gap_min": 2},
    })
    assert mp_api["url"].startswith("https://api.materialsproject.org/materials/summary/")
    assert mp_api["params"]["elements"] == "Ba,O"
    assert mp_api["params"]["is_stable"] == "true"
    assert mp_api["params"]["_fields"] == "material_id,band_gap"
    assert mp_api["params"]["_limit"] == "5"
    assert mp_api["headers"]["x-api-key"] == "k" * 32
    assert text(out).startswith("300 matches; 5 returned.")
    assert len(payload(out)) == 5


async def test_query_caps_rows_and_characters(mcp, mp_api, monkeypatch):
    out = await call(mcp, "query", {"path": "/materials/summary/", "fields": ["material_id"], "limit": 10_000})
    assert mp_api["params"]["_limit"] == "500"
    monkeypatch.setattr("mp_mcp.server.MAX_CHARS", 500)
    from mp_mcp import server as srv

    small = srv.build_server(spec_url="bundled", mount_docs=False)
    out = await call(small, "query", {"path": "/materials/summary/", "fields": ["material_id"], "limit": 100})
    assert "Cut to" in text(out) and len(text(out)) < 800


async def test_hosted_server_never_uses_its_own_key(monkeypatch, mp_api):
    from mp_mcp import server as srv

    monkeypatch.setenv("MP_API_KEY", "server-key")
    monkeypatch.setenv("MP_MCP_HOSTED", "1")
    hosted = srv.build_server(spec_url="bundled", mount_docs=False)
    with pytest.raises(ToolError, match="X-API-KEY"):
        await call(hosted, "query", {"path": "/materials/summary/", "fields": ["material_id"]})
    assert "url" not in mp_api


async def test_get_object_summary_and_large_json(mcp, monkeypatch, tmp_path):
    from pymatgen.core import Lattice, Structure

    si = Structure(Lattice.cubic(5.47), ["Si"] * 8, [[0, 0, 0], [0.25, 0.25, 0.25], [0, 0.5, 0.5], [0.25, 0.75, 0.75],
                                                    [0.5, 0, 0.5], [0.75, 0.25, 0.75], [0.5, 0.5, 0], [0.75, 0.75, 0.25]])
    monkeypatch.setattr(objects, "call", lambda key, method, args: si)
    out = text(await call(mcp, "get_object", {"method": "get_structure_by_material_id", "args": {"material_id": "mp-149"}}))
    assert "Si, Fd-3m, 8 sites" in out
    small = text(await call(mcp, "get_object", {"method": "get_structure_by_material_id", "args": {}, "format": "json"}))
    assert json.loads(small)["@class"] == "Structure"
    monkeypatch.setattr(objects, "INLINE_LIMIT", 100)
    monkeypatch.setenv("MP_MCP_OUTPUT_DIR", str(tmp_path))
    big = text(await call(mcp, "get_object", {"method": "get_structure_by_material_id", "args": {}, "format": "json"}))
    assert "written to" in big and list(tmp_path.glob("*.json"))
    with pytest.raises(ToolError):
        await call(mcp, "get_object", {"method": "not_a_method"})
