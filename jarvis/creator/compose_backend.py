"""C5 backend composer: FastAPI + SQLite CRUD service from validated entity definitions.

Generated SQL uses parameter binding for all values; table/column names are validated identifiers that are
also double-quoted. Nothing is executed or installed by the composer."""

from __future__ import annotations

from jarvis.creator.composers import Composer
from jarvis.creator.spec_utils import (SpecError, clean_identifier, clean_list, clean_text, pyname,
                                       reject_unknown, slugify)

FIELD_TYPES = {"str": ("str", "TEXT", "'sample'", "'changed'"), "int": ("int", "INTEGER", "1", "2"),
               "float": ("float", "REAL", "1.5", "2.5"), "bool": ("bool", "INTEGER", "True", "False")}
_SQL_RESERVED = {"order", "group", "table", "select", "insert", "update", "delete", "from", "where", "index",
                 "key", "primary", "values", "default", "check", "create", "drop", "alter", "join", "limit",
                 "offset", "union", "column", "constraint", "foreign", "references", "unique", "having",
                 "between", "exists", "case", "when", "then", "end", "null", "like", "into", "set", "view",
                 "trigger", "transaction", "rowid"}


def _plural(name: str) -> str:
    if name.endswith("s"):
        return name + "es"
    if name.endswith("y") and len(name) > 1 and name[-2] not in "aeiou":
        return name[:-1] + "ies"
    return name + "s"


def _camel(name: str) -> str:
    return "".join(w.capitalize() for w in name.split("_"))


