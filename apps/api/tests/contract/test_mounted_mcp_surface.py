"""The tools a real client sees, asked of the mounted application.

Its sibling `test_access_mcp_tools.py` checks the registrar: it builds a
server of its own, calls the registration function, and reads the tools
back. That is the right subject for it, and its docstring says plainly
that the mount is "a single line in `create_app` and a separate
concern". The separate concern had no owner. Deleting
`register_access_tools(...)` from `create_app` survived the whole
contract and architecture suite, and the application would have served
an empty tool list to every MCP client while 575 tests passed.

So this file asks the mounted app, over the wire, the way a client
would: initialize, notify, then `tools/list`. Nothing is imported from
the Access package, deliberately. Pulling the expected names in from
`register_access_tools` would build both sides of the comparison from
the registrar and agree with it however wrong the mount was. The names
are spelled out here instead.

Slow by this tier's standards, because a full application boots for it.
One test, because the one fact worth this cost is that the tools reach
the surface at all.
"""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aroc.api.main import create_app
from aroc.infrastructure.settings import Settings

pytestmark = pytest.mark.contract

TOOLS_A_CLIENT_SHOULD_SEE = frozenset(
    {"register_actor", "deactivate_actor", "reactivate_actor", "get_actor"}
)
"""Spelled out rather than imported, so this side is independent.

A second bounded context publishing tools adds them here, in the commit
that mounts it.
"""

_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _result(response_text: str) -> dict[str, Any]:
    """The JSON-RPC result carried in a server-sent-events response body."""
    for line in response_text.splitlines():
        if line.startswith("data: "):
            payload: dict[str, Any] = json.loads(line.removeprefix("data: "))
            return payload.get("result", {})
    pytest.fail(f"no SSE data frame in the response:\n{response_text[:400]}")


def test_the_mounted_mcp_endpoint_publishes_every_tool_a_client_needs() -> None:
    with TestClient(create_app(settings=Settings(app_env="test"))) as client:
        opened = client.post(
            "/mcp/",
            headers=_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "contract-test", "version": "0"},
                },
            },
        )
        assert opened.status_code == 200, f"the MCP endpoint refused to open: {opened.text[:200]}"
        session = opened.headers.get("mcp-session-id")
        assert session, "the server opened no session, so the mount is not a live MCP endpoint"

        live = {**_HEADERS, "mcp-session-id": session}
        client.post(
            "/mcp/", headers=live, json={"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        listed = client.post(
            "/mcp/", headers=live, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
        assert listed.status_code == 200

    published = frozenset(tool["name"] for tool in _result(listed.text)["tools"])
    assert published == TOOLS_A_CLIENT_SHOULD_SEE, (
        "The mounted MCP surface is not what a client should see.\n"
        f"  Missing:   {sorted(TOOLS_A_CLIENT_SHOULD_SEE - published)}\n"
        f"  Unexpected: {sorted(published - TOOLS_A_CLIENT_SHOULD_SEE)}\n"
        "A tool registered on a server that is never mounted, or mounted on a "
        "server the app does not serve, looks correct everywhere except here."
    )
