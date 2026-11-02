"""Natural-language resource command routing (Phase F).

Parses user phrases (English / Banglish) into acquisition intents.
Does not download unless the intent is find_and_download/alternative
and the acquisition service is invoked. Never installs or executes.
"""

from __future__ import annotations

from pathlib import Path

import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from jarvis.resources.acquisition import (
    AcquisitionPolicy,
    AcquisitionReport,
    AcquisitionRequest,
    INTENT_ALTERNATIVE,
    INTENT_FIND,
    INTENT_FIND_DOWNLOAD,
    INTENT_LOCATE,
    INTENT_VERIFY,
    ResourceAcquisitionService,
)
from jarvis.resources.registry import (
    STATUS_AWAITING_APPROVAL,
    STATUS_DISCOVERED,
    STATUS_FAILED,
    STATUS_REJECTED,
    STATUS_VERIFIED,
)

# Pending approval store for interactive confirm/deny (text UX)
_pending_approval: dict[str, Any] = {}


@dataclass
class ParsedResourceCommand:
    handled: bool
    intent: Optional[str] = None
    need: str = ""
    preferred_url: Optional[str] = None
    resource_id: Optional[str] = None
    project: Optional[str] = None
    filename: Optional[str] = None
    help_text: Optional[str] = None
    list_only: bool = False
    confirm_approval: Optional[bool] = None  # True/False when user answers approval
    ambiguous: bool = False
    clarification: Optional[str] = None


HELP_TEXT = (
    "Resource commands: "
    "find <what>; find and download <what>; download <url>; "
    "locate <name>; verify <name>; list resources; "
    "alternative for <what>. "
    "Downloads go to the local resource library only — "
    "I will not install packages or run files automatically. "
    "When approval is required, reply 'approve download' or 'reject download'."
)


def _contains_any(text: str, phrases: list[str]) -> bool:
    return any(p in text for p in phrases)


