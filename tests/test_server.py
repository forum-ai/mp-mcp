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


async def test_query_omits_fields_and_sort_safely(mcp, mp_api):
    out = await call(mcp, "query", {"path": "/materials/synthesis/", "params": {"target_formula": "LiFePO4", "skip_me": None}})
    assert "_fields" not in mp_api["params"] and "skip_me" not in mp_api["params"]
    assert "returned" in text(out)
    with pytest.raises(ToolError, match="does not support sorting"):
        await call(mcp, "query", {"path": "/materials/elasticity/", "fields": ["k_vrh"], "sort": "-k_vrh"})
    desc = text(await call(mcp, "describe_endpoint", {"path": "/materials/synthesis/"}))
    assert "not described in MP's spec" in desc
    desc = text(await call(mcp, "describe_endpoint", {"path": "/materials/summary/", "search": "gap"}))
    assert "Sorting: pass sort" in desc


async def test_query_survives_bad_upstream_payloads(mcp, monkeypatch):
    import httpx
    from mp_mcp import server as srv

    answers = iter([httpx.Response(200, text="<html>down</html>"), httpx.Response(200, json=[{"x": 1}]),
                    httpx.Response(200, json={"data": [{"blob": "x" * 60_000}], "meta": {"total_doc": 1}})])
    real = httpx.AsyncClient
    monkeypatch.setattr(srv.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(lambda req: next(answers)), **kw))
    with pytest.raises(ToolError, match="not JSON"):
        await call(mcp, "query", {"path": "/materials/summary/", "fields": ["material_id"]})
    assert payload(await call(mcp, "query", {"path": "/materials/summary/", "fields": ["x"]})) == [{"x": 1}]
    out = text(await call(mcp, "query", {"path": "/materials/summary/", "fields": ["blob"]}))
    assert "truncated" in out and len(out) < srv.MAX_CHARS + 500


async def test_get_object_cif_and_size_guards(mcp, monkeypatch, tmp_path):
    from pymatgen.core import Lattice, Structure

    si = Structure(Lattice.cubic(5.47), ["Si"] * 2, [[0, 0, 0], [0.25, 0.25, 0.25]])
    monkeypatch.setattr(objects, "call", lambda key, method, args: si)
    cif = text(await call(mcp, "get_object", {"method": "get_structure_by_material_id", "args": {"material_id": "mp-149"}, "format": "cif"}))
    assert "_cell_length_a" in cif and "Si" in cif
    poscar = text(await call(mcp, "get_object", {"method": "get_structure_by_material_id", "format": "poscar"}))
    assert "Direct" in poscar or "direct" in poscar
    monkeypatch.setattr(objects, "call", lambda key, method, args: {"not": "a structure"})
    with pytest.raises(ToolError, match="only for structures"):
        await call(mcp, "get_object", {"method": "get_structure_by_material_id", "format": "cif"})
    monkeypatch.setattr(objects, "call", lambda key, method, args: si)
    monkeypatch.setattr(objects, "MAX_OBJECT_BYTES", 100)
    with pytest.raises(ToolError, match="at most 100"):
        await call(mcp, "get_object", {"method": "get_structure_by_material_id", "format": "json"})


async def test_get_object_times_out(mcp, monkeypatch):
    import time
    from mp_mcp import server as srv

    monkeypatch.setattr(srv, "TIMEOUT", 0.2)
    monkeypatch.setattr(objects, "call", lambda key, method, args: time.sleep(2))
    slow = srv.build_server(spec_url="bundled", mount_docs=False)
    with pytest.raises(ToolError, match="longer than"):
        await call(slow, "get_object", {"method": "get_structure_by_material_id", "args": {"material_id": "mp-149"}})


async def test_query_asks_for_legacy_ids_where_offered(mcp, mp_api):
    await call(mcp, "query", {"path": "/materials/summary/", "fields": ["material_id"]})
    assert mp_api["params"]["id_format"] == "legacy"
    await call(mcp, "query", {"path": "/materials/summary/", "fields": ["material_id"], "params": {"id_format": "alpha"}})
    assert mp_api["params"]["id_format"] == "alpha"
    await call(mcp, "query", {"path": "/materials/synthesis/"})
    assert "id_format" not in mp_api["params"]


def test_landing_page_tells_a_person_how_to_connect(mcp):
    from starlette.testclient import TestClient

    with TestClient(mcp.http_app()) as c:
        r = c.get("/")
    assert r.status_code == 200 and "/plugin install" in r.text and "/mcp" in r.text and "X-API-KEY" in r.text
