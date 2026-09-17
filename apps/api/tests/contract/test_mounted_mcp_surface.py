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
would: initialize, notify, then `tools/list`. The expected names are
spelled out here rather than imported. Pulling them from
`register_access_tools` would build both sides of the comparison from
the registrar and agree with it however wrong the mount was.

That rule is about the EXPECTED side of a comparison, not about imports
in general. The second test imports `GOVERNING_COMMAND_NAMES` to build a
policy the domain will accept, which is an input rather than an answer,
and spelling that out would make this file fail confusingly the day the
set grows.

Slow by this tier's standards, because a full application boots for it,
so each test here earns its place separately.

The second one calls tools rather than listing them. Listing proves the
mount; it says nothing about the bodies, and a tool body is a second
copy of what a route does: build the input, call the handler, shape the
answer. Nothing else in this repository executes one, so a tool that
dropped a field, read the wrong argument or returned an unordered set
would be invisible on the surface this project pairs with HTTP as an
equal. One walk covers writing and reading; the other tools are still
uncovered, and the shape below is what covering them would look like.
"""

import json
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from aroc.api.main import create_app
from aroc.authority.aggregates.policy import GOVERNING_COMMAND_NAMES
from aroc.infrastructure.settings import Settings

pytestmark = pytest.mark.contract

TOOLS_A_CLIENT_SHOULD_SEE = frozenset(
    {
        "register_actor",
        "deactivate_actor",
        "reactivate_actor",
        "get_actor",
        "define_policy",
        "grant_permission",
        "revoke_permission",
        "get_policy",
    }
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


def _open_session(client: TestClient) -> dict[str, str]:
    """Initialize an MCP session and return the headers that keep it."""
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
    return live


def _call(client: TestClient, live: dict[str, str], name: str, **arguments: Any) -> dict[str, Any]:
    """Invoke one tool and return its structured result."""
    response = client.post(
        "/mcp/",
        headers=live,
        json={
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert response.status_code == 200, response.text[:300]
    result = _result(response.text)
    assert not result.get("isError"), f"{name} failed: {result}"
    structured: dict[str, Any] = result["structuredContent"]
    return structured


def test_a_client_can_write_and_read_a_policy_over_the_mcp_surface() -> None:
    """Three tool bodies executed, not just published.

    The read is what the ordering assertion is for. A set has no order,
    so the tool imposes one, and it imposes it in its own code rather
    than sharing the route's. Eight pairs, because a handful can come
    out of a set in sorted order by luck.
    """
    administrator = str(uuid4())
    governing = [
        {"principal_id": administrator, "command_name": name}
        for name in sorted(GOVERNING_COMMAND_NAMES)
    ]

    with TestClient(create_app(settings=Settings(app_env="test"))) as client:
        live = _open_session(client)
        defined = _call(client, live, "define_policy", permissions=governing)
        policy_id = defined["policy_id"]
        for _ in range(8):
            _call(
                client,
                live,
                "grant_permission",
                policy_id=policy_id,
                principal_id=str(uuid4()),
                command_name="RegisterActor",
            )
        read = _call(client, live, "get_policy", policy_id=policy_id)

    assert read["policy_id"] == policy_id
    keys = [(p["principal_id"], p["command_name"]) for p in read["permissions"]]
    assert keys == sorted(keys), "a set has no order, so the tool must impose one"
    assert len(keys) == len(governing) + 8
