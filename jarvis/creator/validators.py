"""Static syntax validation. Parses/scans text only; generated code is never imported or run.

Levels: "parser" (real parser: python, json, toml, yaml if PyYAML present),
"structural" (heuristic scanner: html, css, js/jsx/ts/tsx, sql, md, yaml fallback),
"none" (extension not validated; reported as validated=False, never as success of validation).
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import PurePosixPath

try:  # tomllib is stdlib on 3.11+
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None
try:
    import yaml as _yaml
except ImportError:
    _yaml = None


@dataclass
class FileValidation:
    path: str
    ok: bool
    level: str
    validated: bool
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"path": self.path, "ok": self.ok, "level": self.level,
                "validated": self.validated, "errors": list(self.errors)}


_PAIRS = {")": "(", "]": "[", "}": "{"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_OPT_END = {"p", "li", "dt", "dd", "tr", "td", "th", "thead", "tbody", "tfoot", "option"}


def _python(text):
    try:
        ast.parse(text)
        return []
    except SyntaxError as e:
        return [f"line {e.lineno}: {e.msg}"]
    except (ValueError, RecursionError, MemoryError) as e:
        return [f"{type(e).__name__}: {e}"]


def _json(text):
    try:
        json.loads(text)
        return []
    except ValueError as e:
        return [str(e)]


def _toml(text):
    if tomllib is None:
        return None
    try:
        tomllib.loads(text)
        return []
    except Exception as e:  # tomllib.TOMLDecodeError
        return [str(e)]


def _balance(text, *, strings=("'", '"'), line_comment=("//",), block=("/*", "*/"), lenient_strings=False,
             template=False):
    """Bracket/string/comment scanner shared by js/css/sql/yaml. Heuristic (no regex-literal support)."""
    n = len(text)
    stack: list[str] = []
    line = 1

    def scan_template(k):
        """Scan template-literal text from k. Returns (next_index, error or None); pushes '${' on interpolation."""
        nonlocal line
        while k < n:
            d = text[k]
            if d == "\\":
                k += 2
                continue
            if d == "\n":
                line += 1
            if d == "`":
                return k + 1, None
            if d == "$" and text.startswith("${", k):
                stack.append("${")
                return k + 2, None
            k += 1
        return n, f"line {line}: unterminated template literal"

    i = 0
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if block and text.startswith(block[0], i):
            j = text.find(block[1], i + 2)
            if j < 0:
                return [f"line {line}: unterminated block comment"]
            line += text.count("\n", i, j)
            i = j + len(block[1])
            continue
        if any(text.startswith(lc, i) for lc in line_comment):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if template and c == "`":
            i, err = scan_template(i + 1)
            if err:
                return [err]
            continue
        if c in strings:
            j = i + 1
            while True:
                if j >= n or text[j] == "\n":
                    if lenient_strings:
                        break
                    return [f"line {line}: unterminated string"]
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == c:
                    j += 1
                    break
                j += 1
            i = max(j, i + 1)
            continue
        if c in "([{":
            stack.append(c)
        elif c in ")]}":
            if c == "}" and stack and stack[-1] == "${":
                stack.pop()
                i, err = scan_template(i + 1)
                if err:
                    return [err]
                continue
            if not stack or stack[-1] != _PAIRS[c]:
                return [f"line {line}: unmatched '{c}'"]
            stack.pop()
        i += 1
    return [f"unclosed '{stack[-1]}'"] if stack else []


def _js(text, path):
    lenient = path.endswith((".jsx", ".tsx"))  # apostrophes in JSX text
    return _balance(text, strings=("'", '"'), template=True, lenient_strings=lenient)


def _css(text):
    return _balance(text, strings=("'", '"'), line_comment=())


def _sql(text):
    errs = _balance(text, strings=("'", '"'), line_comment=("--",))
    stripped = re.sub(r"--[^\n]*", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S)).strip()
    if not errs and stripped and not stripped.endswith(";"):
        errs.append("last statement is not terminated with ';'")
    return errs


class _Html(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in _VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        if tag in self.stack:
            while self.stack and self.stack[-1] != tag:
                top = self.stack.pop()
                if top not in _OPT_END:
                    self.errors.append(f"<{top}> not closed before </{tag}>")
            if self.stack:
                self.stack.pop()
        else:
            self.errors.append(f"unexpected </{tag}>")


def _html(text):
    p = _Html()
    try:
        p.feed(text)
        p.close()
    except Exception as e:
        return [str(e)]
    errs = list(p.errors)
    errs += [f"<{t}> never closed" for t in p.stack if t not in _OPT_END]
    return errs


def _markdown(text):
    fence = None
    for ln, line in enumerate(text.splitlines(), 1):
        m = re.match(r"^\s*(```+|~~~+)", line)
        if m:
            if fence is None:
                fence = (m.group(1)[0], len(m.group(1)))
            elif m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1]:
                fence = None
    return ["unclosed code fence"] if fence else []


def _yaml_check(text):
    if _yaml is not None:
        try:
            list(_yaml.safe_load_all(text))
            return [], "parser"
        except Exception as e:
            return [str(e).splitlines()[0]], "parser"
    errs = []
    for ln, line in enumerate(text.splitlines(), 1):
        if re.match(r"^ *\t", line):
            errs.append(f"line {ln}: tab indentation")
    return errs + _balance(text, strings=("'", '"'), line_comment=("#",), block=None), "structural"


def _svg(text):
    import xml.etree.ElementTree as ET
    low = text.lower()
    if "<!doctype" in low or "<!entity" in low:
        return ["DOCTYPE/ENTITY declarations are not allowed"]
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        return [str(e)]
    if not root.tag.endswith("svg"):
        return ["root element is not <svg>"]
    bad = [el.tag for el in root.iter() if el.tag.split("}")[-1].lower() in ("script", "foreignobject")]
    return [f"disallowed element: {b}" for b in bad]


def validate_content(path: str, content: str) -> FileValidation:
    ext = PurePosixPath(path).suffix.lower()
    if "\x00" in content:
        return FileValidation(path, False, "parser", True, ["NUL byte in text file"])
    if ext == ".py":
        errs, level = _python(content), "parser"
    elif ext == ".json":
        errs, level = _json(content), "parser"
    elif ext == ".toml":
        errs = _toml(content)
        level = "parser"
        if errs is None:
            return FileValidation(path, True, "none", False, ["toml parser unavailable"])
    elif ext in (".yaml", ".yml"):
        errs, level = _yaml_check(content)
    elif ext in (".html", ".htm"):
        errs, level = _html(content), "structural"
    elif ext == ".css":
        errs, level = _css(content), "structural"
    elif ext in (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"):
        errs, level = _js(content, path), "structural"
    elif ext == ".svg":
        errs, level = _svg(content), "parser"
    elif ext == ".sql":
        errs, level = _sql(content), "structural"
    elif ext in (".md", ".markdown"):
        errs, level = _markdown(content), "structural"
    else:
        return FileValidation(path, True, "none", False, [])
    return FileValidation(path, not errs, level, True, errs)
