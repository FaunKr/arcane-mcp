"""Tests for cloud/local mode: redaction, env: secret references, blocked tools, hash consistency."""
from __future__ import annotations

import json
from typing import Any

import pytest

from arcane_mcp.mode import REDACTED, redact, redact_text, resolve_secret
from tests.conftest import call_tool


@pytest.fixture
def cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCANE_MCP_MODE", "cloud")


# ── redaction ─────────────────────────────────────────────────────────


def test_unset_mode_is_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARCANE_MCP_MODE")
    assert redact({"password": "hunter2"}) == {"password": REDACTED}


def test_local_mode_passes_through() -> None:
    data = {"password": "hunter2", "Env": ["A=b"]}
    assert redact(data) == data


def test_env_list_values_redacted(cloud: None) -> None:
    data = {"Config": {"Env": ["DATABASE_URL=postgres://u:p@db/x", "TZ=Europe/Berlin"], "Image": "nginx"}}
    assert redact(data) == {"Config": {"Env": [f"DATABASE_URL={REDACTED}", f"TZ={REDACTED}"], "Image": "nginx"}}


def test_secret_keys_redacted_but_safety_keys_kept(cloud: None) -> None:
    data = {"accessToken": "abc", "apiKey": "k", "name": "x", "confirmation_token": "t1", "operation_hash": "h"}
    assert redact(data) == {"accessToken": REDACTED, "apiKey": REDACTED, "name": "x", "confirmation_token": "t1", "operation_hash": "h"}


def test_compose_text_redacted(cloud: None) -> None:
    compose = (
        "services:\n"
        "  db:\n"
        "    image: postgres:16\n"
        "    environment:\n"
        "      - POSTGRES_PASSWORD=supersecret\n"
        "      API_TOKEN: abc123\n"
        "      REDIS_URL: redis://default:pw@redis:6379\n"
        "secrets:\n"
        "  db_pw:\n"
    )
    out = redact_text(compose)
    assert "supersecret" not in out and "abc123" not in out and ":pw@" not in out
    assert "image: postgres:16" in out
    assert "secrets:\n" in out


def test_resolve_secret(monkeypatch: pytest.MonkeyPatch, cloud: None) -> None:
    monkeypatch.setenv("REG_PW", "s3cret")
    assert resolve_secret("env:REG_PW", "password") == "s3cret"
    with pytest.raises(ValueError, match="literal secrets"):
        resolve_secret("s3cret", "password")
    with pytest.raises(ValueError, match="not set"):
        resolve_secret("env:MISSING_VAR", "password")


def test_resolve_secret_local_accepts_literal() -> None:
    assert resolve_secret("s3cret", "password") == "s3cret"


# ── tools in cloud mode ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_inspect_container_redacts_env(mcp: Any, httpx_mock: Any, cloud: None) -> None:
    httpx_mock.add_response(
        url="http://localhost:3552/api/environments/0/containers/c1",
        method="GET",
        json={"id": "c1", "config": {"env": ["SECRET_KEY=abc"]}},
    )
    result = await call_tool(mcp, "inspect_container", container_id="c1")
    assert result["data"]["config"]["env"] == [f"SECRET_KEY={REDACTED}"]


@pytest.mark.asyncio
async def test_read_volume_file_blocked_in_cloud(mcp: Any, cloud: None) -> None:
    result = await call_tool(mcp, "read_volume_file", name="v", path="/etc/app.conf")
    assert "disabled in cloud mode" in result["error"]


@pytest.mark.asyncio
async def test_create_registry_rejects_literal_password_in_cloud(mcp: Any, cloud: None) -> None:
    result = await call_tool(mcp, "create_registry", name="r", url="ghcr.io", username="me", password="literal")
    assert "literal secrets" in result["error"]


@pytest.mark.asyncio
async def test_create_registry_env_reference(mcp: Any, httpx_mock: Any, monkeypatch: pytest.MonkeyPatch, cloud: None) -> None:
    monkeypatch.setenv("GHCR_PW", "real-pw")
    httpx_mock.add_response(url="http://localhost:3552/api/container-registries", method="POST", json={"id": "r1", "password": "real-pw"})
    result = await call_tool(mcp, "create_registry", name="r", url="ghcr.io", username="me", password="env:GHCR_PW")
    assert json.loads(httpx_mock.get_requests()[0].content)["password"] == "real-pw"
    assert result == {"id": "r1", "password": REDACTED}


# ── newly gated writes and hash consistency ───────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "kwargs"),
    [
        ("upload_to_volume", {"name": "v", "path": "/a.txt", "content": "hi"}),
        ("build_image", {"dockerfile_content": "FROM alpine", "tag": "t"}),
        ("update_environment", {"env_id": "0", "name": "n"}),
    ],
)
async def test_risky_writes_need_confirmation(mcp: Any, tool: str, kwargs: dict[str, Any]) -> None:
    result = await call_tool(mcp, tool, **kwargs)
    assert "confirmation_token" in result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "kwargs", "method", "url"),
    [
        ("remove_volume", {"name": "v"}, "DELETE", "http://localhost:3552/api/environments/0/volumes/v"),
        ("remove_network", {"network_id": "n"}, "DELETE", "http://localhost:3552/api/environments/0/networks/n"),
        ("delete_volume_file", {"name": "v", "path": "/x"}, "DELETE", "http://localhost:3552/api/environments/0/volumes/v/browse?path=%2Fx"),
    ],
)
async def test_returned_hash_confirms(mcp: Any, httpx_mock: Any, tool: str, kwargs: dict[str, Any], method: str, url: str) -> None:
    """The operation_hash a tool returns must be accepted by confirm_operation (previously mismatched)."""
    httpx_mock.add_response(url=url, method=method, json={"ok": True})
    proposal = await call_tool(mcp, tool, **kwargs)
    result = await call_tool(mcp, "confirm_operation", token=proposal["confirmation_token"], operation_hash=proposal["operation_hash"])
    assert result == {"ok": True}
