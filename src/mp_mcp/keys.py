"""Whose MP API key a request runs under.

Hosted (MP_MCP_HOSTED=1): only the caller's own X-API-KEY header, never the server's
environment, so one user can never borrow another's key or the operator's.
Local: the caller's header if there is one, else MP_API_KEY, else pymatgen's PMG_MAPI_KEY.
"""
from __future__ import annotations

import os

from fastmcp.server.dependencies import get_http_headers


class MissingKey(Exception):
    pass


def hosted() -> bool:
    return os.environ.get("MP_MCP_HOSTED", "").lower() in ("1", "true", "yes")


def api_key() -> str:
    headers = {k.lower(): v for k, v in get_http_headers(include={"x-api-key"}).items()}
    if key := headers.get("x-api-key", "").strip():
        return key
    if hosted():
        raise MissingKey(
            "This server needs your Materials Project API key in an X-API-KEY header. "
            "Get one at https://next-gen.materialsproject.org/api and add it to your MCP client's config."
        )
    if key := os.environ.get("MP_API_KEY", "").strip():
        return key
    try:
        from pymatgen.core import SETTINGS

        if key := (SETTINGS.get("PMG_MAPI_KEY") or "").strip():
            return key
    except Exception:
        pass
    raise MissingKey(
        "No Materials Project API key found. Set MP_API_KEY, or PMG_MAPI_KEY in ~/.config/.pmgrc.yaml. "
        "Get a key at https://next-gen.materialsproject.org/api"
    )
