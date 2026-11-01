"""Tests for container tools."""
from __future__ import annotations

import json
from typing import Any

import pytest

from tests.conftest import call_tool, propose_and_confirm

# ── list_containers ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_containers(mcp: Any, httpx_mock: Any) -> None:
    """List containers returns parsed JSON."""
    httpx_mock.add_response(
        url="http://localhost:3552/api/environments/0/containers?all=false",
        method="GET",
        json=[{"id": "c1", "name": "web", "status": "running"}],
    )
    result = await call_tool(mcp, "list_containers")
    assert result == [{"id": "c1", "name": "web", "status": "running"}]


@pytest.mark.asyncio
async def test_list_containers_all(mcp: Any, httpx_mock: Any) -> None:
    """list_containers passes the all flag."""
    httpx_mock.add_response(
        url="http://localhost:3552/api/environments/0/containers?all=true",
        method="GET",
        json=[],
    )
    result = await call_tool(mcp, "list_containers", all=True)
    assert result == []


@pytest.mark.asyncio
async def test_list_containers_http_error(mcp: Any, httpx_mock: Any) -> None:
    """list_containers returns error dict on HTTP error."""
    httpx_mock.add_response(status_code=500)
    result = await call_tool(mcp, "list_containers")
    assert "error" in result
    assert result["status_code"] == 500


# ── inspect_container ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_inspect_container(mcp: Any, httpx_mock: Any) -> None:
    """inspect_container returns container details."""
    httpx_mock.add_response(
        url="http://localhost:3552/api/environments/0/containers/c1",
        method="GET",
        json={"id": "c1", "name": "web", "config": {}},
    )
    result = await call_tool(mcp, "inspect_container", container_id="c1")
    assert result["data"]["id"] == "c1"


# ── start / stop / restart ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_container(mcp: Any, httpx_mock: Any) -> None:
    """start_container posts to the start endpoint."""
    httpx_mock.add_response(
        url="http://localhost:3552/api/environments/0/containers/c1/start",
        method="POST",
        json={"message": "started"},
    )
    result = await call_tool(mcp, "start_container", container_id="c1")
    assert result == {"message": "started"}


@pytest.mark.asyncio
async def test_stop_container(mcp: Any, httpx_mock: Any) -> None:
    """stop_container posts with timeout."""
    httpx_mock.add_response(
        url="http://localhost:3552/api/environments/0/containers/c1/stop",
        method="POST",
        json={"message": "stopped"},
    )
    result = await call_tool(mcp, "stop_container", container_id="c1", timeout=30)
    assert result == {"message": "stopped"}


@pytest.mark.asyncio
async def test_restart_container(mcp: Any, httpx_mock: Any) -> None:
    """restart_container posts with timeout."""
    httpx_mock.add_response(
        url="http://localhost:3552/api/environments/0/containers/c1/restart",
        method="POST",
        json={"message": "restarted"},
    )
    result = await call_tool(mcp, "restart_container", container_id="c1")
    assert result == {"message": "restarted"}


# ── remove_container ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_remove_container_needs_confirm(mcp: Any, httpx_mock: Any) -> None:
    """remove_container returns a confirmation token instead of executing."""
    result = await call_tool(mcp, "remove_container", container_id="c1")
    assert "warning" in result
    assert "confirmation_token" in result
    assert result["target"] == "c1"


@pytest.mark.asyncio
async def test_remove_container_confirmed(mcp: Any, httpx_mock: Any) -> None:
    """remove_container executes once confirmed."""
    httpx_mock.add_response(
        url="http://localhost:3552/api/environments/0/containers/c1?force=false",
        method="DELETE",
        json={"message": "removed"},
    )
    result = await propose_and_confirm(mcp, "remove_container", container_id="c1")
    assert result == {"message": "removed"}


# ── create_container ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_container(mcp: Any, httpx_mock: Any) -> None:
    """create_container posts with image and name."""
    httpx_mock.add_response(
        url="http://localhost:3552/api/environments/0/containers",
        method="POST",
        json={"id": "new-container"},
    )
    result = await call_tool(mcp, "create_container", image="nginx", name="my-nginx")
    assert result == {"id": "new-container"}


# ── exec_in_container ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exec_in_container(mcp: Any, httpx_mock: Any) -> None:
    """exec_in_container sends command payload."""
    httpx_mock.add_response(
        url="http://localhost:3552/api/environments/0/containers/c1/exec",
        method="POST",
        json={"output": "hello world"},
    )
    result = await call_tool(mcp, "exec_in_container", container_id="c1", command="echo hello")
    assert result == {"output": "hello world"}


# ── get_container_logs ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_container_logs(mcp: Any, httpx_mock: Any) -> None:
    """get_container_logs uses the logs/download endpoint and returns raw text."""
    httpx_mock.add_response(
        url="http://localhost:3552/api/environments/0/containers/c1/logs/download?tail=100",
        method="GET",
        text="line1\nline2",
    )
    result = await call_tool(mcp, "get_container_logs", container_id="c1")
    assert result == {"container_id": "c1", "tail": 100, "logs": "line1\nline2"}


