"""The Materials Project REST API, read from its own OpenAPI spec.

Nothing about an endpoint is written down here: names, parameters, descriptions and
returned fields all come from the spec the API serves, so a new endpoint or field
appears as soon as the server restarts.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from importlib import resources
from typing import Any

import httpx

log = logging.getLogger(__name__)

API_ROOT = os.environ.get("MP_API_ENDPOINT", "https://api.materialsproject.org").rstrip("/")
METHODS = ("get", "post", "put", "patch", "delete")


@dataclass
class Endpoint:
    path: str
    method: str
    summary: str
    params: list[dict[str, Any]]
    body: dict[str, Any] | None
    fields: dict[str, dict[str, Any]]

    def has_param(self, name: str) -> bool:
        return any(p["name"] == name for p in self.params)


def _snapshot() -> dict[str, Any]:
    return json.loads(resources.files("mp_mcp").joinpath("openapi_snapshot.json").read_text())


def load_spec(url: str | None = None, timeout: float = 15.0) -> tuple[dict[str, Any], str]:
    """Fetch the live spec; fall back to the snapshot shipped with the package."""
    url = url or os.environ.get("MP_MCP_SPEC_URL") or f"{API_ROOT}/openapi.json"
    if url == "bundled":
        return _snapshot(), "bundled snapshot"
    try:
        r = httpx.get(url, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict) or not data.get("paths"):
            raise ValueError("not an OpenAPI document")
        return data, url
    except Exception as exc:  # network down, API down: still start
        log.warning("Could not fetch %s (%s); using the bundled snapshot", url, exc)
        return _snapshot(), "bundled snapshot"


def _type(schema: dict[str, Any]) -> str:
    if "anyOf" in schema:
        return " | ".join(_type(s) for s in schema["anyOf"] if s.get("type") != "null") or "any"
    if "enum" in schema:
        return "one of " + ", ".join(map(str, schema["enum"]))
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if schema.get("type") == "array":
        return f"list of {_type(schema.get('items', {}))}"
    return schema.get("type", "any")


def _doc_fields(spec: dict[str, Any], op: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The fields of the document an endpoint returns, from its 200 response schema.
    Empty when the spec does not describe the response (a few endpoints), in which case
    the endpoint returns whole documents and no projection is possible."""
    schemas = spec.get("components", {}).get("schemas", {})
    try:
        ref = op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        resp = schemas[ref.rsplit("/", 1)[-1]]
        data = resp["properties"]["data"]
        items = next(s["items"] for s in data.get("anyOf", [data]) if s.get("type") == "array")
        doc = schemas[items["$ref"].rsplit("/", 1)[-1]]
    except (KeyError, StopIteration, TypeError):
        return {}
    return {
        name: {"type": _type(s), "description": (s.get("description") or s.get("title") or "").strip()}
        for name, s in doc.get("properties", {}).items()
    }


def endpoints(spec: dict[str, Any]) -> dict[str, Endpoint]:
    out: dict[str, Endpoint] = {}
    for path, ops in spec.get("paths", {}).items():
        shared = [p for p in ops.get("parameters", []) if isinstance(p, dict)]  # path-level parameters
        for method, op in ops.items():
            if method not in METHODS or not isinstance(op, dict):
                continue
            params = [
                {
                    "name": p["name"],
                    "type": _type(p.get("schema", {})),
                    "description": (p.get("description") or "").strip(),
                    "default": p.get("schema", {}).get("default"),
                }
                for p in shared + op.get("parameters", [])
                if p.get("in") == "query"
            ]
            body = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
            out[path] = Endpoint(path, method.upper(), op.get("summary") or "", params, body, _doc_fields(spec, op))
    return out


def normalize(path: str) -> str:
    return "/" + path.strip().strip("/") + "/"
