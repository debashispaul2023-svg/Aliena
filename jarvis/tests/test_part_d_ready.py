"""Later-PC readiness checks. Does not claim live verification."""

from jarvis.desktop.drivers import MockDesktopDriver
from jarvis.resources.rebinding import allow_connect
from jarvis.voice.devices import probe_audio


def test_mock_desktop_not_real():
    result = MockDesktopDriver().move(10, 10, approved=True)
    assert result.executed is False
    assert result.status == "MOCK_ONLY"


def test_private_ip_blocked():
    assert allow_connect("example.com", "10.0.0.5")["status"] == "BLOCKED"
    assert allow_connect("example.com", "1.1.1.1", prior_ip="8.8.8.8")["status"] == "BLOCKED"


def test_audio_probe_honest():
    probe = probe_audio()
    assert probe["status"] == "UNVERIFIED"
