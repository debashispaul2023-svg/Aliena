"""Stack registry. generator_available is False until a generator AND tests exist."""

from __future__ import annotations

from jarvis.creator.contracts import ProjectType, StackSelection

_STACKS = {
    ProjectType.STATIC_WEBSITE: (["html", "css", "javascript"], [], ["src", "assets", "tests", "docs"]),
    ProjectType.REACT_APP: (["javascript"], ["react"], ["src", "public", "tests", "docs"]),
    ProjectType.NEXTJS_APP: (["javascript"], ["nextjs"], ["app", "public", "tests", "docs"]),
    ProjectType.PYTHON_APP: (["python"], [], ["src", "tests", "docs"]),
    ProjectType.FASTAPI_BACKEND: (["python"], ["fastapi"], ["app", "tests", "docs"]),
    ProjectType.DATABASE_PROJECT: (["python", "sql"], ["sqlite"], ["db", "src", "tests", "docs"]),
    ProjectType.DESKTOP_APP: (["python"], ["tkinter"], ["src", "tests", "docs"]),
    ProjectType.MOBILE_SCAFFOLD: (["javascript"], ["react-native"], ["src", "tests", "docs"]),
    ProjectType.GAME_SCAFFOLD: (["python"], ["pygame"], ["src", "assets", "tests", "docs"]),
    ProjectType.DOCUMENTATION: (["markdown"], [], ["docs"]),
}
# Updated per phase as generators land (C3-C6). Nothing is claimed supported in C1.
IMPLEMENTED_GENERATORS: frozenset = frozenset()

_KEYWORDS = [
    (ProjectType.NEXTJS_APP, ("next.js", "nextjs")),
    (ProjectType.REACT_APP, ("react",)),
    (ProjectType.FASTAPI_BACKEND, ("fastapi", "rest api", "backend", "api service")),
    (ProjectType.MOBILE_SCAFFOLD, ("mobile app", "android", "ios app", "react native")),
    (ProjectType.GAME_SCAFFOLD, ("game", "platformer", "pygame")),
    (ProjectType.DESKTOP_APP, ("desktop app", "desktop software", "tkinter", "gui app")),
    (ProjectType.DATABASE_PROJECT, ("database", "sqlite", "schema")),
    (ProjectType.STATIC_WEBSITE, ("website", "web site", "landing page", "portfolio", "html")),
    (ProjectType.PYTHON_APP, ("python", "script", "cli", "tool", "automation")),
    (ProjectType.DOCUMENTATION, ("documentation", "readme", "docs")),
]


def detect_project_type(text: str) -> ProjectType:
    low = (text or "").lower()
    for ptype, words in _KEYWORDS:
        if any(w in low for w in words):
            return ptype
    return ProjectType.UNKNOWN


def select_stack(ptype: ProjectType) -> StackSelection:
    if ptype not in _STACKS:
        return StackSelection(ptype, [], [], [], False, "project type not recognised")
    langs, fws, folders = _STACKS[ptype]
    return StackSelection(ptype, list(langs), list(fws), list(folders),
                          ptype in IMPLEMENTED_GENERATORS,
                          "keyword-based offline selection (not AI-verified)")
