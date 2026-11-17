"""Junta candidatos a clipe de duas fontes:

1. Clipes da comunidade (viewers clipam os melhores lances) — curadoria humana.
2. Momentos de hype detectados no chat — recortados do VOD da live.
"""
from __future__ import annotations

import logging
import math
from datetime import timedelta

from .config import Config
from .db import DB, iso, parse_iso, utcnow
from .hype import clip_window
from .twitch import Twitch, parse_twitch_duration

log = logging.getLogger(__name__)


def community_score(views: int) -> float:
    return round(math.log2(1 + max(views, 0)), 2)


def overlaps(a: tuple[float, float], b: tuple[float, float], min_overlap: float = 5) -> bool:
    return min(a[1], b[1]) - max(a[0], b[0]) >= min_overlap


def harvest_community(db: DB, tw: Twitch, cfg: Config, game_id: str) -> int:
    h = cfg["harvest"]
    end = utcnow()
    start = end - timedelta(hours=h["lookback_hours"])
    added = 0
    for s in db.tracked_streamers():
        if not s["user_id"]:
            continue
        try:
            clips = tw.clips(s["user_id"], start, end, limit=100)
        except Exception as e:  # um canal com problema não pode parar os outros
            log.warning("Falha ao buscar clipes de %s: %s", s["login"], e)
            continue
        good = [
            c
            for c in clips
            if c.get("game_id") == game_id
            and c["view_count"] >= h["min_clip_views"]
            and c["duration"] <= h["max_clip_seconds"]
        ]
        good.sort(key=lambda c: c["view_count"], reverse=True)
        for c in good[: h["community_clips_per_streamer"]]:
            vod_start = c.get("vod_offset")
            new_id = db.add_clip(
                login=s["login"],
                source="twitch_clip",
                source_id=c["id"],
                title=c["title"],
                url=c["url"],
                start_s=vod_start,
                end_s=(vod_start + c["duration"]) if vod_start is not None else None,
                duration=c["duration"],
                view_count=c["view_count"],
                score=community_score(c["view_count"]),
                clip_created_at=c["created_at"],
            )
            if new_id:
                added += 1
            else:  # já existia: atualiza views/score
                db.execute(
                    "UPDATE clips SET view_count=?, score=? WHERE source_id=?",
                    (c["view_count"], community_score(c["view_count"]), c["id"]),
                )
        # guarda o vídeo do VOD de cada clipe para deduplicar contra momentos de hype
        for c in good:
            if c.get("video_id") and c.get("vod_offset") is not None:
                db.set_meta(f"clipvod:{c['id']}", f"{c['video_id']}:{c['vod_offset']}:{c['duration']}")
    log.info("Clipes da comunidade novos: %d", added)
    return added


def harvest_moments(db: DB, tw: Twitch, cfg: Config) -> int:
    hc = cfg["hype"]
    max_len = cfg["harvest"]["max_clip_seconds"]
    pending = db.query(
        "SELECT m.*, s.user_id FROM moments m JOIN streamers s ON s.login=m.login "
        "WHERE m.harvested=0 ORDER BY m.at_utc"
    )
    if not pending:
        return 0
    archives_cache: dict[str, list[dict]] = {}
    added = 0
    now = utcnow()
    for m in pending:
        uid = m["user_id"]
        if uid not in archives_cache:
            try:
                archives_cache[uid] = tw.archives(uid)
            except Exception as e:
                log.warning("Falha ao listar VODs de %s: %s", m["login"], e)
                archives_cache[uid] = []
        video = next((v for v in archives_cache[uid] if v.get("stream_id") == m["stream_id"]), None)
        at = parse_iso(m["at_utc"])
        if video is None:
            if now - at > timedelta(hours=6):
                # streamer não salva VODs (ou apagou): desiste deste momento
                db.execute("UPDATE moments SET harvested=2 WHERE id=?", (m["id"],))
            continue
        offset = (at - parse_iso(video["created_at"])).total_seconds()
        start, end = clip_window(offset, hc["pre_roll_seconds"], hc["post_roll_seconds"], max_len)
        if end > parse_twitch_duration(video["duration"]):
            continue  # a live ainda não chegou até aqui no VOD; tenta na próxima rodada
        if _covered_by_community_clip(db, video["id"], (start, end)):
            db.execute("UPDATE moments SET harvested=3 WHERE id=?", (m["id"],))
            continue
        new_id = db.add_clip(
            login=m["login"],
            source="hype",
            source_id=f"vod:{video['id']}:{int(start)}",
            title=None,
            url=video["url"],
            start_s=start,
            end_s=end,
            duration=end - start,
            score=m["score"],
            clip_created_at=m["at_utc"],
        )
        db.execute("UPDATE moments SET harvested=1, offset_s=? WHERE id=?", (offset, m["id"]))
        added += bool(new_id)
    log.info("Clipes de momentos de hype novos: %d", added)
    return added


def _covered_by_community_clip(db: DB, video_id: str, window: tuple[float, float]) -> bool:
    for row in db.query("SELECT value FROM meta WHERE key LIKE 'clipvod:%' AND value LIKE ?", (f"{video_id}:%",)):
        _, off, dur = row["value"].split(":")
        if overlaps(window, (float(off), float(off) + float(dur))):
            return True
    return False


def record_moment(db: DB, login: str, stream: dict | None, at_ts: float, score: float, rate: float, sample: list[str]) -> int:
    from datetime import datetime, timezone

    at = datetime.fromtimestamp(at_ts, tz=timezone.utc)
    offset = None
    if stream:
        offset = (at - parse_iso(stream["started_at"])).total_seconds()
    return db.execute(
        "INSERT INTO moments (login, stream_id, at_utc, offset_s, score, rate, sample) VALUES (?,?,?,?,?,?,?)",
        (login, stream["id"] if stream else None, iso(at), offset, score, rate, "\n".join(sample)[:2000]),
    )
