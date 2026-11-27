"""Volume management tools."""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from fastmcp import FastMCP

from ..client import _build_headers, api_path, require_client
from ..mode import cloud_blocked, is_cloud
from ..safety import ToolClass, get_token_store

logger = logging.getLogger(__name__)


def _parse_labels(labels: str | None) -> dict[str, str] | None:
    """Parse the ``labels`` string into the string map Arcane v3 expects.

    Accepts either a JSON object (``{"a": "b"}``) or comma-separated
    ``key=value`` pairs (``a=b,c=d``).
    """
    if not labels:
        return None
    text = labels.strip()
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
    result: dict[str, str] = {}
    for pair in text.split(","):
        key, _, value = pair.partition("=")
        if key.strip():
            result[key.strip()] = value.strip()
    return result


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def list_volumes(env_id: str = "0", agent_token: str | None = None) -> Any:
        """List all volumes in the given environment."""
        client = require_client()
        url = api_path(env_id, "volumes")
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
    async def create_volume(
        name: str, driver: str = "local", labels: str | None = None,
        env_id: str = "0", agent_token: str | None = None,
    ) -> Any:
        """Create a new volume in the given environment."""
        client = require_client()
        url = api_path(env_id, "volumes")
        body: dict[str, Any] = {"name": name, "driver": driver}
        parsed_labels = _parse_labels(labels)
        if parsed_labels is not None:
            body["labels"] = parsed_labels
        try:
            resp = await client.post(url, json=body, headers=_build_headers(agent_token))
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def inspect_volume(name: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Inspect a volume by name."""
        client = require_client()
        url = api_path(env_id, "volumes", name)
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
    async def remove_volume(
        name: str, force: bool = False, env_id: str = "0",
        agent_token: str | None = None,
    ) -> Any:
        """Remove a volume by name. Destructive; requires confirmation token."""
        token = get_token_store().create(
            action="remove_volume",
            target=f"volume:{name}",
            endpoint=api_path(env_id, "volumes", name),
            method="DELETE",
            # v3 moved ``force`` from the body to a query parameter.
            params={"force": str(force).lower()},
            classification=ToolClass.DESTRUCTIVE_WRITE,
            env_id=env_id,
            agent_token=agent_token,
        )
        op_hash = get_token_store().operation_hash(token)
        return {
            "warning": "Destructive operation. Call confirm_operation(token=...) to proceed.",
            "confirmation_token": token,
            "operation_hash": op_hash,
            "target": f"volume:{name}",
            "action": "remove_volume",
            "classification": ToolClass.DESTRUCTIVE_WRITE,
        }

    @mcp.tool()
    async def prune_volumes(env_id: str = "0", agent_token: str | None = None, dry_run: bool = True) -> Any:
        """Prune unused Docker volumes. Destructive; use dry_run=False and confirm to execute."""
        if dry_run:
            return {
                "dry_run": True,
                "warning": "Dry-run: nothing was queried or changed. Review candidates with the list_* tools, "
                           "then set dry_run=False and confirm to execute.",
                "action": "prune_volumes",
                "target": "all",
            }
        token = get_token_store().create(
            action="prune_volumes",
            target="all",
            endpoint=api_path(env_id, "volumes", "prune"),
            method="POST",
            classification=ToolClass.DESTRUCTIVE_WRITE,
            env_id=env_id,
            agent_token=agent_token,
        )
        op_hash = get_token_store().operation_hash(token)
        return {
            "warning": "Destructive operation. Call confirm_operation(token=...) to proceed.",
            "confirmation_token": token,
            "operation_hash": op_hash,
            "target": "all",
            "action": "prune_volumes",
            "classification": ToolClass.DESTRUCTIVE_WRITE,
        }

    # ── Volume counts & sizes ──────────────────────────────────────────────

    @mcp.tool()
    async def get_volume_counts(env_id: str = "0", agent_token: str | None = None) -> Any:
        """Get volume counts for the given environment."""
        client = require_client()
        url = api_path(env_id, "volumes", "counts")
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
    async def get_volume_sizes(env_id: str = "0", agent_token: str | None = None) -> Any:
        """Get volume sizes for the given environment."""
        client = require_client()
        url = api_path(env_id, "volumes", "sizes")
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
    async def get_volume_usage(name: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Get disk usage for a specific volume."""
        client = require_client()
        url = api_path(env_id, "volumes", name, "usage")
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

    # ── Volume backups ─────────────────────────────────────────────────────

    @mcp.tool()
    async def list_volume_backups(name: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """List all backups for a volume."""
        client = require_client()
        url = api_path(env_id, "volumes", name, "backups")
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
    async def create_volume_backup(name: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Create a new backup of a volume."""
        client = require_client()
        url = api_path(env_id, "volumes", name, "backups")
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
    async def restore_volume_backup(
        volume_name: str, backup_id: str, env_id: str = "0",
        agent_token: str | None = None,
    ) -> Any:
        """Restore a volume backup. Destructive; requires confirmation token."""
        token = get_token_store().create(
            action="restore_volume_backup",
            target=f"volume:{volume_name}/backup:{backup_id}",
            endpoint=api_path(env_id, "volumes", volume_name, "backups", backup_id),
            method="POST",
            # v3 replaced ``/backups/{id}/restore`` with ?action=restore (or restorefiles).
            params={"action": "restore"},
            classification=ToolClass.DESTRUCTIVE_WRITE,
            env_id=env_id,
            agent_token=agent_token,
        )
        op_hash = get_token_store().operation_hash(token)
        return {
            "warning": "Destructive operation. Call confirm_operation(token=...) to proceed.",
            "confirmation_token": token,
            "operation_hash": op_hash,
            "target": f"volume:{volume_name}/backup:{backup_id}",
            "action": "restore_volume_backup",
            "classification": ToolClass.DESTRUCTIVE_WRITE,
        }

    @mcp.tool()
    async def delete_volume_backup(
        backup_id: str, env_id: str = "0",
        agent_token: str | None = None,
    ) -> Any:
        """Delete a volume backup. Destructive; requires confirmation token."""
        token = get_token_store().create(
            action="delete_volume_backup",
            target=f"backup:{backup_id}",
            # v3 keeps volume backups under a backup-id-addressed collection.
            endpoint=api_path(env_id, "volumes", "backups", backup_id),
            method="DELETE",
            classification=ToolClass.DESTRUCTIVE_WRITE,
            env_id=env_id,
            agent_token=agent_token,
        )
        op_hash = get_token_store().operation_hash(token)
        return {
            "warning": "Destructive operation. Call confirm_operation(token=...) to proceed.",
            "confirmation_token": token,
            "operation_hash": op_hash,
            "target": f"backup:{backup_id}",
            "action": "delete_volume_backup",
            "classification": ToolClass.DESTRUCTIVE_WRITE,
        }

    @mcp.tool()
    async def download_volume_backup(backup_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Download a volume backup. Disabled in cloud mode (raw contents may contain secrets)."""
        if is_cloud():
            return cloud_blocked("download_volume_backup")
        client = require_client()
        url = api_path(env_id, "volumes", "backups", backup_id, "download")
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

    # ── Volume file browser (v3 workspace) ─────────────────────────────────

    @mcp.tool()
    async def browse_volume(
        name: str, path: str = "/", env_id: str = "0",
        agent_token: str | None = None,
    ) -> Any:
        """List files and directories at a path inside a volume."""
        client = require_client()
        # v3 replaced /volumes/{name}/browse with the volume workspace listing.
        url = api_path(env_id, "volumes", name, "workspace")
        params = {"path": path}
        try:
            resp = await client.get(url, params=params, headers=_build_headers(agent_token))
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def read_volume_file(
        name: str, path: str, env_id: str = "0",
        agent_token: str | None = None,
    ) -> Any:
        """Read the contents of a file inside a volume. Disabled in cloud mode (raw contents may contain secrets)."""
        if is_cloud():
            return cloud_blocked("read_volume_file")
        client = require_client()
        # v3 replaced /browse/content with the workspace file endpoint; the query
        # parameter is now ``relativePath``.
        url = api_path(env_id, "volumes", name, "workspace", "file")
        params = {"relativePath": path}
        try:
            resp = await client.get(url, params=params, headers=_build_headers(agent_token))
            resp.raise_for_status()
            result = resp.json()
            return {
                "classification": ToolClass.CREDENTIAL_SENSITIVE,
                "warning": "This response may contain sensitive data (env vars, secrets, config). Handle with care.",
                "data": result,
            }
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def create_volume_directory(
        name: str, path: str, env_id: str = "0",
        agent_token: str | None = None,
    ) -> Any:
        """Create a directory inside a volume."""
        return {
            "error": "create_volume_directory is not available in Arcane v3.",
            "reason": "v3 removed the /volumes/{volumeName}/browse/mkdir endpoint. Directories are now "
                      "created as part of a volume workspace update (multipart manifest + files), and the "
                      "manifest schema is not published in the v3 OpenAPI document.",
            "v3_equivalent": {
                "endpoint": api_path(env_id, "volumes", name, "workspace"),
                "method": "PATCH",
                "content_type": "multipart/form-data",
                "fields": ["manifest (JSON string)", "files[] (binary)"],
            },
            "suggestion": "Create the directory from the Arcane UI or by mounting the volume in a container; "
                          "the MCP server will not guess the manifest format for a write into volume data.",
        }

    @mcp.tool()
    async def upload_to_volume(
        name: str, path: str, content: str, env_id: str = "0",
        agent_token: str | None = None,
    ) -> Any:
        """Upload a file to a path inside a volume.

        Not available against Arcane v3: writing requires the multipart volume
        workspace contract, whose manifest schema is unpublished.
        """
        return {
            "error": "upload_to_volume is not available in Arcane v3.",
            "reason": "v3 removed /volumes/{volumeName}/browse/upload. Writes now go through "
                      "PATCH /volumes/{volumeName}/workspace as multipart/form-data carrying a JSON-encoded "
                      "``manifest`` plus binary ``files``. The manifest schema is not published in the v3 "
                      "OpenAPI document, so this tool refuses to send a request that could clobber volume contents.",
            "v3_equivalent": {
                "endpoint": api_path(env_id, "volumes", name, "workspace"),
                "method": "PATCH",
                "content_type": "multipart/form-data",
                "fields": ["manifest (JSON string)", "files[] (binary)"],
            },
            "target": f"volume:{name}:{path}",
            "bytes": len(content.encode()),
            "suggestion": "Use the Arcane UI file editor, or mount the volume into a container and write the file there.",
        }

    @mcp.tool()
    async def delete_volume_file(
        name: str, path: str, env_id: str = "0",
        agent_token: str | None = None,
    ) -> Any:
        """Delete a file or directory inside a volume."""
        return {
            "error": "delete_volume_file is not available in Arcane v3.",
            "reason": "v3 removed DELETE /volumes/{volumeName}/browse. File deletions are now applied through "
                      "the volume workspace update (multipart manifest + files), and the manifest schema is "
                      "not published in the v3 OpenAPI document.",
            "v3_equivalent": {
                "endpoint": api_path(env_id, "volumes", name, "workspace"),
                "method": "PATCH",
                "content_type": "multipart/form-data",
                "fields": ["manifest (JSON string)", "files[] (binary)"],
            },
            "target": f"volume:{name}:{path}",
            "suggestion": "Delete the file from the Arcane UI, or from a container that mounts the volume.",
        }
