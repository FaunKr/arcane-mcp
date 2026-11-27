"""Tests for environment tools (Arcane v3: environments are agents)."""
from __future__ import annotations

import json
from typing import Any

import pytest

from tests.conftest import call_tool, propose_and_confirm


@pytest.mark.asyncio
async def test_list_environments(mcp: Any, httpx_mock: Any) -> None:
    """list_environments returns environments list from the v3 agent collection."""
    httpx_mock.add_response(
        url="http://localhost:3552/api/agents",
        method="GET",
        json=[{"id": "0", "name": "local"}, {"id": "uuid-1", "name": "remote"}],
    )
    result = await call_tool(mcp, "list_environments")
    assert len(result) == 2


@pytest.mark.asyncio
async def test_get_environment(mcp: Any, httpx_mock: Any) -> None:
    """get_environment returns a single environment."""
    httpx_mock.add_response(
        url="http://localhost:3552/api/agents/0",
        method="GET",
        json={"id": "0", "name": "local"},
    )
    result = await call_tool(mcp, "get_environment", env_id="0")
    assert result["data"]["id"] == "0"


@pytest.mark.asyncio
async def test_create_environment(mcp: Any, httpx_mock: Any) -> None:
    """create_environment registers a remote agent.

    v3 creates the agent record only: api_url and agent_token are not part of
    the request body (agents enroll themselves and carry their own token).
    """
    httpx_mock.add_response(
        url="http://localhost:3552/api/agents",
        method="POST",
        json={"name": "staging"},
    )
    result = await call_tool(
        mcp,
        "create_environment",
        name="staging",
        api_url="http://remote:3552",
        agent_token="tok_abc",
    )
    assert result["name"] == "staging"
    assert "enroll" in result["warning"]

    (request,) = httpx_mock.get_requests()
    assert request.method == "POST"
    assert request.url.path == "/api/agents"
    assert json.loads(request.content) == {"name": "staging"}


@pytest.mark.asyncio
async def test_update_environment_needs_confirm(mcp: Any) -> None:
    """update_environment returns a confirmation token instead of executing."""
    result = await call_tool(mcp, "update_environment", env_id="0", name="renamed")
    assert "confirmation_token" in result
    assert result["changes"] == {"name": "renamed"}


@pytest.mark.asyncio
async def test_update_environment_confirmed(mcp: Any, httpx_mock: Any) -> None:
    """update_environment executes as PATCH on the v3 agent resource."""
    httpx_mock.add_response(
        url="http://localhost:3552/api/agents/0",
        method="PATCH",
        json={"message": "updated"},
    )
    result = await propose_and_confirm(mcp, "update_environment", env_id="0", name="renamed")
    assert result == {"message": "updated"}

    (request,) = httpx_mock.get_requests()
    assert request.method == "PATCH"
    assert request.url.path == "/api/agents/0"
    assert json.loads(request.content) == {"name": "renamed"}


@pytest.mark.asyncio
async def test_update_environment_rejects_agent_token(mcp: Any, httpx_mock: Any) -> None:
    """v3 cannot rotate an agent access token; the tool says so instead of ignoring it."""
    result = await call_tool(
        mcp, "update_environment", env_id="0", agent_token="tok_abc"
    )
    assert "not available in Arcane v3" in result["error"]
    assert "confirmation_token" not in result
    assert httpx_mock.get_requests() == []


@pytest.mark.asyncio
async def test_remove_environment_needs_confirm(mcp: Any, httpx_mock: Any) -> None:
    """remove_environment returns warning when not confirmed."""
    result = await call_tool(mcp, "remove_environment", env_id="0")
    assert "warning" in result


@pytest.mark.asyncio
async def test_remove_environment_confirmed(mcp: Any, httpx_mock: Any) -> None:
    """remove_environment executes when confirmed."""
    httpx_mock.add_response(
        url="http://localhost:3552/api/agents/0",
        method="DELETE",
        json={"message": "removed"},
    )
    result = await propose_and_confirm(mcp, "remove_environment", env_id="0")
    assert result == {"message": "removed"}

    (request,) = httpx_mock.get_requests()
    assert request.method == "DELETE"
    assert request.url.path == "/api/agents/0"
