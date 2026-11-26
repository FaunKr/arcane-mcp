"""Tests for the client module."""
from __future__ import annotations

import pytest

from arcane_mcp import client


def test_require_client_raises_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """require_client raises RuntimeError when env vars are missing."""
    monkeypatch.delenv("ARCANE_BASE_URL", raising=False)
    monkeypatch.delenv("ARCANE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ARCANE_BASE_URL and ARCANE_API_KEY must be set"):
        client.require_client()


def test_require_client_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """require_client returns a client when env vars are set."""
    c = client.require_client()
    assert c is not None


def test_build_headers_empty() -> None:
    """_build_headers returns empty dict when no agent_token."""
    result = client._build_headers()
    assert result == {}


def test_build_headers_with_token() -> None:
    """_build_headers returns agent token header."""
    result = client._build_headers(agent_token="tok_abc")
    assert result == {"X-Arcane-Agent-Token": "tok_abc"}


def test_api_path_targets_v3_agents():
    """v3 renamed /api/environments/{id} to /api/agents/{id}."""
    from arcane_mcp.client import api_path

    assert api_path("0") == "/api/agents/0"
    assert api_path("0", "containers") == "/api/agents/0/containers"
    assert api_path("0", "containers", "abc") == "/api/agents/0/containers/abc"
    # leading/trailing slashes and empty segments must not double up
    assert api_path("0", "/projects/", "", "p1") == "/api/agents/0/projects/p1"
