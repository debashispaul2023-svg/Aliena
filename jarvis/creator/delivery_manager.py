"""C9 DeliveryManager: versioned, deterministic ZIP packaging with evidence.

A project is delivered only if every mandatory static check passes and workspace integrity holds. The ZIP
holds tracked project files plus _aliena/{DELIVERY.md,BUILD_REPORT.json,TEST_REPORT.json,MANIFEST.sha256}.
Delivery is a LOCAL file inside the project's control area; exporting it elsewhere needs approval.
Nothing is published or deployed."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from jarvis.core.approval import ApprovalDecision
from jarvis.creator.audit import AuditLogger
from jarvis.creator.security_gate import SecurityGate
from jarvis.creator.spec_utils import slugify
from jarvis.creator.testing_engine import TestManager
from jarvis.creator.workspace_manager import (ApprovalRequired, CollisionError, CreatorWorkspaceError,
                                              CreatorWorkspaceManager, check_relative_path)

META_DIR = "_aliena"
FIXED_DATE = (1980, 1, 1, 0, 0, 0)
LIMITATIONS = [
    "Generated code was NOT executed by Aliena (execution is blocked: no verified OS-level isolation).",
    "Unit/integration/build/runtime/browser tests were not run; only static checks were.",
    "Dependencies were not installed and versions were not verified against any registry.",
    "Scaffolds: review, test and secure the project before relying on it.",
]


class DeliveryRefused(CreatorWorkspaceError):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("delivery refused: " + "; ".join(reasons))
        self.reasons = reasons


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class DeliveryManager:
    def __init__(self, ws: CreatorWorkspaceManager, gate: SecurityGate, audit: Optional[AuditLogger] = None) -> None:
        self.ws, self.gate, self.audit = ws, gate, audit or ws.audit
        self.tests = TestManager(ws, gate, self.audit)

    def package(self, pid: str, actor: str = "delivery") -> dict[str, Any]:
        meta = self.ws.metadata(pid)
        report = self.tests.run(pid, actor="delivery")
        reasons = []
        if not report["completion"]["complete"]:
            reasons += report["completion"]["reasons"]
        tracked = self.ws.manifest(pid)
        if not tracked:
            reasons.append("project has no files")
        if any(k.split("/")[0] == META_DIR for k in tracked):
            reasons.append(f"project uses reserved directory {META_DIR}/")
        if reasons:
            self.audit.record(pid, actor, "delivery", "refused", "; ".join(reasons)[:300])
            raise DeliveryRefused(reasons)

        slug = slugify(meta["name"])
        blobs: dict[str, bytes] = {}
        for key in sorted(tracked):
            check_relative_path(key)
            blobs[f"{slug}/{key}"] = self.ws.read_file(pid, key)
        gens = [self.ws.load_control_record(pid, "generations", n) for n in self.ws.list_control_records(pid, "generations")]
        debugs = [self.ws.load_control_record(pid, "debug", n) for n in self.ws.list_control_records(pid, "debug")]
        untracked = self.ws.verify_integrity(pid)["untracked"]
        build = {
            "project_name": meta["name"], "project_id": pid, "project_type": meta["project_type"],
            "files": [{"path": k, "sha256": tracked[k]["sha256"], "size": tracked[k]["size"]} for k in sorted(tracked)],
            "generations": [{"generation_id": g["generation_id"], "generator": g["template_id"], "kind": g.get("generator_kind", "template"),
                             "version": g["template_version"], "content_digest": g["content_digest"],
                             "support_level": g["support_level"]} for g in gens],
            "debug_runs": [{"errors_before": d["errors_before"], "errors_after": d["errors_after"], "resolved": d["resolved"],
                            "rounds": len(d["rounds"])} for d in debugs],
            "excluded_untracked_files": untracked, "runtime_verified": False, "ai_generated": False,
            "generator": "Aliena Creator Engine",
        }
        pub_report = {k: v for k, v in report.items() if k != "created_at"}
        blobs[f"{slug}/{META_DIR}/BUILD_REPORT.json"] = (json.dumps(build, indent=2, sort_keys=True) + "\n").encode()
        blobs[f"{slug}/{META_DIR}/TEST_REPORT.json"] = (json.dumps(pub_report, indent=2, sort_keys=True) + "\n").encode()
        summary = [f"# Delivery: {meta['name']}", "", f"Status: {report['completion']['status']}", "",
                   f"Files: {len(tracked)}", "", "## Evidence", "",
                   *[f"- {n}: {c['status']}" for n, c in report["categories"].items()], "", "## Limitations", "",
                   *[f"- {x}" for x in LIMITATIONS], ""]
        blobs[f"{slug}/{META_DIR}/DELIVERY.md"] = "\n".join(summary).encode()
        blobs[f"{slug}/{META_DIR}/MANIFEST.sha256"] = "".join(
            f"{_sha(data)}  {name}\n" for name, data in sorted(blobs.items())).encode()

        version = len(self.ws.list_control_records(pid, "delivery")) + 1
        checkpoint = self.ws.create_checkpoint(pid, f"delivery v{version}", actor)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in sorted(blobs):
                zi = zipfile.ZipInfo(name, FIXED_DATE)
                zi.compress_type = zipfile.ZIP_DEFLATED
                zi.external_attr = 0o100644 << 16
                zf.writestr(zi, blobs[name])
        data = buf.getvalue()
        zip_name = f"{slug}-v{version}.zip"
        path = self.ws.write_artifact(pid, "deliveries", zip_name, data, actor=actor)
        record = {"version": version, "zip": path, "zip_sha256": _sha(data), "size": len(data), "file_count": len(tracked),
                  "status": "delivered_static_verified", "runtime_verified": False, "report_status": report["completion"]["status"],
                  "checkpoint": checkpoint, "limitations": LIMITATIONS, "created_at": datetime.now(timezone.utc).isoformat(),
                  "published": False, "deployed": False}
        self.ws.save_control_record(pid, "delivery", f"delivery_{version:04d}", record)
        self.audit.record(pid, actor, "delivery", "ok", f"v{version} {len(tracked)} files sha={record['zip_sha256'][:12]}")
        return record

    def verify_delivery(self, pid: str, version: int) -> dict[str, Any]:
        rec = self.ws.load_control_record(pid, "delivery", f"delivery_{int(version):04d}")
        data = self.ws.read_artifact(pid, "deliveries", Path(rec["zip"]).name)
        problems: dict[str, list[str]] = {"bad_names": [], "mismatch": [], "missing": [], "unexpected": []}
        if _sha(data) != rec["zip_sha256"]:
            problems["mismatch"].append("<zip file hash>")
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            for n in names:
                try:
                    check_relative_path(n)
                except CreatorWorkspaceError:
                    problems["bad_names"].append(n)
            manifest_name = next((n for n in names if n.endswith(f"{META_DIR}/MANIFEST.sha256")), None)
            if manifest_name is None:
                problems["missing"].append("MANIFEST.sha256")
            else:
                listed = {}
                for line in zf.read(manifest_name).decode().splitlines():
                    h, _, n = line.partition("  ")
                    listed[n] = h
                for n, h in listed.items():
                    if n not in names:
                        problems["missing"].append(n)
                    elif _sha(zf.read(n)) != h:
                        problems["mismatch"].append(n)
                problems["unexpected"] = sorted(set(names) - set(listed) - {manifest_name})
        return {"version": rec["version"], "ok": not any(problems.values()), **problems}

    def export(self, pid: str, version: int, dest_dir: str, *, actor: str = "delivery",
               approval: Optional[ApprovalDecision] = None) -> str:
        """Copy a delivery ZIP OUTSIDE the workspace. Requires approval for 'export_delivery'."""
        d = self.gate.check(pid, actor, "export_delivery", approval)
        if not d.allowed:
            raise ApprovalRequired(f"export_delivery: {d.reason}")
        rec = self.ws.load_control_record(pid, "delivery", f"delivery_{int(version):04d}")
        dest = Path(dest_dir).resolve()
        if not dest.is_dir():
            raise CreatorWorkspaceError("destination directory does not exist")
        if self.ws.root == dest or self.ws.root in dest.parents:
            raise CreatorWorkspaceError("destination must be outside the Creator workspace root")
        target = dest / Path(rec["zip"]).name
        if target.exists():
            raise CollisionError("destination file already exists")
        data = self.ws.read_artifact(pid, "deliveries", target.name)
        tmp = dest / f".{target.name}.part"
        with open(tmp, "xb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
        self.audit.record(pid, actor, "export", "ok", target.name)
        return str(target)
