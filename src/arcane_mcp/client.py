"""HTTP client helpers for Arcane API."""
from __future__ import annotations

import logging
import os

import httpx
from dotenv import load_dotenv

from .mode import resolve_secret

logger = logging.getLogger(__name__)

load_dotenv()

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient | None:
    """Return a lazily-created AsyncClient for Arcane API, or None if not configured."""
    global _client
    if _client is None:
        base = os.environ.get("ARCANE_BASE_URL")
        key = os.environ.get("ARCANE_API_KEY")
        if not base or not key:
            logger.warning("Arcane client not configured: ARCANE_BASE_URL or ARCANE_API_KEY missing")
            return None
        _client = httpx.AsyncClient(
            base_url=base.rstrip("/"),
            headers={"X-Api-Key": key},
        )
        logger.info("Arcane client created for %s", base)
    return _client


def require_client() -> httpx.AsyncClient:
    client = get_client()
    if client is None:
        raise RuntimeError("ARCANE_BASE_URL and ARCANE_API_KEY must be set (and loaded) to use MCP tools.")
    return client


def _build_headers(agent_token: str | None = None) -> dict[str, str]:
    """Add X-Arcane-Agent-Token header if provided (``env:NAME`` references are resolved)."""
    headers: dict[str, str] = {}
    token = resolve_secret(agent_token, "agent_token")
    if token:
        headers["X-Arcane-Agent-Token"] = token
    return headers
