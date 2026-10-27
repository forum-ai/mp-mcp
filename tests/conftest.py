import json
import warnings

import httpx
import pytest
from fastmcp import Client

from mp_mcp import server as srv

warnings.filterwarnings("ignore")


@pytest.fixture
def mcp(monkeypatch):
    monkeypatch.setenv("MP_API_KEY", "k" * 32)
    monkeypatch.delenv("MP_MCP_HOSTED", raising=False)
    return srv.build_server(spec_url="bundled", mount_docs=False)


@pytest.fixture
def mp_api(monkeypatch):
    """Record what query sends to the MP API and answer with canned rows."""
    seen = {}
    rows = [{"material_id": f"mp-{i}", "band_gap": 2.0 + i / 100} for i in range(300)]

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["params"] = dict(request.url.params)
        seen["headers"] = dict(request.headers)
        limit = int(request.url.params.get("_limit", 100))
        return httpx.Response(200, json={"data": rows[:limit], "meta": {"total_doc": len(rows)}})

    real = httpx.AsyncClient
    monkeypatch.setattr(srv.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return seen


async def call(mcp, tool, args):
    async with Client(mcp) as c:
        r = await c.call_tool(tool, args)
        return r.content


def text(content):
    return "\n".join(getattr(b, "text", "") for b in content)


def payload(content):
    body = text(content).split("\n", 1)[1]
    return json.loads(body)
