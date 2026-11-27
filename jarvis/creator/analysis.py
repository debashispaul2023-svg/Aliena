"""Static dependency/import analysis over in-memory files. Never imports or runs code."""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import PurePosixPath

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None

_DIST_MAP = {"yaml": "pyyaml", "PIL": "pillow", "cv2": "opencv-python", "sklearn": "scikit-learn",
             "bs4": "beautifulsoup4", "dotenv": "python-dotenv", "jwt": "pyjwt"}
_NODE_BUILTIN = {"fs", "path", "os", "http", "https", "url", "util", "crypto", "stream", "events",
                 "child_process", "buffer", "assert", "zlib", "net", "tls", "readline", "process"}
_JS_IMPORT = re.compile(r"""(?:import\s+(?:[^'"()]*?\s+from\s+)?|export\s+[^'"()]*?\s+from\s+)['"]([^'"]+)['"]""")
_JS_REQUIRE = re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)""")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _py_declared(files: dict[str, str]) -> set[str]:
    out: set[str] = set()
    for path, text in files.items():
        base = PurePosixPath(path).name
        if re.match(r"^requirements.*\.txt$", base):
            for line in text.splitlines():
                m = re.match(r"^\s*([A-Za-z0-9_.-]+)", line.split("#")[0])
                if m:
                    out.add(_norm(m.group(1)))
        elif base == "pyproject.toml" and tomllib is not None:
            try:
                proj = tomllib.loads(text).get("project", {})
            except Exception:
                continue
            deps = list(proj.get("dependencies", []))
            for extra in proj.get("optional-dependencies", {}).values():
                deps += extra
            for d in deps:
                m = re.match(r"^\s*([A-Za-z0-9_.-]+)", d)
                if m:
                    out.add(_norm(m.group(1)))
    return out


def _js_declared(files: dict[str, str]) -> set[str]:
    out: set[str] = set()
    for path, text in files.items():
        if PurePosixPath(path).name == "package.json":
            try:
                pkg = json.loads(text)
            except ValueError:
                continue
            for k in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                out |= set(pkg.get(k, {}))
    return out


def _js_pkg(spec: str) -> str | None:
    if spec.startswith((".", "/", "@/", "~/", "#")) or spec.startswith("node:"):
        return None
    parts = spec.split("/")
    name = "/".join(parts[:2]) if spec.startswith("@") else parts[0]
    return None if name in _NODE_BUILTIN else name


def analyze_dependencies(files: dict[str, str]) -> dict:
    """Return imports per language, declared deps, and undeclared third-party imports."""
    local_py = set()
    for p in files:
        if p.endswith(".py"):
            parts = PurePosixPath(p).parts
            local_py |= set(parts[:-1]) | {PurePosixPath(p).stem}
    py_imports: set[str] = set()
    js_imports: set[str] = set()
    parse_errors: list[str] = []
    for path, text in files.items():
        if path.endswith(".py"):
            try:
                tree = ast.parse(text)
            except (SyntaxError, ValueError, RecursionError) as e:
                parse_errors.append(f"{path}: {type(e).__name__}")
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    py_imports |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    py_imports.add(node.module.split(".")[0])
        elif path.endswith((".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")):
            for rx in (_JS_IMPORT, _JS_REQUIRE):
                for spec in rx.findall(text):
                    pkg = _js_pkg(spec)
                    if pkg:
                        js_imports.add(pkg)
    third_py = sorted(m for m in py_imports if m not in sys.stdlib_module_names and m not in local_py)
    declared_py, declared_js = _py_declared(files), _js_declared(files)
    undeclared_py = [m for m in third_py if _norm(_DIST_MAP.get(m, m)) not in declared_py]
    undeclared_js = sorted(m for m in js_imports if m not in declared_js)
    return {
        "python": {"third_party_imports": third_py, "declared": sorted(declared_py), "undeclared": undeclared_py},
        "javascript": {"third_party_imports": sorted(js_imports), "declared": sorted(declared_js),
                       "undeclared": undeclared_js},
        "parse_errors": parse_errors,
        "note": "static analysis only; local-module detection is path-based and permissive",
    }
