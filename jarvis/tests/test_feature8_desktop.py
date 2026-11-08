"""Feature 8 focused tests. Mock execution is never treated as real desktop success."""

from __future__ import annotations

from jarvis.desktop.capabilities import detect_environment
from jarvis.desktop.controller import build_test_controller
from jarvis.desktop.engine import DesktopAutomationEngine
from jarvis.desktop.platforms.mock import MockAdapter


def test_capability_detection_reports_status():
    report = detect_environment()
    assert report.status in {"PARTIAL", "UNSUPPORTED"}
    assert "mouse" in report.capabilities


def test_permission_and_approval_enforced():
    engine = DesktopAutomationEngine(controller=build_test_controller())
    denied = engine.run("click", {"x": 1, "y": 2})
    assert denied["status"] == "PERMISSION_DENIED"
    assert denied["executed"] is False
    engine.grant("click")
    need = engine.run("click", {"x": 1, "y": 2})
    assert need["status"] == "APPROVAL_REQUIRED"
    engine.approve("click")
    result = engine.run("click", {"x": 1, "y": 2})
    assert result["status"] == "MOCK_OK"
    assert result["executed"] is False
    assert result.get("mock") is True


def test_invalid_url_rejected():
    engine = DesktopAutomationEngine(controller=build_test_controller())
    engine.grant("open_url")
    engine.approve("open_url")
    result = engine.run("open_url", {"url": "file:///etc/passwd"})
    assert result["ok"] is False
    assert result["status"] == "INVALID"


def test_cancel_stops_mock_adapter():
    adapter = MockAdapter()
    from jarvis.desktop.controller import DesktopController

    controller = DesktopController(adapter=adapter)
    engine = DesktopAutomationEngine(controller=controller)
    engine.grant("type_text")
    engine.approve("type_text")
    engine.cancel()
    result = engine.run("type_text", {"text": "hello"})
    assert result["status"] == "CANCELLED"
    assert result["executed"] is False


def test_audit_has_no_secret_payload():
    engine = DesktopAutomationEngine(controller=build_test_controller())
    engine.grant("type_text")
    engine.approve("type_text")
    engine.run("type_text", {"text": "password=supersecret"})
    events = engine.audit.list_events()
    assert events
    joined = str(events)
    assert "supersecret" not in joined


def test_unsupported_adapter_fail_closed():
    from jarvis.desktop.platforms.unsupported import UnsupportedAdapter

    adapter = UnsupportedAdapter()
    result = adapter.execute("screenshot", {})
    assert result["ok"] is False
    assert result["status"] == "UNSUPPORTED"
    assert result["executed"] is False
