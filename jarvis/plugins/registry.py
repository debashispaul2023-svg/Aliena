"""Plugin lifecycle. Plugins are never auto-executed or given unrestricted access."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PluginManifest:
    name: str
    version: str = "0.1.0"
    capabilities: list[str] = field(default_factory=list)
    requires_approval: bool = True


class PluginRegistry:
    def __init__(self) -> None:
        self.plugins: dict[str, PluginManifest] = {}
        self.enabled: set[str] = set()
        self.audit: list[dict[str, Any]] = []

    def register(self, manifest: PluginManifest) -> None:
        if not manifest.name or not manifest.name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("invalid plugin name")
        if any(cap in {"shell", "exec", "system"} for cap in manifest.capabilities):
            raise ValueError("privileged capability rejected")
        self.plugins[manifest.name] = manifest
        self.audit.append({"action": "register", "name": manifest.name, "executed": False})

    def enable(self, name: str, *, approved: bool) -> dict[str, Any]:
        if name not in self.plugins:
            return {"ok": False, "status": "NOT_FOUND", "executed": False}
        if not approved:
            self.audit.append({"action": "enable", "name": name, "status": "APPROVAL_REQUIRED", "executed": False})
            return {"ok": False, "status": "APPROVAL_REQUIRED", "executed": False}
        self.enabled.add(name)
        self.audit.append({"action": "enable", "name": name, "status": "ENABLED", "executed": False})
        return {"ok": True, "status": "ENABLED", "executed": False}

    def disable(self, name: str) -> dict[str, Any]:
        self.enabled.discard(name)
        self.audit.append({"action": "disable", "name": name, "status": "DISABLED", "executed": False})
        return {"ok": True, "status": "DISABLED", "executed": False}

    def invoke(self, name: str, capability: str) -> dict[str, Any]:
        plugin = self.plugins.get(name)
        if plugin is None or name not in self.enabled:
            return {"ok": False, "status": "BLOCKED", "executed": False}
        if capability not in plugin.capabilities:
            return {"ok": False, "status": "CAPABILITY_DENIED", "executed": False}
        # Capability invocation is recorded only. Arbitrary code is not executed.
        self.audit.append({"action": "invoke", "name": name, "capability": capability, "executed": False})
        return {"ok": True, "status": "RECORDED", "executed": False, "note": "plugin code was not executed"}
