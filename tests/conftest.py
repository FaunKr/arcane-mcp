"""Shared test fixtures for arcane-mcp tests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastmcp import FastMCP

from arcane_mcp import safety
from arcane_mcp.tools import (
    containers,
    environments,
    images,
    networks,
    operations,
    projects,
    registries,
    system,
    volumes,
    webhooks,
)


@pytest.fixture(autouse=True)
def setup_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Set default env vars for all tests."""
    monkeypatch.setenv("ARCANE_BASE_URL", "http://localhost:3552")
    monkeypatch.setenv("ARCANE_API_KEY", "test-key-abc123")
    # Existing tool tests assert raw passthrough; cloud-mode redaction is tested in test_mode.py.
    monkeypatch.setenv("ARCANE_MCP_MODE", "local")
    # Token creation writes "proposed" audit events; keep them out of the real home directory.
    monkeypatch.setenv("ARCANE_MCP_AUDIT_LOG", str(tmp_path / "audit.log"))
    safety._audit_log = None
    safety._token_store = None


@pytest.fixture
def mcp() -> FastMCP:
    """Return a FastMCP instance with all tools registered."""
    mcp = FastMCP("test-arcane")
    containers.register(mcp)
    environments.register(mcp)
    images.register(mcp)
    networks.register(mcp)
    operations.register(mcp)
    projects.register(mcp)
    registries.register(mcp)
    system.register(mcp)
    volumes.register(mcp)
    webhooks.register(mcp)
    return mcp


async def call_tool(mcp: FastMCP, tool_name: str, **kwargs: Any) -> Any:
    """Call a registered MCP tool by name and return the raw result."""
    result = await mcp.call_tool(tool_name, kwargs)
    # ToolResult.content is a list of TextContent with .text as JSON
    if result.content and hasattr(result.content[0], "text"):
        return json.loads(result.content[0].text)
    return result.content


async def propose_and_confirm(mcp: FastMCP, tool_name: str, **kwargs: Any) -> Any:
    """Run a gated tool's two-step flow: propose, then confirm with the returned token and hash."""
    proposal = await call_tool(mcp, tool_name, **kwargs)
    assert "confirmation_token" in proposal, proposal
    return await call_tool(
        mcp, "confirm_operation",
        token=proposal["confirmation_token"], operation_hash=proposal["operation_hash"],
    )
