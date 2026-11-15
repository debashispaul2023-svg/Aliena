"""Part D blocker status tests. These assert honest statuses, not fake success."""

from jarvis.app.blockers import blocker_status


def test_blockers_remain_honest():
    status = blocker_status()
    assert status["D1_phase6f"]["status"] == "BLOCKED"
    assert status["D2_plugin_exec"]["status"] == "BLOCKED"
    assert status["D3_gemini"]["status"] == "UNVERIFIED"
    assert status["D6_notifications"]["verification"] == 0
