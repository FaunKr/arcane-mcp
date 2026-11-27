"""Tests for webhook tools."""
from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import call_tool


@pytest.mark.asyncio
async def test_trigger_webhook_removed_in_v3(mcp: Any, httpx_mock: Any) -> None:
    """v3 dropped the inbound trigger endpoint; the tool must say so and not call the API."""
    result = await call_tool(mcp, "trigger_webhook", token="tok_abc", action="deploy")
    assert "not available in Arcane v3" in result["error"]
    assert httpx_mock.get_requests() == []
