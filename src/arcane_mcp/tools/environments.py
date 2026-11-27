"""Environment management tools.

Arcane v3 renamed the ``environment`` resource to ``agent``: the collection is
``/api/agents`` and a single environment is ``/api/agents/{id}`` (which is what
``api_path(env_id)`` returns).  Tool names and signatures keep the v2 wording.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from fastmcp import FastMCP

from ..client import api_path, require_client
from ..mode import redact, resolve_secret
from ..safety import ToolClass, get_token_store

logger = logging.getLogger(__name__)

# Global collection; not agent-scoped, so it stays literal.
AGENTS_URL = "/api/agents"

_V3_ENROLL_HINT = (
    "Arcane v3 agents register themselves: the manager only stores the name and "
    "enabled flag, and the agent supplies its own access token when it enrolls "
    "(POST /api/agents/enroll or the pairing flow). api_url and agent_token are "
    "therefore not sent."
)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def list_environments() -> Any:
        """List all environments (local + remote agents)."""
        client = require_client()
        url = AGENTS_URL
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
        url = api_path(env_id)
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

        In Arcane v3 the manager only creates the agent record (name/enabled);
        the agent connects out to the manager and enrols itself with its own
        token, so ``api_url`` and ``agent_token`` are accepted for signature
        compatibility but are not part of the v3 create body.

        Pass agent_token as 'env:VAR_NAME' to read it from the MCP server's environment (required in cloud mode)."""
        client = require_client()
        url = AGENTS_URL
        try:
            # Resolve (and validate) the token reference even though v3 no longer
            # accepts it: a broken 'env:VAR' reference must fail before the call.
            agent_token_value = resolve_secret(agent_token, "agent_token")
            payload = {"name": name}
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            result = redact(resp.json())
            warnings = []
            if api_url:
                warnings.append(f"api_url {api_url!r} was not applied.")
            if agent_token_value:
                warnings.append("agent_token was not applied.")
            if isinstance(result, dict):
                result.setdefault(
                    "warning",
                    f"{' '.join(warnings)} {_V3_ENROLL_HINT}".strip(),
                )
            return result
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
        Pass agent_token as 'env:VAR_NAME' (required in cloud mode).

        Arcane v3 no longer lets the manager set an agent's access token, so
        agent_token is rejected instead of silently ignored."""
        if agent_token is not None:
            return {
                "error": "update_environment is not available in Arcane v3: agent access "
                "tokens are issued to the agent during enrollment (POST /api/agents/enroll) "
                "and can no longer be rotated by the manager. Call update_environment again "
                "without agent_token to change name or api_url.",
            }
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if api_url is not None:
            payload["apiUrl"] = api_url
        if not payload:
            return {"warning": "No update payload provided. Pass name, api_url or agent_token."}
        token = get_token_store().create(
            action="update_environment",
            target=env_id,
            endpoint=api_path(env_id),
            method="PATCH",
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
            endpoint=api_path(env_id),
            method="DELETE",
            body=None,
            params=None,
            classification=ToolClass.DESTRUCTIVE_WRITE,
            env_id=env_id,
            agent_token=None,
        )
        return {
            "warning": "Destructive operation. Call confirm_operation(token=...) to proceed.",
            "confirmation_token": token,
            "classification": ToolClass.DESTRUCTIVE_WRITE,
            "operation_hash": get_token_store().operation_hash(token),
            "target": env_id,
            "action": "remove_environment",
        }