# ── run_command (exec substitute) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_run_command_preview_needs_confirm(mcp: Any, httpx_mock: Any) -> None:
    """run_command returns a plan and performs no HTTP call until confirmed."""
    result = await call_tool(mcp, "run_command", command="rm -rf /tmp/x", container="c1")
    assert result["action"] == "run_command"
    assert "confirm=True" in result["warning"]
    assert result["plan"]["command"] == "rm -rf /tmp/x"
    assert result["plan"]["image"] == "(inherited from c1)"
    assert httpx_mock.get_requests() == []


@pytest.mark.asyncio
async def test_run_command_requires_context(mcp: Any, httpx_mock: Any) -> None:
    """Neither image nor container given -> clear error, no HTTP call."""
    result = await call_tool(mcp, "run_command", command="true", confirm=True)
    assert "image" in result["error"] and "container" in result["error"]
    assert httpx_mock.get_requests() == []


@pytest.mark.asyncio
async def test_run_command_inherits_image_binds_and_network(mcp: Any, httpx_mock: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """run_command borrows image/mounts/network from the target container and cleans up."""
    base = "http://localhost:3552/api/environments/0/containers"
    httpx_mock.add_response(
        url=f"{base}/caddy-caddy-1",
        method="GET",
        json={
            "data": {
                "id": "caddy-caddy-1",
                "image": "caddy:2.11",
                "networkSettings": {"networks": {"proxy": {"aliases": ["caddy"]}}},
                "mounts": [
                    {"type": "bind", "source": "/opt/caddy/config/etc", "destination": "/etc/caddy", "rw": True},
                    {"type": "bind", "source": "/opt/caddy/ro", "destination": "/ro", "rw": False},
                    {"type": "volume", "name": "caddy_data", "destination": "/data", "rw": True},
                ],
            },
        },
    )
    httpx_mock.add_response(url=base, method="POST", json={"data": {"id": "exec1"}})
    httpx_mock.add_response(url=f"{base}/exec1/start", method="POST", json={"ok": True})
    httpx_mock.add_response(
        url=f"{base}/exec1",
        method="GET",
        json={"data": {"state": {"running": False, "exitCode": 0}}},
    )
    httpx_mock.add_response(url=f"{base}/exec1/logs/download?tail=5000", method="GET", text="Valid configuration\n")
    httpx_mock.add_response(url=f"{base}/exec1?force=true", method="DELETE", json={"ok": True})

    result = await call_tool(
        mcp, "run_command", command="caddy validate --config /etc/caddy/caddy.json", container="caddy-caddy-1", confirm=True,
    )

    assert result["exit_code"] == 0
    assert result["timed_out"] is False
    assert result["output"] == "Valid configuration\n"
    assert result["image"] == "caddy:2.11"
    assert result["network"] == "proxy"
    assert result["binds"] == ["/opt/caddy/config/etc:/etc/caddy", "/opt/caddy/ro:/ro:ro", "caddy_data:/data"]

    requests = httpx_mock.get_requests()
    create_body = json.loads([r for r in requests if r.method == "POST" and str(r.url).endswith("/containers")][0].content)
    assert create_body["image"] == "caddy:2.11"
    assert create_body["entrypoint"] == ["/bin/sh", "-c"]
    assert create_body["cmd"] == ["caddy validate --config /etc/caddy/caddy.json"]
    assert create_body["networks"] == ["proxy"]
    assert create_body["hostConfig"]["binds"][0] == "/opt/caddy/config/etc:/etc/caddy"
    # throwaway container is always removed
    assert any(r.method == "DELETE" for r in requests)


# ── get_container_stats ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_container_stats(mcp: Any, httpx_mock: Any) -> None:
    """get_container_stats fetches resource stats."""
    httpx_mock.add_response(
        url="http://localhost:3552/api/environments/0/containers/c1/stats",
        method="GET",
        json={"cpu": 0.5, "memory": 1048576},
    )
    result = await call_tool(mcp, "get_container_stats", container_id="c1")
    assert result["cpu"] == 0.5


# ── run_command output cleanup ─────────────────────────────────────────


def test_clean_command_output_strips_timestamps() -> None:
    from arcane_mcp.tools.containers import _clean_command_output

    raw = "2026-11-01T13:31:29.166283843Z A\n2026-11-01T13:31:29.167Z B\n"
    assert _clean_command_output(raw) == "A\nB\n"


def test_clean_command_output_collapses_arcaned_double_read() -> None:
    """Short-lived containers return the whole stream twice; collapse only an exact doubling."""
    from arcane_mcp.tools.containers import _clean_command_output

    once = "2026-11-01T13:31:29.166Z A\n2026-11-01T13:31:29.167Z B\n"
    twice = once + "2026-11-01T13:31:29.359Z A\n2026-11-01T13:31:29.360Z B\n"
    assert _clean_command_output(twice) == "A\nB\n"


def test_clean_command_output_keeps_genuine_repeats() -> None:
    from arcane_mcp.tools.containers import _clean_command_output

    # uneven repetition is real output, not the double-read artifact
    raw = "A\nA\nA\n"
    assert _clean_command_output(raw) == "A\nA\nA\n"
    # and dedupe can be disabled entirely
    assert _clean_command_output("A\nA\n", dedupe=False) == "A\nA\n"
