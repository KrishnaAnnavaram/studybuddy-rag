"""SQLite persistence: schema, migrations and low-level row access.

Application code should not call the ``_``-prefixed row helpers directly with an arbitrary user id;
it goes through ``auth.AuthService`` and ``analytics`` which scope every read to the logged-in user.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('student', 'instructor')),
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS courses (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL UNIQUE,
    subject  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS grades (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id  INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    grade      TEXT NOT NULL CHECK (grade IN ('A', 'B', 'C', 'D', 'F')),
    PRIMARY KEY (user_id, course_id)
);
CREATE TABLE IF NOT EXISTS query_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    asked_at      TEXT NOT NULL,
    input_mode    TEXT NOT NULL CHECK (input_mode IN ('text', 'voice')),
    question      TEXT NOT NULL,
    subject       TEXT NOT NULL,
    route_method  TEXT NOT NULL,
    answer        TEXT NOT NULL,
    citations     TEXT NOT NULL,
    grounded      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_query_log_user ON query_log(user_id, asked_at);
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.migrate()

    def migrate(self) -> None:
        with self.conn:
            self.conn.executescript(_SCHEMA)
            row = self.conn.execute("SELECT version FROM schema_version").fetchone()
            if row is None:
                self.conn.execute("INSERT INTO schema_version VALUES (?)", (SCHEMA_VERSION,))

    def close(self) -> None:
        self.conn.close()

    # ---- users & sessions ------------------------------------------------------------------
    def insert_user(self, username: str, display_name: str, role: str, password_hash: str) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO users (username, display_name, role, password_hash, created_at) VALUES (?,?,?,?,?)",
                (username, display_name, role, password_hash, iso(utcnow())),
            )
        return int(cur.lastrowid)

    def user_by_username(self, username: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

    def user_by_id(self, user_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    def insert_session(self, token_hash: str, user_id: int, created_at: datetime, expires_at: datetime) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO sessions VALUES (?,?,?,?)", (token_hash, user_id, iso(created_at), iso(expires_at))
            )

    def session(self, token_hash: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM sessions WHERE token_hash = ?", (token_hash,)).fetchone()

    def delete_session(self, token_hash: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def delete_expired_sessions(self, now: datetime) -> int:
        with self.conn:
            return self.conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (iso(now),)).rowcount

    # ---- courses & grades ------------------------------------------------------------------
    def upsert_course(self, name: str, subject: str) -> int:
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO courses (name, subject) VALUES (?, ?)", (name, subject))
        return int(self.conn.execute("SELECT id FROM courses WHERE name = ?", (name,)).fetchone()[0])

    def set_grade(self, user_id: int, course_id: int, grade: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO grades VALUES (?,?,?) ON CONFLICT(user_id, course_id) DO UPDATE SET grade=excluded.grade",
                (user_id, course_id, grade),
            )

    def _grades_for_user(self, user_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT c.name AS course, c.subject AS subject, g.grade AS grade FROM grades g"
            " JOIN courses c ON c.id = g.course_id WHERE g.user_id = ? ORDER BY c.name",
            (user_id,),
        ).fetchall()

    def _grade_counts_by_course(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT c.name AS course, g.grade AS grade, COUNT(*) AS n FROM grades g"
            " JOIN courses c ON c.id = g.course_id GROUP BY c.name, g.grade ORDER BY c.name, g.grade"
        ).fetchall()

    # ---- query log -------------------------------------------------------------------------
    def insert_query(self, user_id: int, asked_at: datetime, input_mode: str, question: str, subject: str,
                     route_method: str, answer: str, citations: list[dict], grounded: bool) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO query_log (user_id, asked_at, input_mode, question, subject, route_method, answer,"
                " citations, grounded) VALUES (?,?,?,?,?,?,?,?,?)",
                (user_id, iso(asked_at), input_mode, question, subject, route_method, answer,
                 json.dumps(citations), int(grounded)),
            )
        return int(cur.lastrowid)

    def _queries_for_user(self, user_id: int, limit: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM query_log WHERE user_id = ? ORDER BY asked_at DESC, id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()

    def _query_counts_by_subject(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT subject, COUNT(*) AS n, COUNT(DISTINCT user_id) AS users FROM query_log GROUP BY subject"
        ).fetchall()

    def purge_queries_before(self, cutoff: datetime) -> int:
        with self.conn:
            return self.conn.execute("DELETE FROM query_log WHERE asked_at < ?", (iso(cutoff),)).rowcount
