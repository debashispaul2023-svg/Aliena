"""Sample plugin manifest. Documentation only. Not auto-executed."""

from jarvis.plugins.registry import PluginManifest

SAMPLE = PluginManifest(
    name="notes-helper",
    version="0.1.0",
    capabilities=["read_notes"],
    requires_approval=True,
)
