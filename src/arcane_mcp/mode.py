"""Model-hosting mode: ``local`` (self-hosted LLM) vs ``cloud`` (hosted LLM such as Claude).

Set ``ARCANE_MCP_MODE=local`` when the model runs on your own hardware.  Any
other value — including unset — means ``cloud``: tool output leaves your
machine, so secrets are redacted before they reach the model and secrets must
be passed by ``env:NAME`` reference instead of literally.
"""

from __future__ import annotations

import os
import re
from typing import Any

REDACTED = "[REDACTED]"

# Dict keys whose values are always redacted in cloud mode.
_SECRET_KEY_RE = re.compile(
    r"pass(word|wd)?$|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|credential",
    re.IGNORECASE,
)
# Keys the safety system itself returns; they are not secrets.
_SAFE_KEYS = {"confirmation_token", "operation_hash"}
# Container env lists ("KEY=VALUE" strings) — every value is redacted, not just secret-looking ones,
# because connection strings and the like carry credentials under innocuous names.
_ENV_LIST_KEYS = {"env", "environment"}

# "scheme://user:password@host" → keep user, drop password.
_URL_CREDS_RE = re.compile(r"(\b[a-z][a-z0-9+.-]*://[^:/\s@]+:)[^@\s/]+@", re.IGNORECASE)
# "DB_PASSWORD=x", "  api_key: x", "- SECRET_TOKEN=x" lines in compose/.env/log text.
_SECRET_LINE_RE = re.compile(
    r"""(?im)^(\s*-?\s*["']?[\w.-]*"""
    r"""(?:pass(?:word|wd)?|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|credential)"""
    r"""[\w.-]*["']?\s*[:=][ \t]*)(?=\S)(.+)$""",
)


def get_mode() -> str:
    return "local" if os.environ.get("ARCANE_MCP_MODE", "").strip().lower() == "local" else "cloud"


def is_cloud() -> bool:
    return get_mode() == "cloud"


def redact_text(text: str) -> str:
    text = _URL_CREDS_RE.sub(rf"\1{REDACTED}@", text)
    return _SECRET_LINE_RE.sub(rf"\1{REDACTED}", text)


def _redact_env_entry(entry: Any) -> Any:
    if isinstance(entry, str) and "=" in entry:
        return entry.split("=", 1)[0] + "=" + REDACTED
    return redact(entry)


def redact(value: Any) -> Any:
    """Return a copy of an API response with secrets removed (cloud mode only)."""
    if not is_cloud():
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            if key in _SAFE_KEYS:
                out[k] = v
            elif _SECRET_KEY_RE.search(key) and isinstance(v, (str, int, float)) and v != "":
                out[k] = REDACTED
            elif key.lower() in _ENV_LIST_KEYS and isinstance(v, list):
                out[k] = [_redact_env_entry(e) for e in v]
            elif key.lower() in _ENV_LIST_KEYS and isinstance(v, dict):
                out[k] = {ek: REDACTED for ek in v}
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def resolve_secret(value: str | None, field: str) -> str | None:
    """Resolve an ``env:NAME`` reference from the server's environment.

    In cloud mode literal secrets are rejected (raises ``ValueError``) so they
    never pass through the hosted model's context.  In local mode literals are
    accepted as-is.
    """
    if value is None or value == "":
        return value
    if value.startswith("env:"):
        name = value[4:]
        resolved = os.environ.get(name)
        if resolved is None:
            raise ValueError(f"{field}: environment variable {name!r} is not set on the MCP server")
        return resolved
    if is_cloud():
        raise ValueError(
            f"{field}: literal secrets are not accepted in cloud mode. "
            f"Set the value in the MCP server's environment and pass 'env:VAR_NAME' instead."
        )
    return value


def cloud_blocked(tool: str) -> dict[str, Any]:
    return {
        "error": f"{tool} is disabled in cloud mode because it returns raw file contents that may contain secrets. "
        "Set ARCANE_MCP_MODE=local to enable it when using a self-hosted model.",
        "mode": "cloud",
    }
