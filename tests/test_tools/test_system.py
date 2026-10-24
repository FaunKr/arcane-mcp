"""Tests for system tools."""
from __future__ import annotations

import json
from typing import Any

import pytest

from tests.conftest import call_tool, propose_and_confirm


@pytest.mark.asyncio
async def test_get_docker_info(mcp: Any, httpx_mock: Any) -> None:
    """get_docker_info returns system info."""
    httpx_mock.add_response(
        url="http://localhost:3552/api/environments/0/system/docker/info",
        method="GET",
        json={"containers": 5, "images": 10},
    )
    result = await call_tool(mcp, "get_docker_info")
    assert result["containers"] == 5


@pytest.mark.asyncio
async def test_get_docker_version(mcp: Any, httpx_mock: Any) -> None:
    """get_docker_version returns version info."""
    httpx_mock.add_response(
        url="http://localhost:3552/api/environments/0/version",
        method="GET",
        json={"version": "24.0.7"},
    )
    result = await call_tool(mcp, "get_docker_version")
    assert result["version"] == "24.0.7"


@pytest.mark.asyncio
async def test_prune_system_needs_confirm(mcp: Any, httpx_mock: Any) -> None:
    """prune_system returns warning when not confirmed."""
    result = await call_tool(mcp, "prune_system")
    assert "warning" in result


@pytest.mark.asyncio
async def test_prune_system_confirmed(mcp: Any, httpx_mock: Any) -> None:
    """prune_system executes when confirmed."""
    httpx_mock.add_response(
        url="http://localhost:3552/api/environments/0/system/prune",
        method="POST",
        json={"reclaimed": "100MB"},
    )
    result = await propose_and_confirm(mcp, "prune_system", dry_run=False)
    assert result == {"reclaimed": "100MB"}


@pytest.mark.asyncio
async def test_prune_system_with_volumes(mcp: Any, httpx_mock: Any) -> None:
    """prune_system sends volumes flag."""
    httpx_mock.add_response(
        url="http://localhost:3552/api/environments/0/system/prune",
        method="POST",
        json={"reclaimed": "200MB"},
    )
    result = await propose_and_confirm(mcp, "prune_system", dry_run=False, volumes=True)
    assert result == {"reclaimed": "200MB"}
    assert json.loads(httpx_mock.get_requests()[0].content)["volumes"] is True
