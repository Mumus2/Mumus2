"""Descobre e mantém a lista dos ~30 maiores streamers BR jogando GTA VI."""
from __future__ import annotations

import logging
from typing import Any

from .config import Config, load_seeds
from .db import DB, iso, utcnow
from .twitch import Twitch

log = logging.getLogger(__name__)


def resolve_game_id(cfg: Config, tw: Twitch) -> str:
    gid = str(cfg["twitch"].get("game_id") or "")
    if gid:
        return gid
    gid = tw.find_game_id(cfg["twitch"]["game_name"])
    if not gid:
        raise RuntimeError(f"Categoria '{cfg['twitch']['game_name']}' não encontrada na Twitch")
    log.info("Categoria %s = game_id %s", cfg["twitch"]["game_name"], gid)
    return gid


def sync_seeds(db: DB, tw: Twitch, cfg: Config) -> list[str]:
    """Valida a lista-semente na API e grava no banco. Devolve logins inválidos."""
    seeds = load_seeds(cfg)
    if not seeds:
        return []
    found = {u["login"].lower(): u for u in tw.users(s["login"] for s in seeds)}
    invalid = []
    for s in seeds:
        user = found.get(s["login"])
        if not user:
            invalid.append(s["login"])
            log.warning("Login '%s' não existe na Twitch — confira streamers.yaml", s["login"])
            continue
        db.upsert_streamer(
            s["login"],
            user_id=user["id"],
            display_name=user["display_name"],
            avatar_url=user.get("profile_image_url", ""),
            pinned=int(s["pinned"]),
            authorized=int(s["authorized"]),
            priority=s["priority"],
        )
    return invalid


def select_tracked(rows: list[dict[str, Any]], max_n: int) -> set[str]:
    """Fixados sempre entram; o resto é preenchido por pico de audiência."""
    pinned = [r["login"] for r in rows if r["pinned"]]
    others = sorted(
        (r for r in rows if not r["pinned"]),
        key=lambda r: (r["peak_viewers"], r["last_viewers"]),
        reverse=True,
    )
    chosen = list(pinned)
    for r in others:
        if len(chosen) >= max_n:
            break
        chosen.append(r["login"])
    return set(chosen)


def discover(db: DB, tw: Twitch, cfg: Config, game_id: str) -> list[dict]:
    """Busca as maiores lives PT-BR de GTA VI agora e atualiza o ranking."""
    tcfg = cfg["twitch"]
    streams = tw.top_streams(game_id, tcfg["language"], limit=300)
    streams = [s for s in streams if s["viewer_count"] >= tcfg["min_viewers"]]
    now = iso(utcnow())
    if streams:
        users = {u["login"].lower(): u for u in tw.users(s["user_login"] for s in streams)}
    else:
        users = {}
    for s in streams:
        login = s["user_login"].lower()
        prev = db.one("SELECT peak_viewers FROM streamers WHERE login=?", (login,))
        peak = max(s["viewer_count"], prev["peak_viewers"] if prev else 0)
        u = users.get(login, {})
        db.upsert_streamer(
            login,
            user_id=s["user_id"],
            display_name=s["user_name"],
            avatar_url=u.get("profile_image_url", ""),
            peak_viewers=peak,
            last_viewers=s["viewer_count"],
            last_seen_live=now,
        )
    rows = [dict(r) for r in db.query("SELECT * FROM streamers")]
    tracked = select_tracked(rows, tcfg["max_streamers"])
    with db.tx() as c:
        c.execute("UPDATE streamers SET tracked=0")
        c.executemany("UPDATE streamers SET tracked=1 WHERE login=?", [(l,) for l in tracked])
    log.info("Descoberta: %d lives PT de GTA VI, acompanhando %d canais", len(streams), len(tracked))
    return streams


def refresh_live(db: DB, tw: Twitch, game_id: str) -> dict[str, dict]:
    """Atualiza quem está AO VIVO jogando GTA VI. Devolve {login: stream}."""
    rows = db.tracked_streamers()
    ids = [r["user_id"] for r in rows if r["user_id"]]
    live = {s["user_login"].lower(): s for s in tw.live_streams(ids)} if ids else {}
    gta_live: dict[str, dict] = {}
    for r in rows:
        s = live.get(r["login"])
        on_gta = bool(s and s["game_id"] == game_id)
        fields: dict[str, Any] = {"is_live_gta": int(on_gta)}
        if s:
            fields["current_stream_id"] = s["id"]
            fields["last_viewers"] = s["viewer_count"]
            fields["peak_viewers"] = max(r["peak_viewers"], s["viewer_count"])
            fields["last_seen_live"] = iso(utcnow())
            db.execute(
                "INSERT INTO streams (stream_id, login, started_at, title, game_id) VALUES (?,?,?,?,?) "
                "ON CONFLICT(stream_id) DO UPDATE SET title=excluded.title, game_id=excluded.game_id",
                (s["id"], r["login"], s["started_at"], s["title"], s["game_id"]),
            )
        db.upsert_streamer(r["login"], **fields)
        if on_gta:
            gta_live[r["login"]] = s
    return gta_live
