"""Container registry management tools.

Arcane v3 moved registries out of the per-environment API: they are global at
``/api/registries`` (so ``env_id`` is accepted for signature compatibility but
no longer selects a url), ``PUT`` became ``PATCH``, the credential field is
``token`` (was ``password``), testing is ``POST /api/registries/{id}?action=test``
and the v3 registry model has no ``name`` field (a registry is identified by its
URL).
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from fastmcp import FastMCP

from ..client import _build_headers, require_client
from ..mode import redact, resolve_secret
from ..safety import ToolClass, get_token_store

logger = logging.getLogger(__name__)

# Global collection; not agent-scoped, so it stays literal.
REGISTRIES_URL = "/api/registries"


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def list_registries(env_id: str = "0", agent_token: str | None = None) -> Any:
        """List all container registries."""
        client = require_client()
        url = REGISTRIES_URL
        try:
            resp = await client.get(url, headers=_build_headers(agent_token))
            resp.raise_for_status()
            return redact(resp.json())
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def create_registry(
        name: str,
        url: str,
        username: str = "",
        password: str = "",
        env_id: str = "0",
        agent_token: str | None = None,
    ) -> Any:
        """Create a new container registry.

        ``name`` is accepted for compatibility but v3 registries have no name
        field (they are identified by URL). ``password`` is sent as the v3
        ``token`` credential field.

        Pass password as 'env:VAR_NAME' to read it from the MCP server's environment (required in cloud mode)."""
        client = require_client()
        url_path = REGISTRIES_URL
        try:
            secret = resolve_secret(password, "password")
            payload: dict[str, Any] = {"url": url, "username": username, "token": secret}
            resp = await client.post(url_path, json=payload, headers=_build_headers(agent_token))
            resp.raise_for_status()
            return redact(resp.json())
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url_path, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url_path)
            return {"error": str(e)}

    @mcp.tool()
    async def get_registry(registry_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Get a container registry by ID."""
        client = require_client()
        url = f"{REGISTRIES_URL}/{registry_id}"
        try:
            resp = await client.get(url, headers=_build_headers(agent_token))
            resp.raise_for_status()
            return redact(resp.json())
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def update_registry(
        registry_id: str,
        name: str | None = None,
        url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        env_id: str = "0",
        agent_token: str | None = None,
    ) -> Any:
        """Update a container registry.

        v3 registries have no ``name`` field, so a name-only update is rejected
        rather than silently doing nothing. ``password`` is sent as ``token``.

        Pass password as 'env:VAR_NAME' to read it from the MCP server's environment (required in cloud mode)."""
        client = require_client()
        url_path = f"{REGISTRIES_URL}/{registry_id}"
        payload: dict[str, Any] = {}
        if url is not None:
            payload["url"] = url
        if username is not None:
            payload["username"] = username
        if not payload and password is None:
            if name is not None:
                return {
                    "error": "update_registry is not available in Arcane v3 for this change: "
                    "container registries have no `name` field (they are identified by URL). "
                    "Update `url`, `username` or `password` instead.",
                }
            return {"warning": "No update payload provided."}
        try:
            if password is not None:
                payload["token"] = resolve_secret(password, "password")
            resp = await client.patch(url_path, json=payload, headers=_build_headers(agent_token))
            resp.raise_for_status()
            return redact(resp.json())
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url_path, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url_path)
            return {"error": str(e)}

    @mcp.tool()
    async def delete_registry(registry_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Delete a container registry. Requires confirmation via confirmation_token."""
        token = get_token_store().create(
            action="delete_registry",
            target=registry_id,
            endpoint=f"{REGISTRIES_URL}/{registry_id}",
            method="DELETE",
            body=None,
            params=None,
            classification=ToolClass.DESTRUCTIVE_WRITE,
            env_id=env_id,
            agent_token=agent_token,
        )
        return {
            "warning": "Destructive operation. Call confirm_operation(token=...) to proceed.",
            "confirmation_token": token,
            "classification": ToolClass.DESTRUCTIVE_WRITE,
            "operation_hash": get_token_store().operation_hash(token),
            "target": registry_id,
            "action": "delete_registry",
        }

    @mcp.tool()
    async def test_registry(registry_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Test connectivity to a container registry."""
        client = require_client()
        url = f"{REGISTRIES_URL}/{registry_id}"
        try:
            resp = await client.post(url, params={"action": "test"}, headers=_build_headers(agent_token))
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}
