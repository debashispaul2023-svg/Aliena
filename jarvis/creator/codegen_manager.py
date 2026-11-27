"""CodeGenerationManager (C3): template-driven multi-file generation into C2 workspaces.

Pipeline: validate variables -> render in memory -> static syntax validation -> path/collision
preflight -> approval preflight -> checkpoint -> write (C2 atomic writes) -> static dependency
analysis -> reproducibility record. A failure at any write rolls the project back to its
pre-generation state. Nothing generated is ever executed, imported or installed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from jarvis.core.approval import ApprovalDecision
from jarvis.creator.analysis import analyze_dependencies
from jarvis.creator.audit import AuditLogger
from jarvis.creator.composers import ComposerRegistry, default_composers
from jarvis.creator.spec_utils import SpecError
from jarvis.creator.security_gate import SecurityGate
from jarvis.creator.templates import Template, TemplateError, TemplateRegistry, default_registry, render
from jarvis.creator.validators import validate_content
from jarvis.creator.workspace_manager import (ApprovalRequired, CollisionError, CreatorWorkspaceError,
                                              CreatorWorkspaceManager)

_TEXT = re.compile(r"^[A-Za-z0-9 _.,:-]{1,80}$")  # no quotes/backslash/<>/$/braces: safe inside any generated literal
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9 _.-]{0,59}$")
GENERATOR_VERSION = "c3-1"


class GenerationError(CreatorWorkspaceError):
    pass


def derive_variables(variables: dict[str, Any]) -> dict[str, str]:
    if not isinstance(variables, dict):
        raise GenerationError("variables must be a dict")
    unknown = set(variables) - {"project_name", "description"}
    if unknown:
        raise GenerationError(f"unknown variables: {sorted(unknown)}")
    name = str(variables.get("project_name", "")).strip()
    if not _NAME.match(name):
        raise GenerationError("project_name must start with a letter; letters, digits, space, . _ - only (max 60)")
    desc = str(variables.get("description", f"{name} project")).strip()
    if not _TEXT.match(desc):
        raise GenerationError("description contains unsupported characters or is empty/too long")
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    pkg = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not slug or not pkg or not pkg[0].isalpha():
        raise GenerationError("project_name yields an invalid identifier")
    return {"project_name": name, "description": desc, "slug": slug, "pkg": pkg}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _digest(files: dict[str, str]) -> str:
    h = hashlib.sha256()
    for path in sorted(files):
        h.update(f"{path}\0{_sha(files[path].encode('utf-8'))}\n".encode())
    return h.hexdigest()


class CodeGenerationManager:
    def __init__(self, workspaces: CreatorWorkspaceManager, gate: SecurityGate,
                 audit: Optional[AuditLogger] = None, registry: Optional[TemplateRegistry] = None,
                 composers: Optional[ComposerRegistry] = None) -> None:
        self.ws = workspaces
        self.gate = gate
        self.audit = audit or workspaces.audit
        self.registry = registry or default_registry()
        self.composers = composers or default_composers()

    @staticmethod
    def _parents(rel: str) -> list[str]:
        parts = rel.split("/")
        return ["/".join(parts[:i]) for i in range(1, len(parts))]

    def _render(self, tpl: Template, vars_: dict[str, str]) -> dict[str, str]:
        try:
            return {render(p, vars_): render(c, vars_) for p, c in tpl.files.items()}
        except KeyError as exc:
            raise GenerationError(f"template placeholder unresolved: {exc}") from exc

    def generate(self, pid: str, template_id: str, variables: dict[str, Any], *, actor: str = "codegen",
                 regenerate: bool = False, approval: Optional[ApprovalDecision] = None) -> dict[str, Any]:
        d = self.gate.check(pid, actor, "generate_project_files")
        if not d.allowed:
            raise ApprovalRequired(d.reason)
        try:
            tpl = self.registry.get(template_id)
        except TemplateError as exc:
            self.audit.record(pid, actor, "generate", "rejected", str(exc))
            raise GenerationError(str(exc)) from exc
        vars_ = derive_variables(variables)
        files = self._render(tpl, vars_)
        return self._commit(pid, files, actor=actor, regenerate=regenerate, approval=approval,
                            meta={"kind": "template", "id": tpl.template_id, "version": tpl.version,
                                  "support_level": tpl.support_level, "inputs": vars_})

    def compose(self, pid: str, composer_id: str, spec: dict[str, Any], *, actor: str = "codegen",
                regenerate: bool = False, approval: Optional[ApprovalDecision] = None) -> dict[str, Any]:
        d = self.gate.check(pid, actor, "generate_project_files")
        if not d.allowed:
            raise ApprovalRequired(d.reason)
        try:
            comp = self.composers.get(composer_id)
            norm = comp.normalize(spec)
            files = comp.build(norm)
        except (KeyError, SpecError) as exc:
            self.audit.record(pid, actor, "generate", "rejected", str(exc)[:200])
            raise GenerationError(str(exc)) from exc
        return self._commit(pid, files, actor=actor, regenerate=regenerate, approval=approval,
                            meta={"kind": "composer", "id": comp.composer_id, "version": comp.version,
                                  "support_level": comp.support_level, "inputs": norm})

    def _commit(self, pid: str, files: dict[str, str], *, actor: str, regenerate: bool,
                approval: Optional[ApprovalDecision], meta: dict[str, Any]) -> dict[str, Any]:
        vars_ = meta["inputs"]
        # static validation of everything before anything is written
        results = [validate_content(p, c) for p, c in files.items()]
        failed = [r for r in results if not r.ok]
        if failed:
            self.audit.record(pid, actor, "generate", "rejected", f"syntax: {[r.path for r in failed]}")
            raise GenerationError(f"rendered output failed validation: {[(r.path, r.errors) for r in failed]}")

        manifest = self.ws.manifest(pid)
        lowered = {k.lower(): k for k in manifest}
        conflicts, overwrites, unchanged = [], [], []
        for rel, content in files.items():
            target = self.ws.resolve_path(pid, rel, actor)  # PathViolation is audited by C2
            data_sha = _sha(content.encode("utf-8"))
            parent_blocked = next((par for par in self._parents(rel)
                                   if os.path.lexists(self.ws.resolve_path(pid, par, actor))
                                   and not self.ws.resolve_path(pid, par, actor).is_dir()), None)
            if parent_blocked:
                conflicts.append(f"{rel} (parent '{parent_blocked}' is a file)")
            elif lowered.get(rel.lower(), rel) != rel:
                conflicts.append(f"{rel} (case-variant of {lowered[rel.lower()]})")
            elif os.path.lexists(target):
                if target.is_dir():
                    conflicts.append(f"{rel} (directory)")
                elif not regenerate:
                    conflicts.append(rel)
                elif rel in manifest and manifest[rel]["sha256"] == data_sha and target.read_bytes() == content.encode():
                    unchanged.append(rel)
                else:
                    overwrites.append(rel)
        if conflicts:
            self.audit.record(pid, actor, "generate", "collision", f"{len(conflicts)} conflicts")
            raise CollisionError(f"generation would collide with existing paths: {sorted(conflicts)}")
        if overwrites:
            od = self.gate.check(pid, actor, "overwrite_file", approval)
            if not od.allowed:
                self.audit.record(pid, actor, "generate", "denied", "overwrite approval missing")
                raise ApprovalRequired(f"overwrite_file: {od.reason}: {sorted(overwrites)}")

        cid = self.ws.create_checkpoint(pid, f"pre-generate {meta['id']}", actor, skip_missing=True)
        op = uuid.uuid4().hex
        written: list[str] = []
        try:
            for rel in sorted(files):
                if rel in unchanged:
                    continue
                self.ws.write_file(pid, rel, files[rel], actor=actor, overwrite=rel in overwrites,
                                   approval=approval, op=op)
                written.append(rel)
        except Exception as exc:
            discarded = self.ws.discard_created(pid, op, actor=actor)
            try:
                self.ws.rollback(pid, cid, actor=actor)
                state = "rolled back"
            except Exception as rb_exc:  # surfaced, never hidden
                state = f"ROLLBACK FAILED: {rb_exc}"
            self.audit.record(pid, actor, "generate", "failed", f"{type(exc).__name__}; {state}")
            raise GenerationError(f"generation failed ({type(exc).__name__}: {exc}); {state}; "
                                  f"discarded {len(discarded)} new files") from exc

        digest = _digest(files)
        analysis = analyze_dependencies(files)
        gen_hash = _sha(json.dumps([meta["id"], meta["version"], vars_, digest, GENERATOR_VERSION], sort_keys=True).encode())[:16]
        seq = len(self.ws.list_control_records(pid, "generations")) + 1
        record = {
            "generation_id": f"gen_{gen_hash}", "sequence": seq, "project_id": pid,
            "generator_kind": meta["kind"], "template_id": meta["id"], "template_version": meta["version"],
            "support_level": meta["support_level"],
            "generator_version": GENERATOR_VERSION, "variables": vars_, "content_digest": digest,
            "files": [{"path": p, "sha256": _sha(files[p].encode()), "size": len(files[p].encode())}
                      for p in sorted(files)],
            "written": sorted(written), "unchanged": sorted(unchanged), "overwritten": sorted(overwrites),
            "validation": [r.to_dict() for r in results], "dependency_analysis": analysis,
            "unvalidated_files": sorted(r.path for r in results if not r.validated),
            "ai_generated": False, "executed": False, "installed_dependencies": False,
            "regenerated": regenerate, "checkpoint": cid, "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.ws.save_control_record(pid, "generations", f"{seq:04d}_{gen_hash}", record)
        self.audit.record(pid, actor, "generate", "ok", f"{meta['id']} files={len(written)} digest={digest[:12]}")
        return record

    def verify_generation(self, pid: str, record_name: str) -> dict[str, Any]:
        """Re-render from the stored record (reproducibility) and compare with files on disk (drift)."""
        rec = self.ws.load_control_record(pid, "generations", record_name)
        if rec.get("generator_kind") == "composer":
            comp = self.composers.get(rec["template_id"])
            files, version = comp.build(comp.normalize(rec["variables"])), comp.version
        else:
            tpl = self.registry.get(rec["template_id"])
            files, version = self._render(tpl, rec["variables"]), tpl.version
        reproducible = _digest(files) == rec["content_digest"] and version == rec["template_version"]
        drift = []
        for f in rec["files"]:
            try:
                if _sha(self.ws.read_file(pid, f["path"])) != f["sha256"]:
                    drift.append(f["path"])
            except CreatorWorkspaceError:
                drift.append(f["path"])
        return {"reproducible": reproducible, "drift": sorted(drift), "ok": reproducible and not drift}
