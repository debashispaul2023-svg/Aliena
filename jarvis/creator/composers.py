"""Composers: deterministic, code-built project generators (dynamic file sets from validated specs)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Composer:
    composer_id: str
    version: str
    project_type: str
    description: str
    normalize: Callable[[dict], dict]
    build: Callable[[dict], dict]
    support_level: str = "scaffold"


class ComposerRegistry:
    def __init__(self) -> None:
        self._c: dict[str, Composer] = {}

    def register(self, c: Composer) -> None:
        if c.support_level != "scaffold":
            raise ValueError("composers are scaffold-level only")
        if c.composer_id in self._c:
            raise ValueError("composer already registered")
        self._c[c.composer_id] = c

    def get(self, composer_id: str) -> Composer:
        if composer_id not in self._c:
            raise KeyError(f"unknown composer: {composer_id}")
        return self._c[composer_id]

    def list(self) -> list[dict]:
        return [{"composer_id": c.composer_id, "version": c.version, "project_type": c.project_type,
                 "support_level": c.support_level} for c in self._c.values()]

    def for_project_type(self, project_type: str):
        return [c for c in self._c.values() if c.project_type == project_type]


def default_composers() -> ComposerRegistry:
    """Static imports only: the Creator package never imports modules dynamically."""
    from jarvis.creator import compose_apps, compose_backend, compose_website

    reg = ComposerRegistry()
    for module in (compose_website, compose_backend, compose_apps):
        for c in module.COMPOSERS:
            reg.register(c)
    return reg