def parse_resource_command(query: str) -> ParsedResourceCommand:
    """Return a ParsedResourceCommand. handled=False means not a resource command."""
    q = (query or "").strip()
    if not q:
        return ParsedResourceCommand(handled=False)
    low = q.lower().strip()

    # Approval answers (must come first)
    if low in {
        "approve download",
        "approve",
        "yes download",
        "confirm download",
        "haan download",
        "ha download",
        "ok download",
    } or low.startswith("approve download"):
        return ParsedResourceCommand(handled=True, confirm_approval=True)
    if low in {
        "reject download",
        "deny download",
        "cancel download",
        "no download",
        "na download",
        "reject",
    } or low.startswith("reject download") or low.startswith("deny download"):
        return ParsedResourceCommand(handled=True, confirm_approval=False)

    # Help
    if _contains_any(low, [
        "resource help",
        "help resource",
        "resource commands",
        "resources help",
        "ki resource command",
    ]):
        return ParsedResourceCommand(handled=True, help_text=HELP_TEXT)

    # List
    if _contains_any(low, [
        "list resources",
        "list downloaded",
        "show resources",
        "my resources",
        "downloaded resources",
        "resource list",
        "list my resources",
        "amar resource",
        "download kora resource",
    ]):
        return ParsedResourceCommand(handled=True, list_only=True)

    # Explicit URL download
    url_match = re.search(r"https?://\S+", q)
    preferred_url = url_match.group(0).rstrip(".,)") if url_match else None

    # Find and download / download
    download_phrases = [
        "find and download",
        "find & download",
        "search and download",
        "download and save",
        "download the",
        "download this",
        "download resource",
        "download it",
        "save this resource",
        "download kor",
        "download kore de",
        "download kore dao",
        "khuje download",
        "find and save",
    ]
    if preferred_url and _contains_any(low, ["download", "save this", "save the"]):
        need = re.sub(r"https?://\S+", "", q, flags=re.I).strip() or preferred_url
        return ParsedResourceCommand(
            handled=True,
            intent=INTENT_FIND_DOWNLOAD,
            need=need,
            preferred_url=preferred_url,
        )

    if low in {"download", "download kor"} or _contains_any(low, download_phrases) or (
        low.startswith("download ") and "download music" not in low
        and "download youtube" not in low
    ):
        need = low
        for phr in download_phrases + ["download ", "download"]:
            need = need.replace(phr, " ")
        need = re.sub(r"\s+", " ", need).strip(" .")
        if not need and not preferred_url:
            return ParsedResourceCommand(
                handled=True,
                ambiguous=True,
                clarification="What should I download? Name a package, docs, or give a URL.",
            )
        return ParsedResourceCommand(
            handled=True,
            intent=INTENT_FIND_DOWNLOAD,
            need=need or preferred_url or "",
            preferred_url=preferred_url,
        )

    # Alternative
    if _contains_any(low, [
        "alternative for",
        "alternative to",
        "compatible alternative",
        "replacement for",
        "alternative khuj",
        "onno alternative",
    ]):
        need = low
        for p in [
            "find a compatible alternative for",
            "find alternative for",
            "alternative for",
            "alternative to",
            "replacement for",
            "compatible alternative for",
            "alternative khuje",
            "alternative khuj",
        ]:
            need = need.replace(p, " ")
        need = re.sub(r"\s+", " ", need).strip(" .")
        return ParsedResourceCommand(
            handled=True,
            intent=INTENT_ALTERNATIVE,
            need=need or q,
        )

    # Locate
    if _contains_any(low, [
        "where did you save",
        "where is the file",
        "where is that file",
        "locate resource",
        "locate the",
        "find my downloaded",
        "kothay save",
        "kothay rakhso",
        "where saved",
    ]):
        need = low
        for p in [
            "where did you save",
            "where is the file",
            "where is that file",
            "locate resource",
            "locate the",
            "find my downloaded",
            "kothay save",
            "kothay rakhso",
            "where saved",
        ]:
            need = need.replace(p, " ")
        need = re.sub(r"\s+", " ", need).strip(" .") or q
        return ParsedResourceCommand(handled=True, intent=INTENT_LOCATE, need=need)

    # Verify
    if _contains_any(low, [
        "verify the file",
        "verify resource",
        "verify download",
        "recheck the file",
        "verify that file",
        "integrity check",
        "verify kor",
    ]):
        need = low
        for p in [
            "verify the file",
            "verify resource",
            "verify download",
            "recheck the file",
            "verify that file",
            "integrity check",
            "verify kor",
            "verify ",
        ]:
            need = need.replace(p, " ")
        need = re.sub(r"\s+", " ", need).strip(" .") or q
        return ParsedResourceCommand(handled=True, intent=INTENT_VERIFY, need=need)

    # Find only — careful not to catch "find file" (existing OS command)
    if low.startswith("find file") or "find file " in low:
        return ParsedResourceCommand(handled=False)

    find_phrases = [
        "find the resources",
        "find resources",
        "find resource",
        "search resources",
        "search for resource",
        "find documentation",
        "find the official",
        "find library",
        "find package",
        "find a library",
        "find a package",
        "resource search",
        "khuje ber kor",
        "resource khuj",
    ]
    if _contains_any(low, find_phrases) or low.startswith("find resource"):
        need = low
        for p in find_phrases + ["find ", "search "]:
            need = need.replace(p, " ")
        need = re.sub(r"\s+", " ", need).strip(" .")
        if not need:
            return ParsedResourceCommand(
                handled=True,
                ambiguous=True,
                clarification="What resource should I find?",
            )
        return ParsedResourceCommand(handled=True, intent=INTENT_FIND, need=need)

    return ParsedResourceCommand(handled=False)


def format_report(report: AcquisitionReport) -> str:
    """Human-readable, truthful summary — no false install/integration claims."""
    lines: list[str] = []
    if report.intent == INTENT_FIND:
        lines.append(f"Found {len(report.candidates)} candidate(s) for '{report.need}'.")
        for c in report.candidates[:5]:
            lines.append(
                f"- {c.get('title')} [{c.get('source')}/{c.get('kind')}] {c.get('url')}"
            )
        lines.append("Status: discovered only — nothing was downloaded.")
        return " ".join(lines) if len(lines) == 1 else "\n".join(lines)

    if report.status == STATUS_AWAITING_APPROVAL:
        sel = report.selected or {}
        lines.append("Approval required before download.")
        lines.append(f"Name: {sel.get('title')}")
        lines.append(f"Source: {sel.get('source')}")
        lines.append(f"URL: {sel.get('url')}")
        lines.append(
            "This will only download a file into the local resource library. "
            "It will not install packages or run software."
        )
        lines.append("Reply 'approve download' or 'reject download'.")
        return "\n".join(lines)

    if report.status == STATUS_REJECTED:
        return "Download rejected. Nothing was saved."

    if report.success and report.status == STATUS_VERIFIED:
        lines.append(f"Downloaded and integrity-checked: {report.need}")
        if report.local_path:
            lines.append(f"Local path: {report.local_path}")
        if report.resource:
            if report.resource.size is not None:
                lines.append(f"Size: {report.resource.size} bytes")
            if report.resource.sha256:
                lines.append(f"SHA-256: {report.resource.sha256[:16]}…")
            lines.append(f"Registry ID: {report.resource.id}")
            if report.resource.authenticity_verified:
                lines.append("Authenticity: verified against trusted checksum.")
            else:
                lines.append(
                    "Integrity: local SHA-256 recorded (not an authenticity proof)."
                )
        lines.append("Not installed or executed.")
        return "\n".join(lines)

    if report.intent == INTENT_LOCATE and report.success:
        lines.append(f"Located: {report.resource.title if report.resource else report.need}")
        if report.local_path:
            lines.append(f"Path: {report.local_path}")
        if report.resource:
            lines.append(f"Status: {report.resource.status}")
        return "\n".join(lines)

    if report.intent == INTENT_VERIFY:
        if report.success:
            return f"Verification OK for {report.local_path or report.need}."
        return f"Verification failed: {report.error or report.status}"

    return report.error or f"Resource request ended with status {report.status}."