def normalize(spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise SpecError("spec must be a dict")
    reject_unknown(spec, {"project_name", "description", "entities"})
    name = clean_text(spec.get("project_name"), "project_name", maxlen=60)
    ents, names, tables = [], set(), set()
    for e in clean_list(spec.get("entities"), "entities", max_items=6, min_items=1):
        if not isinstance(e, dict):
            raise SpecError("each entity must be a dict")
        reject_unknown(e, {"name", "fields", "table", "klass"}, "entity")  # table/klass: derived, recomputed (idempotent)
        en = clean_identifier(e.get("name"), "entity.name")
        if en in _SQL_RESERVED:
            raise SpecError(f"entity name '{en}' is an SQL reserved word")
        table = _plural(en)
        if en in names or table in tables:
            raise SpecError(f"duplicate entity: {en}")
        names.add(en)
        tables.add(table)
        fields, fnames = [], set()
        for f in clean_list(e.get("fields"), "fields", max_items=12, min_items=1):
            if not isinstance(f, dict):
                raise SpecError("each field must be a dict")
            reject_unknown(f, {"name", "type", "required"}, "field")
            fn = clean_identifier(f.get("name"), "field.name")
            if fn in _SQL_RESERVED or fn in fnames:
                raise SpecError(f"invalid or duplicate field name: {fn}")
            ft = f.get("type", "str")
            if ft not in FIELD_TYPES:
                raise SpecError(f"field type must be one of {sorted(FIELD_TYPES)}")
            fnames.add(fn)
            fields.append({"name": fn, "type": ft, "required": bool(f.get("required", True))})
        ents.append({"name": en, "table": table, "klass": _camel(en), "fields": fields})
    return {"project_name": name, "description": clean_text(spec.get("description", f"{name} API"), "description"),
            "entities": ents}


_CONFIG = '''import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str
    database_path: str


def load_settings() -> Settings:
    """Read settings from the environment on every call (see env.example)."""
    return Settings(
        app_name=os.environ.get("APP_NAME", __DEFAULT_NAME__),
        database_path=os.environ.get("DATABASE_PATH", "app.db"),
    )
'''

_DATABASE = '''import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.config import load_settings

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


@contextmanager
def get_connection():
    conn = sqlite3.connect(load_settings().database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
'''

_REPOSITORY = '''class Repository:
    """Parameterised CRUD for one table. Table/column names are constants from the generator."""

    def __init__(self, table, columns, bool_columns=()):
        self.table = table
        self.columns = tuple(columns)
        self.bool_columns = set(bool_columns)

    def _row(self, row):
        data = dict(row)
        for col in self.bool_columns:
            if data.get(col) is not None:
                data[col] = bool(data[col])
        return data

    def list(self, conn, limit=100, offset=0):
        rows = conn.execute(
            f'SELECT * FROM "{self.table}" ORDER BY id LIMIT ? OFFSET ?', (limit, offset)
        ).fetchall()
        return [self._row(r) for r in rows]

    def get(self, conn, item_id):
        row = conn.execute(f'SELECT * FROM "{self.table}" WHERE id = ?', (item_id,)).fetchone()
        return self._row(row) if row else None

    def create(self, conn, data):
        cols = [c for c in self.columns if c in data]
        names = ", ".join(f'"{c}"' for c in cols)
        marks = ", ".join("?" for _ in cols)
        cur = conn.execute(
            f'INSERT INTO "{self.table}" ({names}) VALUES ({marks})', [data[c] for c in cols]
        )
        return self.get(conn, cur.lastrowid)

    def update(self, conn, item_id, data):
        cols = [c for c in self.columns if c in data]
        if cols:
            sets = ", ".join(f'"{c}" = ?' for c in cols)
            conn.execute(
                f'UPDATE "{self.table}" SET {sets} WHERE id = ?', [data[c] for c in cols] + [item_id]
            )
        return self.get(conn, item_id)

    def delete(self, conn, item_id):
        cur = conn.execute(f'DELETE FROM "{self.table}" WHERE id = ?', (item_id,))
        return cur.rowcount > 0
'''


def _schemas(s: dict) -> str:
    out = ["from typing import Optional\n\nfrom pydantic import BaseModel\n"]
    for e in s["entities"]:
        k = e["klass"]
        base, upd = [], []
        for f in e["fields"]:
            t = FIELD_TYPES[f["type"]][0]
            base.append(f"    {f['name']}: {t}" if f["required"] else f"    {f['name']}: Optional[{t}] = None")
            upd.append(f"    {f['name']}: Optional[{t}] = None")
        out.append(f"\n\nclass {k}Base(BaseModel):\n" + "\n".join(base) +
                   f"\n\n\nclass {k}Create({k}Base):\n    pass\n\n\nclass {k}Update(BaseModel):\n" + "\n".join(upd) +
                   f"\n\n\nclass {k}Out({k}Base):\n    id: int\n")
    return "".join(out)


def _router(e: dict) -> str:
    k, t = e["klass"], e["table"]
    cols = tuple(f["name"] for f in e["fields"])
    bools = tuple(f["name"] for f in e["fields"] if f["type"] == "bool")
    return f'''from fastapi import APIRouter, HTTPException, Response

from app.database import get_connection
from app.repository import Repository
from app.schemas import {k}Create, {k}Out, {k}Update

router = APIRouter(prefix="/{t}", tags=["{t}"])
repo = Repository({t!r}, {cols!r}, {bools!r})


@router.get("", response_model=list[{k}Out])
def list_items(limit: int = 100, offset: int = 0):
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    with get_connection() as conn:
        return repo.list(conn, limit, offset)


@router.post("", response_model={k}Out, status_code=201)
def create_item(payload: {k}Create):
    with get_connection() as conn:
        return repo.create(conn, payload.model_dump())


@router.get("/{{item_id}}", response_model={k}Out)
def get_item(item_id: int):
    with get_connection() as conn:
        item = repo.get(conn, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="not found")
    return item


@router.patch("/{{item_id}}", response_model={k}Out)
def update_item(item_id: int, payload: {k}Update):
    with get_connection() as conn:
        if repo.get(conn, item_id) is None:
            raise HTTPException(status_code=404, detail="not found")
        return repo.update(conn, item_id, payload.model_dump(exclude_unset=True))


@router.delete("/{{item_id}}", status_code=204)
def delete_item(item_id: int):
    with get_connection() as conn:
        if not repo.delete(conn, item_id):
            raise HTTPException(status_code=404, detail="not found")
    return Response(status_code=204)
'''


def _schema_sql(s: dict) -> str:
    out = [f"-- DRAFT schema for {s['project_name']}. Review before applying to real data.\n"]
    for e in s["entities"]:
        cols = ["  id INTEGER PRIMARY KEY AUTOINCREMENT"]
        for f in e["fields"]:
            sql = FIELD_TYPES[f["type"]][1]
            cols.append(f'  "{f["name"]}" {sql}' + (" NOT NULL" if f["required"] else ""))
        out.append(f'\nCREATE TABLE IF NOT EXISTS "{e["table"]}" (\n' + ",\n".join(cols) + "\n);\n")
    return "".join(out)


def _sample(e: dict, alt: bool = False) -> dict:
    return {f["name"]: eval_sample(f["type"], alt) for f in e["fields"]}


def eval_sample(ftype: str, alt: bool):
    return {"str": "changed" if alt else "sample", "int": 2 if alt else 1, "float": 2.5 if alt else 1.5,
            "bool": False if alt else True}[ftype]


def _tests(s: dict) -> str:
    out = ['"""API tests (pytest). Run by you after installing dependencies; never run by Aliena."""\n']
    for e in s["entities"]:
        t, req = e["table"], [f for f in e["fields"] if f["required"]]
        first = e["fields"][0]["name"]
        out.append(f'''

def test_{e["name"]}_crud(client):
    payload = {_sample(e)!r}
    created = client.post("/{t}", json=payload)
    assert created.status_code == 201
    item = created.json()
    assert item["id"] >= 1
    assert item["{first}"] == payload["{first}"]
    assert client.get("/{t}/" + str(item["id"])).json() == item
    assert any(row["id"] == item["id"] for row in client.get("/{t}").json())
    changed = client.patch("/{t}/" + str(item["id"]), json={{"{first}": {eval_sample(e["fields"][0]["type"], True)!r}}})
    assert changed.status_code == 200
    assert changed.json()["{first}"] == {eval_sample(e["fields"][0]["type"], True)!r}
    assert client.delete("/{t}/" + str(item["id"])).status_code == 204
    assert client.get("/{t}/" + str(item["id"])).status_code == 404


def test_{e["name"]}_not_found(client):
    assert client.get("/{t}/999999").status_code == 404
    assert client.delete("/{t}/999999").status_code == 404
''')
        if req:
            out.append(f'''

def test_{e["name"]}_validation(client):
    assert client.post("/{t}", json={{}}).status_code == 422
''')
    return "".join(out)


_CONFTEST = '''import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="api_tests_")
os.environ["DATABASE_PATH"] = os.path.join(_TMP, "test.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client
'''


def build(s: dict) -> dict[str, str]:
    files = {
        "requirements.txt": "fastapi>=0.110\npydantic>=2.0\nuvicorn>=0.29\nhttpx>=0.27\npytest>=8.0\n",
        "env.example": f"# Copy to .env (never commit real secrets)\nAPP_NAME={slugify(s['project_name'])}\nDATABASE_PATH=app.db\n",
        ".gitignore": ".env\n*.db\n__pycache__/\n.pytest_cache/\n",
        "app/__init__.py": "",
        "app/config.py": _CONFIG.replace("__DEFAULT_NAME__", repr(s["project_name"])),
        "app/database.py": _DATABASE,
        "app/repository.py": _REPOSITORY,
        "app/schemas.py": _schemas(s),
        "app/routers/__init__.py": "",
        "db/schema.sql": _schema_sql(s),
        "db/migrations/0001_initial.up.sql": _schema_sql(s),
        "db/migrations/0001_initial.down.sql": "-- DRAFT down migration\n" + "".join(
            f'DROP TABLE IF EXISTS "{e["table"]}";\n' for e in reversed(s["entities"])),
        "tests/__init__.py": "",
        "tests/conftest.py": _CONFTEST,
        "tests/test_api.py": _tests(s),
    }
    imports = "".join(f"from app.routers import {e['name']} as {e['name']}_router\n" for e in s["entities"])
    includes = "".join(f"app.include_router({e['name']}_router.router)\n" for e in s["entities"])
    files["app/main.py"] = f'''from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import load_settings
from app.database import init_db
{imports}

@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


app = FastAPI(title=load_settings().app_name, lifespan=lifespan)
{includes}

@app.get("/health")
def health():
    return {{"status": "ok"}}
'''
    for e in s["entities"]:
        files[f"app/routers/{e['name']}.py"] = _router(e)
    endpoints = "\n".join(
        f"- `GET/POST /{e['table']}`, `GET/PATCH/DELETE /{e['table']}/{{id}}` ({e['klass']}: "
        + ", ".join(f"{f['name']}:{f['type']}" for f in e["fields"]) + ")" for e in s["entities"])
    files["docs/API.md"] = f"# API: {s['project_name']}\n\n{s['description']}\n\n## Endpoints\n\n- `GET /health`\n{endpoints}\n\nNo authentication is generated: add it before exposing this service.\n"
    files["README.md"] = (f"# {s['project_name']}\n\n{s['description']}\n\nFastAPI + SQLite scaffold generated by Aliena Creator. "
                          "Dependencies are not installed. Run it yourself: `pip install -r requirements.txt`, "
                          "`uvicorn app.main:app`. Tests: `pytest`. No auth; review before deploying.\n")
    return files


COMPOSERS = [Composer("fastapi_service", "1.0.0", "fastapi_backend", "FastAPI + SQLite CRUD service", normalize, build)]
