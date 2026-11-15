"""Feature 11 plugin tests. No arbitrary plugin code is executed."""

from jarvis.plugins.registry import PluginManifest, PluginRegistry


def test_plugin_requires_approval_and_does_not_execute():
    reg = PluginRegistry()
    reg.register(PluginManifest(name="notes-helper", capabilities=["read_notes"]))
    denied = reg.enable("notes-helper", approved=False)
    assert denied["status"] == "APPROVAL_REQUIRED"
    assert denied["executed"] is False
    ok = reg.enable("notes-helper", approved=True)
    assert ok["status"] == "ENABLED"
    result = reg.invoke("notes-helper", "read_notes")
    assert result["executed"] is False
    blocked = reg.invoke("notes-helper", "shell")
    assert blocked["status"] == "CAPABILITY_DENIED"
