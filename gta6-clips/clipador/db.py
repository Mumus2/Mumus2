"""Banco SQLite: streamers, lives, momentos de hype, clipes e uploads."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS streamers (
    login         TEXT PRIMARY KEY,
    user_id       TEXT,
    display_name  TEXT,
    avatar_url    TEXT,
    pinned        INTEGER NOT NULL DEFAULT 0,
    authorized    INTEGER NOT NULL DEFAULT 0,
    priority      INTEGER NOT NULL DEFAULT 1,
    tracked       INTEGER NOT NULL DEFAULT 1,
    peak_viewers  INTEGER NOT NULL DEFAULT 0,
    last_viewers  INTEGER NOT NULL DEFAULT 0,
    is_live_gta   INTEGER NOT NULL DEFAULT 0,
    current_stream_id TEXT,
    last_seen_live TEXT,
    added_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS streams (
    stream_id   TEXT PRIMARY KEY,
    login       TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    title       TEXT,
    game_id     TEXT
);

CREATE TABLE IF NOT EXISTS moments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    login       TEXT NOT NULL,
    stream_id   TEXT,
    at_utc      TEXT NOT NULL,
    offset_s    REAL,
    score       REAL NOT NULL,
    rate        REAL NOT NULL,
    sample      TEXT,
    harvested   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS clips (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    login           TEXT NOT NULL,
    source          TEXT NOT NULL,          -- twitch_clip | hype
    source_id       TEXT NOT NULL UNIQUE,   -- id do clipe ou "vod:<id>:<offset>"
    title           TEXT,
    custom_title    TEXT,                   -- título editado no painel
    url             TEXT NOT NULL,
    start_s         REAL,                   -- só para source=hype (trecho do VOD)
    end_s           REAL,
    duration        REAL,
    view_count      INTEGER DEFAULT 0,
    score           REAL NOT NULL DEFAULT 0,
    clip_created_at TEXT,
    raw_path        TEXT,
    vertical_path   TEXT,
    horizontal_path TEXT,
    status          TEXT NOT NULL DEFAULT 'candidate',
    approved        INTEGER,                -- NULL = sem decisão, 1 = aprovado, 0 = rejeitado
    youtube_id      TEXT,
    publish_at      TEXT,
    error           TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS clips_login_status ON clips(login, status);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS uploads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_id     INTEGER,                    -- NULL para compilação
    kind        TEXT NOT NULL,              -- short | video | compilation
    youtube_id  TEXT NOT NULL,
    title       TEXT,
    publish_at  TEXT,
    quota_cost  INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL
);
"""

# Status do ciclo de vida de um clipe
CANDIDATE = "candidate"      # encontrado, ainda não baixado
DOWNLOADED = "downloaded"
RENDERED = "rendered"        # pronto para postar
SCHEDULED = "scheduled"      # enviado ao YouTube com publishAt
UPLOADED = "uploaded"        # publicado
FAILED = "failed"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class DB:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: tuple | dict = ()) -> int:
        with self.tx() as c:
            cur = c.execute(sql, params)
            return cur.lastrowid

    # ---------- streamers ----------
    def upsert_streamer(self, login: str, **fields: Any) -> None:
        login = login.lower()
        existing = self.one("SELECT login FROM streamers WHERE login=?", (login,))
        if existing is None:
            fields.setdefault("added_at", iso(utcnow()))
            cols = ["login", *fields.keys()]
            self.execute(
                f"INSERT INTO streamers ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                (login, *fields.values()),
            )
        elif fields:
            sets = ",".join(f"{k}=?" for k in fields)
            self.execute(f"UPDATE streamers SET {sets} WHERE login=?", (*fields.values(), login))

    def tracked_streamers(self) -> list[sqlite3.Row]:
        return self.query(
            "SELECT * FROM streamers WHERE tracked=1 ORDER BY pinned DESC, peak_viewers DESC, login"
        )

    # ---------- clips ----------
    def add_clip(self, **fields: Any) -> int | None:
        """Insere um clipe; devolve None se ele já existe (mesmo source_id)."""
        fields.setdefault("created_at", iso(utcnow()))
        cols = list(fields.keys())
        with self.tx() as c:
            cur = c.execute(
                f"INSERT OR IGNORE INTO clips ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                tuple(fields.values()),
            )
            return cur.lastrowid if cur.rowcount else None

    def update_clip(self, clip_id: int, **fields: Any) -> None:
        sets = ",".join(f"{k}=?" for k in fields)
        self.execute(f"UPDATE clips SET {sets} WHERE id=?", (*fields.values(), clip_id))

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.one("SELECT value FROM meta WHERE key=?", (key,))
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def quota_used_today(self, day_start_utc: datetime) -> int:
        row = self.one(
            "SELECT COALESCE(SUM(quota_cost),0) AS used FROM uploads WHERE uploaded_at >= ?",
            (iso(day_start_utc),),
        )
        return int(row["used"]) if row else 0
