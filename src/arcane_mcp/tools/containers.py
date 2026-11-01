"""Container lifecycle tools."""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from typing import Any

import httpx
from fastmcp import FastMCP

from ..client import _build_headers, require_client
from ..mode import redact
from ..safety import ToolClass, get_token_store

logger = logging.getLogger(__name__)

# Arcane's logs/download prefixes each line with an RFC3339 timestamp.
_LOG_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ?", re.MULTILINE)


def _clean_command_output(text: str, dedupe: bool = True) -> str:
    """Strip log timestamps, and collapse the exact double-read Arcane emits.

    For short-lived containers `logs/download` returns the whole stream twice (the
    second copy ~200ms later).  Only an exact line-for-line doubling is collapsed,
    so genuine repeated output from the command itself is preserved.
    """
    text = _LOG_TS_RE.sub("", text)
    if dedupe:
        lines = text.splitlines()
        half = len(lines) // 2
        if half and lines[:half] == lines[half:]:
            text = "\n".join(lines[:half]) + ("\n" if text.endswith("\n") else "")
    return text


def register(mcp: FastMCP) -> None:
    """Register all container tools."""

    @mcp.tool()
    async def list_containers(all: bool = False, env_id: str = "0", agent_token: str | None = None) -> Any:
        """List containers for a given Arcane environment."""
        client = require_client()
        url = f"/api/environments/{env_id}/containers"
        try:
            resp = await client.get(url, params={"all": str(all).lower()}, headers=_build_headers(agent_token))
            resp.raise_for_status()
            return redact(resp.json())
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def inspect_container(container_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Get detailed information about a specific container."""
        client = require_client()
        url = f"/api/environments/{env_id}/containers/{container_id}"
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
    async def start_container(container_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Start a stopped container."""
        client = require_client()
        url = f"/api/environments/{env_id}/containers/{container_id}/start"
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
    async def stop_container(container_id: str, timeout: int = 10, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Stop a running container gracefully."""
        client = require_client()
        url = f"/api/environments/{env_id}/containers/{container_id}/stop"
        try:
            resp = await client.post(url, headers=_build_headers(agent_token), json={"timeout": timeout})
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def restart_container(container_id: str, timeout: int = 10, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Restart a running container."""
        client = require_client()
        url = f"/api/environments/{env_id}/containers/{container_id}/restart"
        try:
            resp = await client.post(url, headers=_build_headers(agent_token), json={"timeout": timeout})
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def remove_container(
        container_id: str, force: bool = False, env_id: str = "0",
        agent_token: str | None = None,
    ) -> Any:
        """Remove a container. Requires confirmation token to execute."""
        token = get_token_store().create(
            action="remove_container",
            target=container_id,
            endpoint=f"/api/environments/{env_id}/containers/{container_id}",
            method="DELETE",
            params={"force": str(force).lower()},
            body=None,
            classification=ToolClass.DESTRUCTIVE_WRITE,
            env_id=env_id,
            agent_token=agent_token,
        )
        op_hash = get_token_store().operation_hash(token)
        return {
            "warning": "Destructive operation. Call confirm_operation(token=...) to proceed.",
            "confirmation_token": token,
            "operation_hash": op_hash,
            "target": container_id,
            "action": "remove_container",
            "classification": ToolClass.DESTRUCTIVE_WRITE,
        }

    @mcp.tool()
    async def create_container(
        image: str, name: str, env_id: str = "0",
        agent_token: str | None = None, command: str | None = None,
        env: str | None = None, labels: str | None = None,
    ) -> Any:
        """Create and optionally start a container. Command is a string that will be split into an array (e.g. 'sleep 60' becomes ['sleep', '60']). For the raw array form use the JSON format for env/labels."""
        client = require_client()
        url = f"/api/environments/{env_id}/containers"
        payload: dict[str, Any] = {"image": image, "name": name}
        if command:
            payload["cmd"] = command.split()
        if env:
            payload["env"] = env
        if labels:
            payload["labels"] = labels
        try:
            resp = await client.post(url, json=payload, headers=_build_headers(agent_token))
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def exec_in_container(container_id: str, command: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Execute a command inside a running container.

        NOTE: The Arcane API may not expose an exec endpoint; if it returns 404 this tool returns an error (there is no fallback)."""
        client = require_client()
        url = f"/api/environments/{env_id}/containers/{container_id}/exec"
        payload = {"cmd": command.split()}
        try:
            resp = await client.post(url, json=payload, headers=_build_headers(agent_token))
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            if resp.status_code == 404:
                return {"error": "Arcane API does not expose a container exec endpoint. Use SSH to the Docker host as a workaround.", "container_id": container_id}
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def run_command(
        command: str,
        container: str | None = None,
        image: str | None = None,
        network: str | None = None,
        binds: list[str] | None = None,
        workdir: str | None = None,
        timeout: int = 60,
        env_id: str = "0",
        agent_token: str | None = None,
        confirm: bool = False,
        dedupe_output: bool = True,
    ) -> Any:
        """Run a shell command and return its output, via a throwaway container.

        Arcane exposes no container exec endpoint, so this creates a short-lived
        container that runs `/bin/sh -c <command>`, waits for it to exit, captures
        stdout+stderr and the exit code, then force-removes the container.

        Pass `container="caddy-caddy-1"` to inherit that container's image, bind
        mounts and network — the command then sees the same files (e.g. a config
        bind-mounted into a service) and can reach the same peers. `image`, `binds`
        and `network` override the inherited values individually.

        Examples:
            run_command("caddy validate --config /etc/caddy/caddy.json", container="caddy-caddy-1")
            run_command("ls -la /srv", container="caddy-caddy-1")
            run_command("uptime", image="alpine:3", confirm=True)

        This executes arbitrary code on the Docker host, so it requires confirm=True.
        """
        if not container and not image:
            return {"error": "Provide either image=... or container=<name> to inherit image/mounts/network from."}

        if not confirm:
            return {
                "classification": ToolClass.DESTRUCTIVE_WRITE,
                "action": "run_command",
                "warning": "Runs an arbitrary command in a new container on the Docker host, then deletes it. "
                           "Review the plan and call again with confirm=True.",
                "plan": {
                    "command": command,
                    "image": image or f"(inherited from {container})",
                    "network": network or f"(inherited from {container})" if container else (network or "default"),
                    "binds": binds if binds is not None else (f"(inherited from {container})" if container else []),
                    "workdir": workdir,
                    "timeout_seconds": timeout,
                },
            }

        client = require_client()
        base = f"/api/environments/{env_id}/containers"
        headers = _build_headers(agent_token)

        inherited: dict[str, Any] = {}
        if container:
            try:
                resp = await client.get(f"{base}/{container}", headers=headers)
                resp.raise_for_status()
                inherited = resp.json().get("data") or {}
            except Exception as e:
                return {"error": f"cannot inspect container {container!r}: {e}", "container": container}

        run_image = image or inherited.get("image")
        if not run_image:
            return {"error": "no image resolved; pass image=..."}

        run_network = network
        if run_network is None:
            run_network = next(iter((inherited.get("networkSettings") or {}).get("networks") or {}), None)

        run_binds = binds
        if run_binds is None and inherited:
            run_binds = []
            for mount in inherited.get("mounts") or []:
                dest = mount.get("destination")
                if not dest:
                    continue
                source = mount.get("name") if mount.get("type") == "volume" else mount.get("source")
                if not source:
                    continue
                run_binds.append(f"{source}:{dest}" + ("" if mount.get("rw", True) else ":ro"))

        name = f"arcane-mcp-exec-{uuid.uuid4().hex[:8]}"
        payload: dict[str, Any] = {
            "image": run_image,
            "name": name,
            "entrypoint": ["/bin/sh", "-c"],
            "cmd": [command],
            "labels": {"arcane.mcp": "run_command", "arcane.mcp.target": container or ""},
            "hostConfig": {"binds": run_binds or [], "autoRemove": False},
        }
        if run_network:
            payload["networks"] = [run_network]
        if workdir:
            payload["workingDir"] = workdir

        started_at = time.monotonic()
        container_id: str | None = None
        state: dict[str, Any] = {}
        output = ""
        timed_out = False
        try:
            resp = await client.post(base, json=payload, headers=headers)
            if resp.status_code >= 400:
                return {
                    "error": "container create failed",
                    "status_code": resp.status_code,
                    "detail": redact(resp.text)[:500],
                    "image": run_image,
                }
            body = resp.json()
            container_id = ((body.get("data") or {}).get("id")) or body.get("id")
            if not container_id:
                return {"error": "container create returned no id", "response": resp.text[:300]}

            resp = await client.post(f"{base}/{container_id}/start", headers=headers)
            if resp.status_code >= 400:
                return {"error": "container start failed", "status_code": resp.status_code, "detail": redact(resp.text)[:500]}

            deadline = time.monotonic() + max(1, timeout)
            while True:
                poll = await client.get(f"{base}/{container_id}", headers=headers)
                poll.raise_for_status()
                state = (poll.json().get("data") or {}).get("state") or {}
                if not state.get("running"):
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                await asyncio.sleep(0.5)

            log_resp = await client.get(f"{base}/{container_id}/logs/download", params={"tail": "5000"}, headers=headers)
            if log_resp.status_code < 400:
                output = log_resp.text
        except httpx.HTTPStatusError as e:
            return {"error": str(e), "status_code": e.response.status_code, "detail": redact(e.response.text)[:500]}
        except Exception as e:
            logger.exception("run_command failed on %s", name)
            return {"error": str(e), "container": name}
        finally:
            if container_id:
                try:
                    await client.delete(f"{base}/{container_id}", params={"force": "true"}, headers=headers)
                except Exception:  # cleanup is best-effort; never mask the result
                    logger.warning("failed to remove throwaway container %s", container_id)

        limit = 20000
        return {
            "exit_code": state.get("exitCode"),
            "timed_out": timed_out,
            "output": redact(_clean_command_output(output, dedupe=dedupe_output))[:limit],
            "output_truncated": len(_clean_command_output(output, dedupe=dedupe_output)) > limit,
            "image": run_image,
            "network": run_network,
            "binds": run_binds or [],
            "duration_ms": int((time.monotonic() - started_at) * 1000),
        }

    @mcp.tool()
    async def get_container_logs(container_id: str, tail: int = 100, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Fetch a container's recent output (stdout+stderr) as text.

        Uses Arcane's `logs/download` endpoint, which streams the raw log rather than
        the (nonexistent) JSON streaming endpoint. Secret-looking lines are redacted
        in cloud mode."""
        client = require_client()
        url = f"/api/environments/{env_id}/containers/{container_id}/logs/download"
        try:
            resp = await client.get(url, params={"tail": str(tail)}, headers=_build_headers(agent_token))
            resp.raise_for_status()
            text = resp.text
            if "application/json" in resp.headers.get("content-type", ""):
                body = resp.json()
                payload = body.get("data") if isinstance(body, dict) else None
                text = payload if isinstance(payload, str) else resp.text
            return {"container_id": container_id, "tail": tail, "logs": redact(text)}
        except httpx.HTTPStatusError as e:
            if resp.status_code == 404:
                return {"error": "Logs endpoint not available for this Arcane build.", "container_id": container_id}
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def get_container_stats(container_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Get live resource usage stats for a container. NOTE: The Arcane API may not expose a stats endpoint. If 404 is returned, use SSH to the Docker host as workaround."""
        client = require_client()
        url = f"/api/environments/{env_id}/containers/{container_id}/stats"
        try:
            resp = await client.get(url, headers=_build_headers(agent_token))
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            if resp.status_code == 404:
                return {"error": "Stats endpoint not available in Arcane API. Use SSH to the Docker host as a workaround.", "container_id": container_id}
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def kill_container(container_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Force-kill a running container. Requires confirmation token to execute."""
        token = get_token_store().create(
            action="kill_container",
            target=container_id,
            endpoint=f"/api/environments/{env_id}/containers/{container_id}/kill",
            method="POST",
            body=None,
            params=None,
            classification=ToolClass.DESTRUCTIVE_WRITE,
            env_id=env_id,
            agent_token=agent_token,
        )
        op_hash = get_token_store().operation_hash(token)
        return {
            "warning": "Destructive operation. Call confirm_operation(token=...) to proceed.",
            "confirmation_token": token,
            "operation_hash": op_hash,
            "target": container_id,
            "action": "kill_container",
            "classification": ToolClass.DESTRUCTIVE_WRITE,
        }

    @mcp.tool()
    async def pause_container(container_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Pause a running container (freeze its processes)."""
        client = require_client()
        url = f"/api/environments/{env_id}/containers/{container_id}/pause"
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
    async def unpause_container(container_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Unpause a paused container."""
        client = require_client()
        url = f"/api/environments/{env_id}/containers/{container_id}/unpause"
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
    async def redeploy_container(container_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Redeploy a container using its original image and configuration."""
        client = require_client()
        url = f"/api/environments/{env_id}/containers/{container_id}/redeploy"
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
    async def commit_container(container_id: str, repo: str = "", tag: str = "latest", env_id: str = "0", agent_token: str | None = None) -> Any:
        """Commit a container's current state to a new image."""
        client = require_client()
        url = f"/api/environments/{env_id}/containers/{container_id}/commit"
        payload = {"repo": repo, "tag": tag}
        try:
            resp = await client.post(url, json=payload, headers=_build_headers(agent_token))
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def update_container(container_id: str, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Update a container's configuration (e.g. after image or resource changes)."""
        client = require_client()
        url = f"/api/environments/{env_id}/containers/{container_id}/update"
        try:
            resp = await client.post(url, json={}, headers=_build_headers(agent_token))
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def set_container_auto_update(container_id: str, enabled: bool, env_id: str = "0", agent_token: str | None = None) -> Any:
        """Enable or disable automatic updates for a container."""
        client = require_client()
        url = f"/api/environments/{env_id}/containers/{container_id}/auto-update"
        payload = {"enabled": enabled}
        try:
            resp = await client.put(url, json=payload, headers=_build_headers(agent_token))
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %s on %s: %s", resp.status_code, url, resp.text)
            return {"error": str(e), "status_code": resp.status_code, "detail": resp.text}
        except Exception as e:
            logger.exception("Unexpected error on %s", url)
            return {"error": str(e)}

    @mcp.tool()
    async def get_container_counts(env_id: str = "0", agent_token: str | None = None) -> Any:
        """Get container counts by status (running, stopped, paused, etc.)."""
        client = require_client()
        url = f"/api/environments/{env_id}/containers/counts"
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
