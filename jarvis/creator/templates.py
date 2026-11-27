"""TemplateRegistry. Templates are static data; a registered template is a SCAFFOLD,
never a claim of full framework support. Registration validates paths, placeholders and syntax."""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, field
from typing import Optional

from jarvis.creator.validators import validate_content
from jarvis.creator.workspace_manager import PathViolation, check_relative_path

ALLOWED_VARS = ("project_name", "description", "slug", "pkg")
SAMPLE_VARS = {"project_name": "Sample Project", "description": "A sample project", "slug": "sample-project",
               "pkg": "sample_project"}
_PLACEHOLDER = re.compile(r"@@\{([A-Za-z_][A-Za-z0-9_]*)\}")
_ID = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
MAX_TEMPLATE_FILES = 60
MAX_TEMPLATE_BYTES = 200_000


class TemplateError(ValueError):
    pass


class _Tpl(string.Template):
    delimiter = "@@"  # avoids clashing with ${...} in JS and $ in shell/SQL


def render(text: str, variables: dict[str, str]) -> str:
    return _Tpl(text).substitute(variables)


@dataclass(frozen=True)
class Template:
    template_id: str
    version: str
    name: str
    project_type: str
    description: str
    files: dict
    notes: str = ""
    support_level: str = "scaffold"  # never "full"


class TemplateRegistry:
    def __init__(self) -> None:
        self._t: dict[str, Template] = {}

    def validate_template(self, t: Template) -> list[str]:
        errs: list[str] = []
        if not _ID.match(t.template_id or ""):
            errs.append("invalid template_id")
        if not t.version:
            errs.append("version required")
        if t.support_level != "scaffold":
            errs.append("support_level must be 'scaffold'")
        if not t.files or len(t.files) > MAX_TEMPLATE_FILES:
            errs.append("file count out of range")
            return errs
        if sum(len(c) for c in t.files.values()) > MAX_TEMPLATE_BYTES:
            errs.append("template too large")
        rendered_paths = set()
        for path, content in t.files.items():
            for text in (path, content):
                bad = set(_PLACEHOLDER.findall(text)) - set(ALLOWED_VARS)
                if bad:
                    errs.append(f"{path}: unknown placeholders {sorted(bad)}")
            try:
                rpath = render(path, SAMPLE_VARS)
                check_relative_path(rpath)
                body = render(content, SAMPLE_VARS)
            except (KeyError, ValueError, PathViolation) as exc:
                errs.append(f"{path}: {exc}")
                continue
            if rpath.lower() in rendered_paths:
                errs.append(f"{path}: duplicate rendered path")
            rendered_paths.add(rpath.lower())
            res = validate_content(rpath, body)
            if not res.ok:
                errs.append(f"{rpath}: syntax {res.errors}")
        return errs

    def register(self, t: Template) -> None:
        errs = self.validate_template(t)
        if errs:
            raise TemplateError("; ".join(errs))
        if t.template_id in self._t:
            raise TemplateError("template already registered")
        self._t[t.template_id] = t

    def get(self, template_id: str) -> Template:
        if template_id not in self._t:
            raise TemplateError(f"unknown template: {template_id}")
        return self._t[template_id]

    def list(self) -> list[dict]:
        return [{"template_id": t.template_id, "version": t.version, "project_type": t.project_type,
                 "support_level": t.support_level, "files": len(t.files)} for t in self._t.values()]

    def for_project_type(self, project_type: str) -> Optional[Template]:
        for t in self._t.values():
            if t.project_type == project_type:
                return t
        return None


def default_registry() -> TemplateRegistry:
    from jarvis.creator.builtin_templates import BUILTIN
    reg = TemplateRegistry()
    for t in BUILTIN:
        reg.register(t)
    return reg
