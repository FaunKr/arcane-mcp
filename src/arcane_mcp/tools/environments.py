"""Environment management tools."""
from __future__ import annotations

import logging
from typing import Any

import httpx
from fastmcp import FastMCP

from ..client import require_client
from ..mode import redact, resolve_secret
from ..safety import ToolClass, get_token_store

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def list_environments() -> Any:
        """List all environments (local + remote agents)."""
        client = require_client()
        url = "/api/environments"
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return redact(resp.json())
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def get_environment(env_id: str) -> Any:
        """Get details of a specific environment."""
        client = require_client()
        url = f"/api/environments/{env_id}"
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            result = resp.json()
            return {
                "classification": ToolClass.CREDENTIAL_SENSITIVE,
                "warning": "This response may contain sensitive data (env vars, secrets, config). Handle with care.",
                "data": redact(result),
            }
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def create_environment(name: str, api_url: str, agent_token: str) -> Any:
        """Register a new remote agent environment.

        Pass agent_token as 'env:VAR_NAME' to read it from the MCP server's environment (required in cloud mode)."""
        client = require_client()
        url = "/api/environments"
        try:
            access_token = resolve_secret(agent_token, "agent_token")
            payload = {"name": name, "apiUrl": api_url, "accessToken": access_token}
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return redact(resp.json())
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def update_environment(env_id: str, name: str | None = None, api_url: str | None = None, agent_token: str | None = None) -> Any:
        """Update environment settings (name, API URL, or access token). Requires confirmation token to execute,
        because repointing an environment redirects every later operation on it.
        Pass agent_token as 'env:VAR_NAME' (required in cloud mode)."""
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if api_url is not None:
            payload["apiUrl"] = api_url
        try:
            if agent_token is not None:
                payload["accessToken"] = resolve_secret(agent_token, "agent_token")
        except ValueError as e:
            return {"error": str(e)}
        if not payload:
            return {"warning": "No update payload provided. Pass name, api_url or agent_token."}
        token = get_token_store().create(
            action="update_environment",
            target=env_id,
            endpoint=f"/api/environments/{env_id}",
            method="PUT",
            body=payload,
            params=None,
            classification=ToolClass.DESTRUCTIVE_WRITE,
            env_id=env_id,
            agent_token=None,
        )
        return {
            "warning": "Environment update. Call confirm_operation(token=...) to proceed.",
            "confirmation_token": token,
            "operation_hash": get_token_store().operation_hash(token),
            "target": env_id,
            "action": "update_environment",
            "changes": {k: ("[REDACTED]" if k == "accessToken" else v) for k, v in payload.items()},
            "classification": ToolClass.DESTRUCTIVE_WRITE,
        }

    @mcp.tool()
    async def remove_environment(env_id: str) -> Any:
        """Remove an environment. Requires confirmation via confirmation_token."""
        token = get_token_store().create(
            action="remove_environment",
            target=env_id,
            endpoint=f"/api/environments/{env_id}",
            method="DELETE",
            body=None,
            params=None,
            classification=ToolClass.DESTRUCTIVE_WRITE,
            env_id=env_id,
            agent_token=None,
        )
        return {"warning": "Destructive operation. Call confirm_operation(token=...) to proceed.", "confirmation_token": token, "classification": ToolClass.DESTRUCTIVE_WRITE, "operation_hash": get_token_store().operation_hash(token), "target": env_id, "action": "remove_environment"}
