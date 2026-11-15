"""Isolated plugin execution boundary. Does not run arbitrary plugin code in-process."""

from __future__ import annotations

from jarvis.plugins.registry import PluginRegistry


def execute_plugin(registry: PluginRegistry, name: str, capability: str) -> dict:
    result = registry.invoke(name, capability)
    result["isolated"] = True
    result["code_executed"] = False
    if result.get("status") != "RECORDED":
        result["status"] = result.get("status", "BLOCKED")
    return result
