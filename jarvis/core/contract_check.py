"""Integration contract checker (Part A tool; standard library only; never imports the code it scans).

Two jobs, both used for Phase 7 / handover:

1. ``check_part_b_imports(root)``: AST-scan the Part B packages under ``root`` and verify
   that every ``jarvis.<part A module>`` name they import actually exists in Part A.
2. ``changed_files(baseline_root, candidate_root)``: hash-compare two trees and group the
   differences by owner (per ``ALIENA_FILE_OWNERSHIP.md``) so cross-owner edits are visible.

Run:  python -m jarvis.core.contract_check imports <root>
      python -m jarvis.core.contract_check diff <baseline_root> <candidate_root>
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

PART_A = ("config.py", "logger.py", "core", "memory", "ai", "dev", "skills")
PART_B = ("resources", "voice", "desktop", "research", "productivity", "plugins", "freelancer")
SHARED_FILES = {
    "ROADMAP.md", "IMPLEMENTATION_STATUS.md", "ARCHITECTURE.md", "SECURITY.md",
    "KNOWN_LIMITATIONS.md", "DEFERRED_TESTING.md", "CHANGELOG.md", "jarvis/dev/phase6_status.json",
}
UNASSIGNED = ("app", "adapt", "integrations")
PROTECTED_DBS = {"jarvis_memory.db", "jarvis_resources.db", "jarvis_skills.db"}
_SKIP_DIRS = {"__pycache__", ".pytest_cache"}


def owner_of(rel: str) -> str:
    """Owner of a project-relative POSIX path: part_a | part_b | shared | unassigned | other."""
    rel = rel.replace("\\", "/").lstrip("./")
    if rel in SHARED_FILES:
        return "shared"
    if rel.startswith("jarvis/tests/"):
        name = rel.rsplit("/", 1)[-1]
        # tests follow the module they test (convention in this code base)
        for b in PART_B:
            if b in name:
                return "part_b"
        for stem in ("feature6", "feature7", "feature8", "feature9", "feature10", "freelancer", "downloader",
                     "resource_", "acquisition", "tts_"):
            if stem in name:
                return "part_b"
        return "part_a"
    parts = rel.split("/")
    if parts[0] == "jarvis" and len(parts) >= 2:
        top = parts[1]
        if top in ("config.py", "logger.py") or top in ("core", "memory", "ai", "dev", "skills"):
            return "part_a"
        if top in PART_B:
            return "part_b"
        if top in UNASSIGNED:
            return "unassigned"
    return "other"


def _iter_py(root: Path, subdirs: Iterable[str]) -> Iterable[Path]:
    for sub in subdirs:
        base = root / "jarvis" / sub
        if base.is_file():
            yield base
            continue
        for p in sorted(base.rglob("*.py")) if base.exists() else []:
            if not (_SKIP_DIRS & set(p.parts)):
                yield p


def _top_level_names(path: Path) -> set[str]:
    """Names a module defines or re-exports at top level (no import executed)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        names.add(n.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[0])
    return names


def _resolve_module(root: Path, dotted: str) -> Optional[Path]:
    parts = dotted.split(".")
    base = root.joinpath(*parts)
    if base.with_suffix(".py").exists():
        return base.with_suffix(".py")
    if (base / "__init__.py").exists():
        return base / "__init__.py"
    return None


def _is_part_a_module(dotted: str) -> bool:
    parts = dotted.split(".")
    if len(parts) < 2 or parts[0] != "jarvis":
        return False
    return parts[1] in ("config", "logger", "core", "memory", "ai", "dev", "skills")


def _absolute(module: Optional[str], level: int, file_rel: str) -> Optional[str]:
    if level == 0:
        return module
    pkg = file_rel[:-3].split("/")[:-1]  # directory of the importing file as a package path
    if level - 1 > len(pkg):
        return None
    base = pkg[: len(pkg) - (level - 1)]
    return ".".join(base + ([module] if module else []))


def check_part_b_imports(root: str | Path) -> dict[str, Any]:
    """Verify every Part A import made by Part B source files (tests excluded)."""
    root = Path(root).resolve()
    imports: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for path in _iter_py(root, PART_B):
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            missing.append({"file": rel, "problem": f"syntax error: {exc.msg}"})
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = _absolute(node.module, node.level, rel)
                if not mod or not _is_part_a_module(mod):
                    continue
                target = _resolve_module(root, mod)
                for alias in node.names:
                    rec = {"file": rel, "module": mod, "name": alias.name}
                    imports.append(rec)
                    if target is None:
                        missing.append({**rec, "problem": "module not found"})
                        continue
                    if alias.name == "*":
                        continue
                    sub = _resolve_module(root, f"{mod}.{alias.name}")  # `from pkg import submodule`
                    if alias.name not in _top_level_names(target) and sub is None:
                        missing.append({**rec, "problem": "name not defined in module"})
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_part_a_module(alias.name):
                        rec = {"file": rel, "module": alias.name, "name": None}
                        imports.append(rec)
                        if _resolve_module(root, alias.name) is None:
                            missing.append({**rec, "problem": "module not found"})
    return {
        "status": "COMPATIBLE" if not missing else "INCOMPATIBLE",
        "part_a_imports_found": len(imports),
        "imports": imports,
        "problems": missing,
    }


def _hash_tree(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and not (_SKIP_DIRS & set(p.parts)) and p.suffix != ".pyc":
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def changed_files(baseline_root: str | Path, candidate_root: str | Path) -> dict[str, Any]:
    """Differences between two trees, grouped by owner. Protected DB changes are flagged."""
    a, b = _hash_tree(Path(baseline_root)), _hash_tree(Path(candidate_root))
    added = sorted(set(b) - set(a))
    removed = sorted(set(a) - set(b))
    modified = sorted(k for k in set(a) & set(b) if a[k] != b[k])
    by_owner: dict[str, dict[str, list[str]]] = {}
    for kind, items in (("added", added), ("modified", modified), ("removed", removed)):
        for rel in items:
            by_owner.setdefault(owner_of(rel), {"added": [], "modified": [], "removed": []})[kind].append(rel)
    protected = sorted(r for r in modified + removed if r in PROTECTED_DBS)
    return {
        "added": added, "modified": modified, "removed": removed,
        "by_owner": by_owner, "protected_db_changes": protected,
        "counts": {"added": len(added), "modified": len(modified), "removed": len(removed)},
    }


def _main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[1] == "imports":
        rep = check_part_b_imports(argv[2])
        print(json.dumps(rep, indent=2))
        return 0 if rep["status"] == "COMPATIBLE" else 1
    if len(argv) >= 4 and argv[1] == "diff":
        print(json.dumps(changed_files(argv[2], argv[3]), indent=2))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
