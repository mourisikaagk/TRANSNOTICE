from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from flask import current_app, g

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def connect(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


@contextmanager
def savepoint(conn: sqlite3.Connection, name: str = "sp"):
    conn.execute(f"SAVEPOINT {name}")
    try:
        yield conn
    except BaseException:
        conn.execute(f"ROLLBACK TO {name}")
        conn.execute(f"RELEASE {name}")
        raise
    else:
        conn.execute(f"RELEASE {name}")


def apply_migrations(conn: sqlite3.Connection) -> list[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    done = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}
    applied: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.stem in done:
            continue
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (path.stem,))
        applied.append(path.stem)
    return applied


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect(current_app.extensions["settings"].database_path)
    return g.db


def close_db(_exc=None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()
