"""Compose project management tools."""
from __future__ import annotations

import logging
from typing import Any

import httpx
from fastmcp import FastMCP

from ..client import _build_headers, api_path, require_client
from ..mode import redact
from ..safety import ToolClass, get_token_store

logger = logging.getLogger(__name__)


def _parse_compose_plan(compose_content: str) -> dict:
    """Extract a basic plan/receipt from compose content without yaml parser."""
    plan = {"services": [], "images": []}
    current_service = None
    for line in compose_content.split('\n'):
        stripped = line.strip()
        if stripped.startswith('#') or not stripped:
            continue
        # Detect service definition (top-level key with colon, not indented)
        top_level_block = ('services:', 'networks:', 'volumes:', 'configs:', 'secrets:')
        if (
            not line.startswith(' ') and not line.startswith('\t')
            and stripped.endswith(':') and stripped not in top_level_block
        ):
            current_service = stripped[:-1]
            plan["services"].append(current_service)
        elif 'image:' in stripped and current_service:
            img = stripped.split('image:')[1].strip().strip('"').strip("'")
            if img:
                plan["images"].append(img)
    return plan


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def list_projects(env_id: str = "0", agent_token: str | None = None) -> Any:
        """List all Compose projects in the given environment."""
        client = require_client()
        url = api_path(env_id, "projects")
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
    async def get_project(project_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Get details of a specific Compose project."""
        client = require_client()
        url = api_path(env_id, "projects", project_id)
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
    async def deploy_project(compose_content: str, project_name: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Deploy a new Compose project from compose content.

        Not available against Arcane v3: creating a project requires a multipart
        workspace upload whose manifest schema is unpublished.
        """
        plan = _parse_compose_plan(compose_content)
        return {
            "error": "deploy_project is not available in Arcane v3 as a JSON request.",
            "reason": "v3 changed POST /projects to multipart/form-data. The OpenAPI document requires a "
                      "``project`` field (JSON-encoded Project: name, composeContent, envContent, ...) and a "
                      "``manifest`` field (JSON-encoded initial project workspace manifest), plus optional "
                      "binary ``files``. The manifest schema is not published, so this tool refuses to send a "
                      "request that the server would reject (422) or misread.",
            "v3_contract": {
                "endpoint": api_path(env_id, "projects"),
                "method": "POST",
                "content_type": "multipart/form-data",
                "fields": {
                    "project": "JSON string: {\"name\": ..., \"composeContent\": ...}",
                    "manifest": "JSON string: initial project workspace manifest (schema not published)",
                    "files": "optional binary file parts",
                },
            },
            "alternatives": [
                "Create the project in the Arcane UI (Projects -> Create).",
                f"Then use update_project(project_id=...) or the {api_path(env_id, 'projects', '{projectId}', 'deploy')} endpoint.",
            ],
            "plan": plan,
            "target": project_name,
            "action": "deploy_project",
        }

    @mcp.tool()
    async def redeploy_project(project_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Redeploy a Compose project."""
        client = require_client()
        # v3 consolidated up/redeploy/pull into /deploy?action=...
        url = api_path(env_id, "projects", project_id, "deploy")
        params = {"action": "redeploy"}
        try:
            resp = await client.post(url, params=params, headers=_build_headers(agent_token))
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def remove_project(project_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Remove a Compose project."""
        token = get_token_store().create(
            action="remove_project",
            target=project_id,
            endpoint=api_path(env_id, "projects", project_id),
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
            "target": project_id,
            "action": "remove_project",
        }

    @mcp.tool()
    async def update_project(
        project_id: str, env_id: str = "0",
        agent_token: str | None = None, compose_content: str | None = None,
        project_name: str | None = None,
    ) -> Any:
        """Update a Compose project's configuration."""
        payload: dict = {}
        if compose_content is not None:
            # v3 renamed the field to ``composeContent``.
            payload["composeContent"] = compose_content
        if project_name is not None:
            payload["name"] = project_name
        if not payload:
            return {"warning": "No update payload provided. Pass compose_content or project_name to update."}
        plan = {}
        if compose_content:
            plan = _parse_compose_plan(compose_content)
        token = get_token_store().create(
            action="update_project",
            target=project_id,
            endpoint=api_path(env_id, "projects", project_id),
            # v3 replaced PUT with PATCH.
            method="PATCH",
            body=payload,
            params=None,
            classification=ToolClass.DESTRUCTIVE_WRITE,
            env_id=env_id,
            agent_token=agent_token,
        )
        op_hash = get_token_store().operation_hash(token)
        return {
            "classification": ToolClass.DESTRUCTIVE_WRITE,
            "risk_level": "high",
            "warning": "Compose update is a high-risk operation. "
                       f"This will update project '{project_id}' and may mutate networks, volumes, "
                       "env, images, and restart policies. Verify the plan, then call confirm_operation() with the token.",
            "confirmation_token": token,
            "operation_hash": op_hash,
            "target": project_id,
            "action": "update_project",
            "plan": plan,
        }

    @mcp.tool()
    async def get_project_counts(env_id: str = "0", agent_token: str | None = None) -> Any:
        """Get counts of Compose projects in the given environment."""
        client = require_client()
        url = api_path(env_id, "projects", "counts")
        try:
            resp = await client.get(url, headers=_build_headers(agent_token))
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def project_down(project_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Take a Compose project down (stop and remove containers)."""
        token = get_token_store().create(
            action="project_down",
            target=project_id,
            endpoint=api_path(env_id, "projects", project_id),
            method="POST",
            body=None,
            # v3 runs project lifecycle actions through ?action=...
            params={"action": "down"},
            classification=ToolClass.DESTRUCTIVE_WRITE,
            env_id=env_id,
            agent_token=agent_token,
        )
        return {
            "warning": "Destructive operation. Call confirm_operation(token=...) to proceed.",
            "confirmation_token": token,
            "classification": ToolClass.DESTRUCTIVE_WRITE,
            "operation_hash": get_token_store().operation_hash(token),
            "target": project_id,
            "action": "project_down",
        }

    @mcp.tool()
    async def restart_project(project_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Restart a Compose project."""
        token = get_token_store().create(
            action="restart_project",
            target=project_id,
            endpoint=api_path(env_id, "projects", project_id),
            method="POST",
            body=None,
            params={"action": "restart"},
            classification=ToolClass.DESTRUCTIVE_WRITE,
            env_id=env_id,
            agent_token=agent_token,
        )
        return {
            "warning": "Destructive operation. Call confirm_operation(token=...) to proceed.",
            "confirmation_token": token,
            "classification": ToolClass.DESTRUCTIVE_WRITE,
            "operation_hash": get_token_store().operation_hash(token),
            "target": project_id,
            "action": "restart_project",
        }

    @mcp.tool()
    async def build_project(project_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Build a Compose project's images."""
        client = require_client()
        url = api_path(env_id, "projects", project_id, "build")
        try:
            resp = await client.post(url, headers=_build_headers(agent_token))
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def archive_project(project_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Archive a Compose project."""
        client = require_client()
        url = api_path(env_id, "projects", project_id)
        params = {"action": "archive"}
        try:
            resp = await client.post(url, params=params, headers=_build_headers(agent_token))
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def unarchive_project(project_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Unarchive a Compose project."""
        client = require_client()
        url = api_path(env_id, "projects", project_id)
        params = {"action": "unarchive"}
        try:
            resp = await client.post(url, params=params, headers=_build_headers(agent_token))
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def pull_project_images(project_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Pull images for a Compose project."""
        client = require_client()
        url = api_path(env_id, "projects", project_id, "deploy")
        params = {"action": "pull"}
        try:
            resp = await client.post(url, params=params, headers=_build_headers(agent_token))
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def get_project_compose(project_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Get the Compose file content for a project."""
        client = require_client()
        url = api_path(env_id, "projects", project_id, "compose")
        try:
            resp = await client.get(url, headers=_build_headers(agent_token))
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
    async def get_project_file(project_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Get the project file content for a Compose project.

        Not available against Arcane v3: the project-level ``/file`` endpoint was
        replaced by the project workspace file endpoints.
        """
        return {
            "error": "get_project_file is not available in Arcane v3.",
            "reason": "v3 removed GET /projects/{projectId}/file. Project files are now read from the project "
                      "workspace, which requires a relativePath argument the v3 tool signature does not have.",
            "v3_equivalents": {
                "compose": api_path(env_id, "projects", project_id, "compose"),
                "workspace_file": api_path(env_id, "projects", project_id, "workspace", "file"),
            },
            "suggestion": "Use get_project_compose for the compose file, or read the workspace file via the "
                          "Arcane UI / an explicit relativePath call.",
            "target": project_id,
        }

    @mcp.tool()
    async def update_project_services(project_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Update services of a Compose project from the current compose config."""
        client = require_client()
        url = api_path(env_id, "projects", project_id)
        params = {"action": "updateservices"}
        try:
            resp = await client.post(url, params=params, headers=_build_headers(agent_token))
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def get_project_runtime(project_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Get the runtime info for a Compose project."""
        client = require_client()
        url = api_path(env_id, "projects", project_id, "runtime")
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
