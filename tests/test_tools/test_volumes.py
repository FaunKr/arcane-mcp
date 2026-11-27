"""Tests for volume tools."""
from __future__ import annotations

import json
from typing import Any

import pytest

from tests.conftest import call_tool, propose_and_confirm

BASE = "http://localhost:3552/api/agents/0"


@pytest.mark.asyncio
async def test_list_volumes(mcp: Any, httpx_mock: Any) -> None:
    """list_volumes returns volumes list."""
    httpx_mock.add_response(
        url=f"{BASE}/volumes",
        method="GET",
        json=[{"name": "data-vol", "driver": "local"}],
    )
    result = await call_tool(mcp, "list_volumes")
    assert result == [{"name": "data-vol", "driver": "local"}]


@pytest.mark.asyncio
async def test_create_volume(mcp: Any, httpx_mock: Any) -> None:
    """create_volume posts with name, driver, and a labels map."""
    httpx_mock.add_response(
        url=f"{BASE}/volumes",
        method="POST",
        json={"name": "my-vol", "driver": "local"},
    )
    result = await call_tool(mcp, "create_volume", name="my-vol", labels="tier=data,owner=ops")
    assert result["name"] == "my-vol"
    request = httpx_mock.get_request()
    assert request is not None
    assert json.loads(request.content) == {
        "name": "my-vol",
        "driver": "local",
        "labels": {"tier": "data", "owner": "ops"},
    }


@pytest.mark.asyncio
async def test_inspect_volume(mcp: Any, httpx_mock: Any) -> None:
    """inspect_volume returns volume details."""
    httpx_mock.add_response(
        url=f"{BASE}/volumes/my-vol",
        method="GET",
        json={"name": "my-vol", "mountpoint": "/data"},
    )
    result = await call_tool(mcp, "inspect_volume", name="my-vol")
    assert result["mountpoint"] == "/data"


@pytest.mark.asyncio
async def test_remove_volume_needs_confirm(mcp: Any, httpx_mock: Any) -> None:
    """remove_volume returns warning when not confirmed."""
    result = await call_tool(mcp, "remove_volume", name="my-vol")
    assert "warning" in result


@pytest.mark.asyncio
async def test_remove_volume_confirmed(mcp: Any, httpx_mock: Any) -> None:
    """remove_volume executes when confirmed, passing force as a query parameter."""
    httpx_mock.add_response(
        url=f"{BASE}/volumes/my-vol?force=false",
        method="DELETE",
        json={"message": "removed"},
    )
    result = await propose_and_confirm(mcp, "remove_volume", name="my-vol")
    assert result == {"message": "removed"}
    request = httpx_mock.get_request()
    assert request is not None
    assert request.url.params["force"] == "false"


@pytest.mark.asyncio
async def test_browse_volume_uses_workspace(mcp: Any, httpx_mock: Any) -> None:
    """browse_volume reads the v3 volume workspace listing."""
    httpx_mock.add_response(
        url=f"{BASE}/volumes/my-vol/workspace?path=/data",
        method="GET",
        json={"files": [{"name": "app.conf", "relativePath": "app.conf"}]},
    )
    result = await call_tool(mcp, "browse_volume", name="my-vol", path="/data")
    assert result["files"][0]["name"] == "app.conf"
    request = httpx_mock.get_request()
    assert request is not None
    assert request.url.params["path"] == "/data"


@pytest.mark.asyncio
async def test_read_volume_file_uses_workspace_file(mcp: Any, httpx_mock: Any) -> None:
    """read_volume_file reads the v3 workspace file with relativePath."""
    httpx_mock.add_response(
        url=f"{BASE}/volumes/my-vol/workspace/file?relativePath=etc/app.conf",
        method="GET",
        json={"path": "/etc/app.conf", "content": "key=value"},
    )
    result = await call_tool(mcp, "read_volume_file", name="my-vol", path="etc/app.conf")
    assert result["data"]["content"] == "key=value"
    assert result["classification"] == "credential_sensitive"
    request = httpx_mock.get_request()
    assert request is not None
    assert request.url.params["relativePath"] == "etc/app.conf"


@pytest.mark.asyncio
async def test_upload_to_volume_not_available(mcp: Any, httpx_mock: Any) -> None:
    """upload_to_volume refuses instead of posting to the removed browse endpoint."""
    result = await call_tool(mcp, "upload_to_volume", name="my-vol", path="app.conf", content="x")
    assert "error" in result
    assert "multipart" in result["reason"]
    assert "manifest" in result["reason"]
    assert "confirmation_token" not in result


@pytest.mark.asyncio
async def test_create_volume_directory_not_available(mcp: Any, httpx_mock: Any) -> None:
    """create_volume_directory refuses instead of posting to the removed mkdir endpoint."""
    result = await call_tool(mcp, "create_volume_directory", name="my-vol", path="logs")
    assert "error" in result
    assert result["v3_equivalent"]["method"] == "PATCH"


@pytest.mark.asyncio
async def test_restore_volume_backup_uses_action_query(mcp: Any, httpx_mock: Any) -> None:
    """restore_volume_backup posts to the backup id with ?action=restore."""
    httpx_mock.add_response(
        url=f"{BASE}/volumes/my-vol/backups/b1?action=restore",
        method="POST",
        json={"message": "restored"},
    )
    result = await propose_and_confirm(mcp, "restore_volume_backup", volume_name="my-vol", backup_id="b1")
    assert result == {"message": "restored"}
    request = httpx_mock.get_request()
    assert request is not None
    assert request.url.params["action"] == "restore"


@pytest.mark.asyncio
async def test_delete_volume_backup_confirmed(mcp: Any, httpx_mock: Any) -> None:
    """delete_volume_backup deletes by backup id under the volumes collection."""
    httpx_mock.add_response(
        url=f"{BASE}/volumes/backups/b1",
        method="DELETE",
        json={"message": "deleted"},
    )
    result = await propose_and_confirm(mcp, "delete_volume_backup", backup_id="b1")
    assert result == {"message": "deleted"}
