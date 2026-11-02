"""Resource acquisition pipeline (Phase E).

Coordinates ResourceFinder → evaluation → approval → DownloadManager →
ResourceRegistry → verification. Does not install packages or execute files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence
from urllib.parse import urlparse

from jarvis.ai.resource_finder import ResourceFinder, ResourceFindResult, ResourceCandidate
from jarvis.resources.downloader import DownloadManager, DownloadResult
from jarvis.resources.registry import (
    ResourceRegistry,
    ResourceRecord,
    STATUS_DISCOVERED,
    STATUS_EVALUATING,
    STATUS_AWAITING_APPROVAL,
    STATUS_DOWNLOADING,
    STATUS_VERIFYING,
    STATUS_VERIFIED,
    STATUS_FAILED,
    STATUS_CANCELLED,
    STATUS_REJECTED,
)

# Intent types
INTENT_FIND = "find"
INTENT_FIND_DOWNLOAD = "find_and_download"
INTENT_VERIFY = "verify"
INTENT_LOCATE = "locate"
INTENT_ALTERNATIVE = "alternative"

ApprovalCallback = Callable[[dict[str, Any]], bool]


@dataclass
class AcquisitionPolicy:
    """Controls which actions may proceed without an interactive approval."""

    auto_download_public: bool = False  # must be explicitly enabled
    max_auto_bytes: int = 5 * 1024 * 1024  # 5 MiB soft gate for auto path
    allow_overwrite: bool = False
    # Restricted actions always need approval (install/exec not implemented here)


@dataclass
class AcquisitionRequest:
    need: str
    intent: str = INTENT_FIND
    project: Optional[str] = None
    preferred_url: Optional[str] = None  # direct URL download when intent allows
    resource_id: Optional[str] = None  # for verify/locate
    category: str = ""
    limit: int = 5
    filename: Optional[str] = None
    expected_sha256: Optional[str] = None
    overwrite: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AcquisitionReport:
    success: bool
    intent: str
    status: str
    need: str
    candidates: list[dict[str, Any]] = field(default_factory=list)
    selected: Optional[dict[str, Any]] = None
    resource: Optional[ResourceRecord] = None
    download: Optional[DownloadResult] = None
    local_path: Optional[str] = None
    error: Optional[str] = None
    approval_required: bool = False
    approval_granted: Optional[bool] = None
    notes: str = ""
    mode: str = "OFFLINE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "intent": self.intent,
            "status": self.status,
            "need": self.need,
            "candidates": self.candidates,
            "selected": self.selected,
            "resource_id": self.resource.id if self.resource else None,
            "resource_status": self.resource.status if self.resource else None,
            "local_path": self.local_path,
            "sha256": self.resource.sha256 if self.resource else None,
            "error": self.error,
            "approval_required": self.approval_required,
            "approval_granted": self.approval_granted,
            "notes": self.notes,
            "mode": self.mode,
            "download_success": self.download.success if self.download else None,
        }


def _candidate_dict(c: ResourceCandidate) -> dict[str, Any]:
    return {
        "title": c.title,
        "url": c.url,
        "description": c.description,
        "source": c.source,
        "kind": c.kind,
        "score": c.score,
        "reasons": list(c.reasons),
        "metadata": dict(c.metadata),
    }


def _is_downloadable_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    # Prefer URLs that look like files, raw content, or known package pages
    path = (parsed.path or "").lower()
    if any(path.endswith(ext) for ext in (
        ".py", ".txt", ".md", ".json", ".csv", ".zip", ".gz", ".tgz",
        ".whl", ".tar", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bin",
        ".yaml", ".yml", ".toml", ".xml", ".html", ".css", ".js",
    )):
        return True
    # Allow direct user-provided preferred URLs even without extension
    return True


class ResourceAcquisitionService:
    """End-to-end resource acquisition without install/exec."""

    def __init__(
        self,
        *,
        finder: Optional[ResourceFinder] = None,
        downloader: Optional[DownloadManager] = None,
        registry: Optional[ResourceRegistry] = None,
        policy: Optional[AcquisitionPolicy] = None,
        approval_callback: Optional[ApprovalCallback] = None,
        resource_root: Optional[str | Path] = None,
    ) -> None:
        self.finder = finder or ResourceFinder()
        if downloader is not None:
            self.downloader = downloader
        else:
            root = Path(resource_root or Path.cwd() / "JarvisResources")
            self.downloader = DownloadManager(root)
        self.registry = registry
        self.policy = policy or AcquisitionPolicy()
        self.approval_callback = approval_callback
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        try:
            self.downloader.cancel()
        except Exception:
            pass

    def run(self, request: AcquisitionRequest) -> AcquisitionReport:
        self._cancelled = False
        intent = (request.intent or INTENT_FIND).lower().strip()
        if intent == INTENT_FIND:
            return self._find_only(request)
        if intent in {INTENT_FIND_DOWNLOAD, INTENT_ALTERNATIVE}:
            return self._find_and_download(request)
        if intent == INTENT_VERIFY:
            return self._verify_existing(request)
        if intent == INTENT_LOCATE:
            return self._locate(request)
        return AcquisitionReport(
            success=False,
            intent=intent,
            status=STATUS_FAILED,
            need=request.need,
            error=f"Unknown intent: {intent}",
        )

    # ------------------------------------------------------------------
    def _find_only(self, request: AcquisitionRequest) -> AcquisitionReport:
        result = self.finder.find(request.need, limit=request.limit)
        candidates = [_candidate_dict(c) for c in result.candidates]
        records: list[ResourceRecord] = []
        if self.registry is not None:
            for c in result.candidates:
                rec = self.registry.register_discovered(
                    title=c.title,
                    url=c.url,
                    source=c.source,
                    kind=c.kind,
                    category=request.category,
                    description=c.description,
                    version=c.metadata.get("version"),
                    license=c.metadata.get("license"),
                    project=request.project,
                    metadata=c.metadata,
                )
                records.append(rec)
        return AcquisitionReport(
            success=result.error is None,
            intent=INTENT_FIND,
            status=STATUS_DISCOVERED if candidates else STATUS_FAILED,
            need=request.need,
            candidates=candidates,
            resource=records[0] if records else None,
            error=result.error or (None if candidates else "No candidates found"),
            notes=result.notes or "Find-only: no download performed",
            mode=result.mode,
        )

    def _locate(self, request: AcquisitionRequest) -> AcquisitionReport:
        if self.registry is None:
            return AcquisitionReport(
                success=False,
                intent=INTENT_LOCATE,
                status=STATUS_FAILED,
                need=request.need,
                error="No registry configured",
            )
        if request.resource_id:
            rec = self.registry.get(request.resource_id)
            hits = [rec] if rec else []
        else:
            hits = self.registry.search(request.need, limit=request.limit)
        if not hits:
            return AcquisitionReport(
                success=False,
                intent=INTENT_LOCATE,
                status=STATUS_FAILED,
                need=request.need,
                error="No registered resource matched",
            )
        rec = hits[0]
        return AcquisitionReport(
            success=True,
            intent=INTENT_LOCATE,
            status=rec.status,
            need=request.need,
            resource=rec,
            local_path=rec.local_path,
            candidates=[
                {
                    "title": r.title,
                    "url": r.canonical_url,
                    "status": r.status,
                    "local_path": r.local_path,
                    "id": r.id,
                }
                for r in hits
            ],
            notes="Locate only",
            mode="OFFLINE",
        )

    def _verify_existing(self, request: AcquisitionRequest) -> AcquisitionReport:
        if self.registry is None:
            return AcquisitionReport(
                success=False,
                intent=INTENT_VERIFY,
                status=STATUS_FAILED,
                need=request.need,
                error="No registry configured",
            )
        rec = None
        if request.resource_id:
            rec = self.registry.get(request.resource_id)
        if rec is None and request.need:
            hits = self.registry.search(request.need, limit=1)
            rec = hits[0] if hits else None
        if rec is None:
            return AcquisitionReport(
                success=False,
                intent=INTENT_VERIFY,
                status=STATUS_FAILED,
                need=request.need,
                error="Resource not found in registry",
            )
        updated = self.registry.recheck(rec.id)
        ok = updated.status == STATUS_VERIFIED and updated.verification_status == "ok"
        return AcquisitionReport(
            success=ok,
            intent=INTENT_VERIFY,
            status=updated.status,
            need=request.need,
            resource=updated,
            local_path=updated.local_path,
            error=updated.error,
            notes="Recheck complete",
            mode="OFFLINE",
        )

    def _find_and_download(self, request: AcquisitionRequest) -> AcquisitionReport:
        # 1) Search (or use preferred URL)
        candidates: list[dict[str, Any]] = []
        mode = "OFFLINE"
        selected: Optional[dict[str, Any]] = None

        if request.preferred_url:
            selected = {
                "title": request.filename or "direct",
                "url": request.preferred_url,
                "source": "user",
                "kind": "other",
                "score": 100.0,
                "reasons": ["preferred_url"],
                "metadata": {},
            }
            candidates = [selected]
            mode = "LIVE"
        else:
            find_result: ResourceFindResult = self.finder.find(
                request.need, limit=request.limit
            )
            mode = find_result.mode
            candidates = [_candidate_dict(c) for c in find_result.candidates]
            if find_result.error and not candidates:
                return AcquisitionReport(
                    success=False,
                    intent=request.intent,
                    status=STATUS_FAILED,
                    need=request.need,
                    candidates=candidates,
                    error=find_result.error,
                    mode=mode,
                )
            if not candidates:
                return AcquisitionReport(
                    success=False,
                    intent=request.intent,
                    status=STATUS_FAILED,
                    need=request.need,
                    error="No candidates found",
                    mode=mode,
                )
            selected = candidates[0]

        assert selected is not None
        url = str(selected.get("url") or "")
        if not _is_downloadable_url(url):
            return AcquisitionReport(
                success=False,
                intent=request.intent,
                status=STATUS_FAILED,
                need=request.need,
                candidates=candidates,
                selected=selected,
                error="Selected candidate has no downloadable HTTP(S) URL",
                mode=mode,
            )

        # Register discovered
        rec: Optional[ResourceRecord] = None
        if self.registry is not None:
            rec = self.registry.register_discovered(
                title=str(selected.get("title") or url),
                url=url,
                source=str(selected.get("source") or ""),
                kind=str(selected.get("kind") or "unknown"),
                category=request.category,
                description=str(selected.get("description") or ""),
                version=(selected.get("metadata") or {}).get("version"),
                license=(selected.get("metadata") or {}).get("license"),
                project=request.project,
                metadata=selected.get("metadata") or {},
            )
            try:
                self.registry.update_status(rec.id, STATUS_EVALUATING)
                rec = self.registry.get(rec.id)
            except Exception:
                pass

        if self._cancelled:
            return self._cancelled_report(request, candidates, selected, rec, mode)

        # Approval gate
        needs_approval = self._needs_approval(request, selected)
        approval_granted: Optional[bool] = None
        if needs_approval:
            if self.registry and rec:
                try:
                    self.registry.update_status(rec.id, STATUS_AWAITING_APPROVAL)
                    rec = self.registry.get(rec.id)
                except Exception:
                    pass
            if self.approval_callback is None:
                return AcquisitionReport(
                    success=False,
                    intent=request.intent,
                    status=STATUS_AWAITING_APPROVAL,
                    need=request.need,
                    candidates=candidates,
                    selected=selected,
                    resource=rec,
                    approval_required=True,
                    approval_granted=None,
                    error="Approval required but no approval_callback configured",
                    mode=mode,
                    notes="Restricted action blocked pending approval",
                )
            decision = bool(
                self.approval_callback(
                    {
                        "action": "download",
                        "url": url,
                        "title": selected.get("title"),
                        "need": request.need,
                        "overwrite": request.overwrite,
                    }
                )
            )
            approval_granted = decision
            if not decision:
                if self.registry and rec:
                    try:
                        self.registry.update_status(rec.id, STATUS_REJECTED, error="Approval denied")
                        rec = self.registry.get(rec.id)
                    except Exception:
                        pass
                return AcquisitionReport(
                    success=False,
                    intent=request.intent,
                    status=STATUS_REJECTED,
                    need=request.need,
                    candidates=candidates,
                    selected=selected,
                    resource=rec,
                    approval_required=True,
                    approval_granted=False,
                    error="Approval denied",
                    mode=mode,
                )

        if self._cancelled:
            return self._cancelled_report(request, candidates, selected, rec, mode)

        # Download
        if self.registry and rec:
            try:
                self.registry.update_status(rec.id, STATUS_DOWNLOADING)
                rec = self.registry.get(rec.id)
            except Exception:
                pass

        filename = request.filename
        if not filename:
            path_name = Path(urlparse(url).path).name
            filename = path_name or "download.bin"

        subdir = ""
        if request.project:
            # keep project name relative/safe
            safe_proj = re.sub(r"[^\w.\-]+", "_", request.project)[:80]
            subdir = f"projects/{safe_proj}"

        dl = self.downloader.download(
            url,
            filename=filename,
            subdir=subdir,
            expected_sha256=request.expected_sha256,
            overwrite=request.overwrite and (
                self.policy.allow_overwrite or (approval_granted is True)
            ),
        )

        if self.registry is not None:
            rec = self.registry.register_download(
                dl,
                title=str(selected.get("title") or filename),
                source=str(selected.get("source") or ""),
                kind=str(selected.get("kind") or "unknown"),
                category=request.category,
                project=request.project,
                expected_sha256=request.expected_sha256,
                resource_id=rec.id if rec else None,
            )
        else:
            # No registry — still report download outcome
            if not dl.success:
                return AcquisitionReport(
                    success=False,
                    intent=request.intent,
                    status=STATUS_CANCELLED if dl.cancelled else STATUS_FAILED,
                    need=request.need,
                    candidates=candidates,
                    selected=selected,
                    download=dl,
                    error=dl.error,
                    approval_required=needs_approval,
                    approval_granted=approval_granted,
                    mode=mode,
                )
            return AcquisitionReport(
                success=True,
                intent=request.intent,
                status=STATUS_VERIFIED,
                need=request.need,
                candidates=candidates,
                selected=selected,
                download=dl,
                local_path=dl.path,
                approval_required=needs_approval,
                approval_granted=approval_granted,
                mode=mode,
                notes="Downloaded without registry",
            )

        assert rec is not None
        ok = dl.success and rec.status == STATUS_VERIFIED
        return AcquisitionReport(
            success=ok,
            intent=request.intent,
            status=rec.status,
            need=request.need,
            candidates=candidates,
            selected=selected,
            resource=rec,
            download=dl,
            local_path=rec.local_path,
            error=None if ok else (dl.error or rec.error or "Acquisition failed"),
            approval_required=needs_approval,
            approval_granted=approval_granted,
            mode=mode,
            notes="Find-and-download complete" if ok else "Find-and-download failed",
        )

    def _needs_approval(
        self, request: AcquisitionRequest, selected: dict[str, Any]
    ) -> bool:
        # Overwrite always restricted
        if request.overwrite and not self.policy.allow_overwrite:
            return True
        # Auto-download disabled → require approval for any download
        if not self.policy.auto_download_public:
            return True
        # Large files (when size known in metadata) need approval
        meta = selected.get("metadata") or {}
        size = meta.get("size")
        if isinstance(size, int) and size > self.policy.max_auto_bytes:
            return True
        return False

    def _cancelled_report(
        self,
        request: AcquisitionRequest,
        candidates: list,
        selected: Optional[dict],
        rec: Optional[ResourceRecord],
        mode: str,
    ) -> AcquisitionReport:
        if self.registry and rec:
            try:
                self.registry.update_status(rec.id, STATUS_CANCELLED, error="Cancelled", force=True)
                rec = self.registry.get(rec.id)
            except Exception:
                pass
        return AcquisitionReport(
            success=False,
            intent=request.intent,
            status=STATUS_CANCELLED,
            need=request.need,
            candidates=candidates,
            selected=selected,
            resource=rec,
            error="Cancelled",
            mode=mode,
        )
