"""Tests for Compose project tools."""
from __future__ import annotations

import json
from typing import Any

import pytest

from tests.conftest import call_tool, propose_and_confirm

BASE = "http://localhost:3552/api/agents/0"


@pytest.mark.asyncio
async def test_list_projects(mcp: Any, httpx_mock: Any) -> None:
    """list_projects returns projects list."""
    httpx_mock.add_response(
        url=f"{BASE}/projects",
        method="GET",
        json=[{"id": "p1", "name": "myapp"}],
    )
    result = await call_tool(mcp, "list_projects")
    assert result == [{"id": "p1", "name": "myapp"}]


@pytest.mark.asyncio
async def test_get_project(mcp: Any, httpx_mock: Any) -> None:
    """get_project returns project details."""
    httpx_mock.add_response(
        url=f"{BASE}/projects/p1",
        method="GET",
        json={"id": "p1", "name": "myapp"},
    )
    result = await call_tool(mcp, "get_project", project_id="p1")
    assert result["id"] == "p1"


@pytest.mark.asyncio
async def test_deploy_project_not_available(mcp: Any, httpx_mock: Any) -> None:
    """deploy_project explains the v3 multipart contract instead of sending JSON."""
    result = await call_tool(
        mcp, "deploy_project", compose_content="version: '3'", project_name="myapp",
    )
    assert "error" in result
    assert "multipart/form-data" in result["reason"]
    assert "manifest" in result["v3_contract"]["fields"]
    assert result["v3_contract"]["endpoint"] == "/api/agents/0/projects"
    assert result["plan"]["services"] == []
    assert "confirmation_token" not in result


@pytest.mark.asyncio
async def test_redeploy_project(mcp: Any, httpx_mock: Any) -> None:
    """redeploy_project posts to the consolidated deploy endpoint with action=redeploy."""
    httpx_mock.add_response(
        url=f"{BASE}/projects/p1/deploy?action=redeploy",
        method="POST",
        json={"message": "redeployed"},
    )
    result = await call_tool(mcp, "redeploy_project", project_id="p1")
    assert result == {"message": "redeployed"}
    request = httpx_mock.get_request()
    assert request is not None
    assert request.url.params["action"] == "redeploy"


@pytest.mark.asyncio
async def test_remove_project_needs_confirm(mcp: Any, httpx_mock: Any) -> None:
    """remove_project returns warning when not confirmed."""
    result = await call_tool(mcp, "remove_project", project_id="p1")
    assert "warning" in result


@pytest.mark.asyncio
async def test_remove_project_confirmed(mcp: Any, httpx_mock: Any) -> None:
    """remove_project executes when confirmed."""
    httpx_mock.add_response(
        url=f"{BASE}/projects/p1",
        method="DELETE",
        json={"message": "removed"},
    )
    result = await propose_and_confirm(mcp, "remove_project", project_id="p1")
    assert result == {"message": "removed"}


@pytest.mark.asyncio
async def test_update_project(mcp: Any, httpx_mock: Any) -> None:
    """update_project patches with the v3 field name composeContent."""
    httpx_mock.add_response(
        url=f"{BASE}/projects/p1",
        method="PATCH",
        json={"id": "p1", "name": "renamed"},
    )
    result = await propose_and_confirm(
        mcp, "update_project", project_id="p1", project_name="renamed",
        compose_content="services:\n  web:\n    image: nginx:latest\n",
    )
    assert result["name"] == "renamed"
    request = httpx_mock.get_request()
    assert request is not None
    body = json.loads(request.content)
    assert body["name"] == "renamed"
    assert body["composeContent"].startswith("services:")
    assert "compose" not in body


@pytest.mark.asyncio
async def test_update_project_empty_payload(mcp: Any, httpx_mock: Any) -> None:
    """update_project returns warning with no update fields."""
    result = await call_tool(mcp, "update_project", project_id="p1")
    assert "warning" in result


@pytest.mark.asyncio
async def test_project_down_uses_action_query(mcp: Any, httpx_mock: Any) -> None:
    """project_down posts ?action=down to the project."""
    httpx_mock.add_response(
        url=f"{BASE}/projects/p1?action=down",
        method="POST",
        json={"message": "down"},
    )
    result = await propose_and_confirm(mcp, "project_down", project_id="p1")
    assert result == {"message": "down"}
    request = httpx_mock.get_request()
    assert request is not None
    assert request.url.params["action"] == "down"


@pytest.mark.asyncio
async def test_get_project_file_not_available(mcp: Any, httpx_mock: Any) -> None:
    """get_project_file points at the v3 workspace equivalents."""
    result = await call_tool(mcp, "get_project_file", project_id="p1")
    assert "error" in result
    assert result["v3_equivalents"]["compose"] == "/api/agents/0/projects/p1/compose"
