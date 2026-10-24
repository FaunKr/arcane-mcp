"""Arcane MCP server — entrypoint that registers all tools."""

from __future__ import annotations

import logging
import os

from fastmcp import FastMCP

from arcane_mcp.mode import get_mode
from arcane_mcp.tools import (
    activities,
    containers,
    environments,
    images,
    networks,
    operations,
    ports,
    projects,
    registries,
    system,
    updater,
    volumes,
    vulnerabilities,
    webhooks,
)

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

mcp = FastMCP("arcane-mcp")

_MODULES = {
    "activities": activities,
    "containers": containers,
    "environments": environments,
    "images": images,
    "networks": networks,
    "operations": operations,
    "ports": ports,
    "projects": projects,
    "registries": registries,
    "system": system,
    "updater": updater,
    "volumes": volumes,
    "vulnerabilities": vulnerabilities,
    "webhooks": webhooks,
}


def _selected_modules() -> list[str]:
    """Modules from ARCANE_MCP_MODULES (comma-separated), or all. ``operations`` is always loaded."""
    raw = os.environ.get("ARCANE_MCP_MODULES", "").strip()
    if not raw:
        return list(_MODULES)
    names = {n.strip().lower() for n in raw.split(",") if n.strip()}
    unknown = names - _MODULES.keys()
    if unknown:
        raise SystemExit(f"ARCANE_MCP_MODULES: unknown module(s) {sorted(unknown)}; valid: {sorted(_MODULES)}")
    names.add("operations")
    return [n for n in _MODULES if n in names]


# Register the selected tool sets with the MCP server
_loaded = _selected_modules()
for _name in _loaded:
    _MODULES[_name].register(mcp)

logger.info("Mode: %s | registered %d tool modules: %s", get_mode(), len(_loaded), ", ".join(_loaded))


def main() -> None:
    """Run the MCP server over stdio transport."""
    mcp.run()


if __name__ == "__main__":
    main()