def list_resources_text(registry, *, limit: int = 15) -> str:
    if registry is None:
        return "Resource registry is not available."
    rows = registry.list(limit=limit)
    if not rows:
        return "No resources registered yet."
    lines = [f"{len(rows)} resource(s):"]
    for r in rows[:limit]:
        path = r.local_path or "(not downloaded)"
        lines.append(f"- [{r.status}] {r.title} → {path}")
    return "\n".join(lines)


class ResourceCommandHandler:
    """Stateful handler for resource NL commands + pending approvals."""

    def __init__(
        self,
        service: Optional[ResourceAcquisitionService] = None,
        *,
        speak: Optional[Callable[[str], None]] = None,
        policy: Optional[AcquisitionPolicy] = None,
    ) -> None:
        self.service = service
        self.speak = speak or (lambda t: None)
        self.policy = policy or AcquisitionPolicy(auto_download_public=False)
        self._pending: Optional[AcquisitionRequest] = None
        self._pending_selected: Optional[dict[str, Any]] = None

    def handle(self, query: str) -> bool:
        """Process query if it is a resource command. Returns True if handled."""
        parsed = parse_resource_command(query)
        if not parsed.handled:
            return False

        if parsed.help_text:
            self.speak(parsed.help_text)
            return True

        if parsed.confirm_approval is not None:
            return self._resolve_approval(parsed.confirm_approval)

        if parsed.list_only:
            reg = getattr(self.service, "registry", None) if self.service else None
            self.speak(list_resources_text(reg))
            return True

        if parsed.ambiguous:
            self.speak(parsed.clarification or "Please clarify the resource request.")
            return True

        if self.service is None:
            self.speak("Resource acquisition service is not available.")
            return True

        req = AcquisitionRequest(
            need=parsed.need,
            intent=parsed.intent or INTENT_FIND,
            preferred_url=parsed.preferred_url,
            resource_id=parsed.resource_id,
            project=parsed.project,
            filename=parsed.filename,
        )

        # Wire approval callback to queue pending instead of hard-fail when possible
        report = self.service.run(req)

        if report.status == STATUS_AWAITING_APPROVAL:
            self._pending = req
            self._pending_selected = report.selected
            self.speak(format_report(report))
            return True

        self.speak(format_report(report))
        return True

    def _resolve_approval(self, approved: bool) -> bool:
        if self._pending is None or self.service is None:
            self.speak("There is no download waiting for approval.")
            return True
        pending = self._pending
        selected = self._pending_selected
        # Clear pending BEFORE running so a concurrent approve cannot double-fire
        self._pending = None
        self._pending_selected = None

        # Bind approval to the exact URL that was presented to the user
        if selected and selected.get("url") and not pending.preferred_url:
            pending.preferred_url = str(selected.get("url"))
            if not pending.filename and selected.get("title"):
                # keep filename safe/simple
                pending.filename = Path(str(selected.get("title"))).name

        expected_url = pending.preferred_url

        def _cb_approve(info: dict) -> bool:
            # Only approve if the URL matches the pending selection
            if expected_url and info.get("url") and info.get("url") != expected_url:
                return False
            return True

        def _cb_reject(info: dict) -> bool:
            return False

        svc = self.service
        old_cb = svc.approval_callback
        old_policy = svc.policy
        try:
            svc.policy = AcquisitionPolicy(
                auto_download_public=False,
                allow_overwrite=old_policy.allow_overwrite,
                max_auto_bytes=old_policy.max_auto_bytes,
            )
            svc.approval_callback = _cb_approve if approved else _cb_reject
            report = svc.run(pending)
        finally:
            svc.approval_callback = old_cb
            svc.policy = old_policy
        self.speak(format_report(report))
        return True
