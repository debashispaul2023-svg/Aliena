"""Part D blocker status. Records evidence without flipping blocked flags."""

from __future__ import annotations


def blocker_status() -> dict:
    return {
        "D1_phase6f": {"implementation": 40, "verification": 0, "status": "BLOCKED"},
        "D2_plugin_exec": {"implementation": 45, "verification": 0, "status": "BLOCKED"},
        "D3_gemini": {"implementation": 50, "verification": 0, "status": "UNVERIFIED"},
        "D4_audio": {"implementation": 50, "verification": 0, "status": "UNVERIFIED"},
        "D5_desktop": {"implementation": 55, "verification": 0, "status": "UNVERIFIED"},
        "D6_notifications": {"implementation": 60, "verification": 0, "status": "UNVERIFIED"},
        "D7_dns_rebinding": {"implementation": 55, "verification": 0, "status": "UNVERIFIED"},
    }
