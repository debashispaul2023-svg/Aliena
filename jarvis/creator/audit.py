"""Hash-chained audit logger. Records identifiers/summaries only; text is redacted."""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from jarvis.core.redaction import redact_secrets


class AuditLogger:
    def __init__(self, path: Optional[Path] = None) -> None:
        self._records: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._path = Path(path) if path else None

    def record(self, project_id: str, actor: str, action: str, outcome: str, detail: str = "") -> dict[str, Any]:
        with self._lock:
            prev = self._records[-1]["hash"] if self._records else "0" * 64
            rec = {
                "seq": len(self._records),
                "ts": datetime.now(timezone.utc).isoformat(),
                "project_id": project_id,
                "actor": actor,
                "action": action,
                "outcome": outcome,
                "detail": redact_secrets(str(detail))[:500],
                "prev": prev,
            }
            rec["hash"] = hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest()
            self._records.append(rec)
            if self._path:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec) + "\n")
            return dict(rec)

    def records(self, project_id: Optional[str] = None) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._records if project_id in (None, r["project_id"])]

    def verify_chain(self) -> bool:
        prev = "0" * 64
        for r in self._records:
            body = {k: v for k, v in r.items() if k != "hash"}
            if body["prev"] != prev:
                return False
            if hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest() != r["hash"]:
                return False
            prev = r["hash"]
        return True
