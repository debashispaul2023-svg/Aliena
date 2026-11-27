"""Offline, deterministic natural-language -> composer + spec heuristics.

Output is a best-effort draft (flagged as heuristic/mock). Callers may pass an explicit spec instead."""

from __future__ import annotations

import re
from typing import Any

from jarvis.creator.contracts import ProjectType
from jarvis.creator.spec_utils import SpecError, clean_identifier

COMPOSER_FOR = {
    ProjectType.STATIC_WEBSITE: ("composer", "website", {"framework": "html"}),
    ProjectType.REACT_APP: ("composer", "website", {"framework": "react"}),
    ProjectType.NEXTJS_APP: ("composer", "website", {"framework": "nextjs"}),
    ProjectType.FASTAPI_BACKEND: ("composer", "fastapi_service", {}),
    ProjectType.PYTHON_APP: ("composer", "python_software", {}),
    ProjectType.MOBILE_SCAFFOLD: ("composer", "mobile_app", {}),
    ProjectType.GAME_SCAFFOLD: ("composer", "game_collector", {}),
    ProjectType.DATABASE_PROJECT: ("template", "db_schema", {}),
    ProjectType.DOCUMENTATION: ("template", "docs_bundle", {}),
}
UNSUPPORTED_NOTE = {ProjectType.DESKTOP_APP: "no desktop generator exists yet; nothing was generated"}
_SECTIONS = {"about": ("about",), "services": ("service",), "menu": ("menu", "food", "drink"), "gallery": ("gallery", "photo"),
             "testimonials": ("testimonial", "review"), "faq": ("faq", "frequently asked"), "contact": ("contact", "form", "email us")}
_STOP = {"a", "an", "the", "my", "our", "your", "api", "app", "and", "or", "with", "that", "it", "to", "of", "for", "me",
         "all", "some", "new", "simple", "basic", "rest", "restful", "service", "backend", "system", "data", "items", "things"}


def _singular(w: str) -> str:
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if re.search(r"(xes|ches|shes|sses)$", w):
        return w[:-2]
    return w[:-1] if w.endswith("s") and not w.endswith("ss") and len(w) > 3 else w


def project_name_from(request: str, ptype: ProjectType) -> str:
    q = re.search(r"""(?:called|named)\s+["\u201c']([^"'\u201d]{2,40})["\u201d']""", request, re.I)
    if q:
        return re.sub(r"\s+", " ", q.group(1)).strip().title()
    m = re.search(r"""(?:called|named)\s+["']?([A-Za-z0-9][A-Za-z0-9 ._-]{1,40}?)["']?(?:\s+(?:with|that|which|for|using)\b|[.,]|$)""", request, re.I)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip().title()
    m = re.search(r"\bfor (?:my|our|a|an|the)\s+([a-z][a-z ]{1,25}?)(?:\s+(?:with|that|which|where|and|using)\b|[.,]|$)", request, re.I)
    base = m.group(1).strip().title() if m else ""
    suffix = {ProjectType.STATIC_WEBSITE: "Site", ProjectType.REACT_APP: "App", ProjectType.NEXTJS_APP: "App",
              ProjectType.FASTAPI_BACKEND: "API", ProjectType.PYTHON_APP: "Tool", ProjectType.MOBILE_SCAFFOLD: "Mobile",
              ProjectType.GAME_SCAFFOLD: "Game", ProjectType.DATABASE_PROJECT: "DB", ProjectType.DOCUMENTATION: "Docs"}.get(ptype, "Project")
    return f"{base} {suffix}".strip() if base else f"My {suffix}"


def entities_from(request: str) -> list[str]:
    found: list[str] = []
    for m in re.finditer(r"\b(?:manage|track|store|for|of|handle)\s+((?:[a-z]+(?:\s*,\s*|\s+and\s+|\s+)){0,3}[a-z]+)", request.lower()):
        for w in re.split(r"\s*,\s*|\s+and\s+|\s+", m.group(1)):
            w = _singular(w)
            if w and w not in _STOP and w not in found and len(w) > 2:
                found.append(w)
    out = []
    for w in found:
        try:
            out.append(clean_identifier(w, "entity"))
        except SpecError:
            continue
    return out[:3]


def build(request: str, ptype: ProjectType) -> dict[str, Any]:
    """Returns {kind, id, spec|variables, assumptions}. kind: composer|template|unsupported."""
    low = request.lower()
    assumptions = ["spec derived from the request by offline keyword heuristics (not AI): review and edit it"]
    if ptype not in COMPOSER_FOR:
        return {"kind": "unsupported", "id": None, "spec": None,
                "assumptions": assumptions + [UNSUPPORTED_NOTE.get(ptype, "project type not recognised")]}
    kind, cid, extra = COMPOSER_FOR[ptype]
    name = project_name_from(request, ptype)
    if kind == "template":
        return {"kind": kind, "id": cid, "spec": {"project_name": name, "description": f"{name} generated from your request"},
                "assumptions": assumptions}
    if cid == "website":
        secs = [s for s, words in _SECTIONS.items() if any(w in low for w in words)] or ["about", "contact"]
        if "about" not in secs and "contact" not in secs:
            secs.insert(0, "about")
        sections = []
        for s in secs[:7]:
            sec: dict[str, Any] = {"type": s, "title": s.capitalize()}
            if s in ("services", "menu", "gallery", "testimonials", "faq"):
                sec["items"] = [{"title": f"{s.capitalize()} item {i}", "text": "Placeholder text: replace with your content."} for i in (1, 2, 3)]
                assumptions.append(f"'{s}' section contains placeholder items to replace")
            elif s == "about":
                sec["text"] = "Placeholder text: describe who you are."
            sections.append(sec)
        spec = {"site_name": name, "tagline": "", "sections": sections, **extra}
        if extra["framework"] != "html":
            spec["layout"] = "single_page"
        if "api" in low or "backend" in low:
            spec["api"] = {"enabled": True}
        return {"kind": kind, "id": cid, "spec": spec, "assumptions": assumptions}
    if cid == "fastapi_service":
        ents = entities_from(request) or ["item"]
        if ents == ["item"]:
            assumptions.append("no entities recognised: using a generic 'item' entity")
        spec = {"project_name": name, "entities": [{"name": e, "fields": [{"name": "name", "type": "str"},
                                                                         {"name": "notes", "type": "str", "required": False}]} for e in ents]}
        assumptions.append("each entity gets default fields name (required) and notes (optional)")
        return {"kind": kind, "id": cid, "spec": spec, "assumptions": assumptions}
    if cid == "python_software":
        assumptions.append("default commands 'run' and 'info' generated; handlers are starting points")
        return {"kind": kind, "id": cid, "spec": {"project_name": name, "commands": [{"name": "run", "description": "Run the tool"}, {"name": "info", "description": "Show information"}]}, "assumptions": assumptions}
    if cid == "mobile_app":
        assumptions.append("default screens home/items/add generated")
        return {"kind": kind, "id": cid, "spec": {"app_name": name, "screens": [
            {"name": "home", "title": "Home", "kind": "text", "text": "Welcome. Replace this text."},
            {"name": "items", "title": "Items", "kind": "list", "items": [{"title": "First item", "text": "Placeholder"}]},
            {"name": "add", "title": "Add", "kind": "form", "fields": [{"name": "title", "label": "Title"}]}]}, "assumptions": assumptions}
    return {"kind": kind, "id": cid, "spec": {"game_name": name}, "assumptions": assumptions + ["default collector-game settings used"]}
