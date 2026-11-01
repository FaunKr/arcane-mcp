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
# Fields holding a whole dotenv document (a Compose project's `.env`). Same reasoning as
# _ENV_LIST_KEYS: an agent platform's DNS token lives under `HETZNER_API` and never matches a
# secret-name pattern, so *every* value is redacted here too.
_ENV_DOCUMENT_KEYS = {"envcontent", "env_content", "envfile", "env_file", "envfilecontent", "dotenv"}

# One line of a dotenv document: "KEY=value", optionally prefixed with "export " and indented.
_ENV_DOCUMENT_LINE_RE = re.compile(r"^(?P<prefix>[ \t]*(?:export[ \t]+)?)(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)=(?P<value>.*)$")

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
    if _looks_like_env_document(text):
        return redact_env_document(text)
    text = _URL_CREDS_RE.sub(rf"\1{REDACTED}@", text)
    return _SECRET_LINE_RE.sub(rf"\1{REDACTED}", text)


def _looks_like_env_document(text: str) -> bool:
    """True when most non-comment lines are "KEY=value" — i.e. this is a `.env` blob.

    Name-based matching cannot cover this: a `.env` holds credentials under names no
    secret-pattern recognises. Shape is the reliable signal, so a dotenv document is
    caught even when the API returns it under a field name we do not know about.
    """
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        return False
    matching = sum(1 for line in lines if _ENV_DOCUMENT_LINE_RE.match(line))
    return matching * 2 >= len(lines)


def redact_env_document(text: str) -> str:
    """Redact every value in a dotenv document, keeping keys, comments and line order."""
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        stripped = body.lstrip()
        match = _ENV_DOCUMENT_LINE_RE.match(body)
        if not stripped or stripped.startswith("#") or match is None or not match.group("value").strip():
            out.append(line)
            continue
        out.append(f"{match.group('prefix')}{match.group('key')}={REDACTED}{line[len(body) :]}")
    return "".join(out)


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
            elif key.lower() in _ENV_DOCUMENT_KEYS and isinstance(v, str):
                out[k] = redact_env_document(v)
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
