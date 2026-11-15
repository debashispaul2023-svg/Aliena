"""Part C focused tests. Live services remain unverified."""

from jarvis.productivity.notifications import NotificationService
from jarvis.plugins.registry import PluginManifest, PluginRegistry
from jarvis.plugins.sandbox import execute_plugin
from jarvis.integrations.gemini_adapter import GeminiAdapter


def test_notification_not_delivered_without_provider():
    svc = NotificationService()
    note = svc.create("local", "deadline")
    svc.mark_delivered(note, provider_confirmed=False)
    assert note.state == "unverified"


def test_plugin_sandbox_does_not_execute():
    reg = PluginRegistry()
    reg.register(PluginManifest(name="notes-helper", capabilities=["read_notes"]))
    reg.enable("notes-helper", approved=True)
    result = execute_plugin(reg, "notes-helper", "read_notes")
    assert result["code_executed"] is False


def test_gemini_adapter_unverified_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert GeminiAdapter().status()["verified"] is False
