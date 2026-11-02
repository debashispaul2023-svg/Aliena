"""Human approval gate for irreversible external actions."""

from __future__ import annotations

EXTERNAL_ACTIONS = {
    "submit_proposal",
    "send_message",
    "publish_content",
    "create_listing",
    "make_payment",
    "share_private_file",
}


def requires_approval(action: str) -> bool:
    return action in EXTERNAL_ACTIONS


def approve(store, action: str, target_id: str, user_confirmed: bool) -> bool:
    if not requires_approval(action):
        return True
    store.record_approval(action, target_id, user_confirmed)
    return user_confirmed
