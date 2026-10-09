"""SQLite history store for SlopCheck."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.environ.get(
    "SLOPCHECK_DB", os.path.expanduser("~/.slopcheck/history.db")
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,          -- 'upload' | 'paste'
    score INTEGER NOT NULL,
    grade TEXT NOT NULL,
    finding_count INTEGER NOT NULL,
    findings_json TEXT NOT NULL,
    code TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_checks_created ON checks(created_at DESC);
"""


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.executescript(SCHEMA)


def save_check(name: str, kind: str, score: int, grade: str,
               findings: list[dict], code: str) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO checks (name, kind, score, grade, finding_count,"
            " findings_json, code, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, kind, score, grade, len(findings),
             json.dumps(findings),
             code[:200_000],  # cap stored code at ~200KB
             datetime.now(timezone.utc).isoformat()),
        )
        return cur.lastrowid


def get_check(check_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM checks WHERE id = ?", (check_id,)).fetchone()
        return dict(row) if row else None


def list_checks(limit: int = 50) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, name, kind, score, grade, finding_count, created_at"
            " FROM checks ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


def stats() -> dict:
    with _conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n, AVG(score) AS avg_score FROM checks"
        ).fetchone()
        return {"total": row["n"] or 0,
                "avg_score": round(row["avg_score"] or 0)}
