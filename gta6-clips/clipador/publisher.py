"""Rotina diária de postagem no YouTube (e exportação para postar manualmente)."""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from .config import Config
from .db import DB, RENDERED, SCHEDULED, iso, parse_iso, utcnow
from .media import MediaWorker
from .metadata import make_description, make_tags, make_title
from .planner import Candidate, pick_clips, publish_times, quota_capacity, quota_day_start
from .youtube import YouTube, build_metadata

log = logging.getLogger(__name__)


def candidates(db: DB, cfg: Config, max_age_days: int = 4) -> list[Candidate]:
    yc = cfg["youtube"]
    since = iso(utcnow() - timedelta(days=max_age_days))
    sql = (
        "SELECT c.id, c.login, c.score, s.priority, s.authorized, "
        "(SELECT COUNT(*) FROM uploads u JOIN clips c2 ON c2.id=u.clip_id WHERE c2.login=c.login) AS ups "
        "FROM clips c JOIN streamers s ON s.login=c.login "
        "WHERE c.status=? AND c.vertical_path IS NOT NULL AND c.clip_created_at >= ? "
        "AND (c.approved=1 OR (c.approved IS NULL AND ?=1))"
    )
    rows = db.query(sql, (RENDERED, since, int(bool(yc["auto_approve"]))))
    out = []
    for r in rows:
        if yc["upload_only_authorized"] and not r["authorized"]:
            continue
        out.append(Candidate(r["id"], r["login"], r["score"], r["priority"], r["ups"]))
    return out


def uploaded_today_logins(db: DB, cfg: Config, now: datetime) -> set[str]:
    day_start = datetime.combine(now.astimezone(cfg.tz).date(), datetime.min.time(), tzinfo=cfg.tz)
    rows = db.query(
        "SELECT DISTINCT c.login FROM uploads u JOIN clips c ON c.id=u.clip_id WHERE u.uploaded_at >= ?",
        (iso(day_start),),
    )
    return {r["login"] for r in rows}


def build_video_meta(db: DB, cfg: Config, clip, publish_at: datetime | None) -> dict:
    yc = cfg["youtube"]
    s = db.one("SELECT display_name FROM streamers WHERE login=?", (clip["login"],))
    name = s["display_name"] if s and s["display_name"] else clip["login"]
    sample_row = db.one(
        "SELECT sample FROM moments WHERE login=? AND harvested=1 ORDER BY ABS(julianday(at_utc)-julianday(?)) LIMIT 1",
        (clip["login"], clip["clip_created_at"]),
    ) if clip["source"] == "hype" else None
    live_date = parse_iso(clip["clip_created_at"]).astimezone(cfg.tz) if clip["clip_created_at"] else None
    return build_metadata(
        title=make_title(dict(clip), name, yc["title_suffix"], sample_row["sample"] if sample_row else ""),
        description=make_description(dict(clip), clip["login"], name, yc["hashtags"], live_date),
        tags=make_tags(yc["tags"], clip["login"], name),
        category_id=yc["category_id"],
        privacy=yc["privacy"],
        publish_at=publish_at,
        made_for_kids=yc["made_for_kids"],
    )


def plan_today(db: DB, cfg: Config, now: datetime | None = None, capacity: int | None = None) -> list[tuple]:
    """Devolve [(clip_row, publish_at)] sem fazer upload (usado também pelo painel)."""
    now = now or utcnow()
    yc = cfg["youtube"]
    if capacity is None:
        used = db.quota_used_today(quota_day_start(now))
        capacity = quota_capacity(yc["daily_quota"], used, yc["upload_cost"], yc["quota_reserve"])
    done = uploaded_today_logins(db, cfg, now)
    cands = [c for c in candidates(db, cfg) if c.login not in done]
    chosen = pick_clips(cands, capacity)
    local_now = now.astimezone(cfg.tz)
    times = publish_times(len(chosen), local_now.date(), yc["publish_slots"], cfg.tz, local_now)
    return [(db.one("SELECT * FROM clips WHERE id=?", (c.clip_id,)), t) for c, t in zip(chosen, times)]


def run_daily(db: DB, cfg: Config, yt: YouTube, media: MediaWorker, dry_run: bool = False) -> list[str]:
    yc = cfg["youtube"]
    now = utcnow()
    used = db.quota_used_today(quota_day_start(now))
    capacity = quota_capacity(yc["daily_quota"], used, yc["upload_cost"], yc["quota_reserve"])
    log.info("Cota: %d usada hoje, cabem %d uploads", used, capacity)
    ids: list[str] = []

    comp_key = f"compilation:{now.astimezone(cfg.tz).date()}"
    if yc["compilation"]["enabled"] and capacity > 0 and not db.get_meta(comp_key):
        vid = _compilation(db, cfg, yt, media, now, dry_run)
        if vid:
            ids.append(vid)
            capacity -= 1
            if not dry_run:
                db.set_meta(comp_key, vid)

    for clip, when in plan_today(db, cfg, now, capacity):
        meta = build_video_meta(db, cfg, clip, when)
        log.info("Upload #%s %s → %s às %s", clip["id"], clip["login"], meta["snippet"]["title"], when)
        if dry_run:
            continue
        try:
            vid = yt.upload(Path(clip["vertical_path"]), meta)
        except Exception as e:
            log.error("Upload do clipe #%s falhou: %s", clip["id"], e)
            db.update_clip(clip["id"], error=str(e)[:1000])
            if "quotaExceeded" in str(e) or "uploadLimitExceeded" in str(e):
                break
            continue
        db.update_clip(clip["id"], status=SCHEDULED, youtube_id=vid, publish_at=iso(when), error=None)
        db.execute(
            "INSERT INTO uploads (clip_id, kind, youtube_id, title, publish_at, quota_cost, uploaded_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (clip["id"], "short", vid, meta["snippet"]["title"], iso(when), yc["upload_cost"], iso(utcnow())),
        )
        ids.append(vid)
    return ids


def _compilation(db: DB, cfg: Config, yt: YouTube, media: MediaWorker, now: datetime, dry_run: bool) -> str | None:
    """Vídeo horizontal com o melhor clipe de cada streamer das últimas 24h."""
    yc = cfg["youtube"]
    since = iso(now - timedelta(hours=26))
    rows = db.query(
        "SELECT * FROM (SELECT c.*, ROW_NUMBER() OVER (PARTITION BY login ORDER BY score DESC) rn FROM clips c "
        "WHERE raw_path IS NOT NULL AND clip_created_at >= ? AND (approved IS NULL OR approved=1)) "
        "WHERE rn=1 ORDER BY score DESC LIMIT ?",
        (since, yc["compilation"]["max_clips"]),
    )
    if len(rows) < 3:
        log.info("Poucos clipes para compilação hoje (%d)", len(rows))
        return None
    day = now.astimezone(cfg.tz)
    names = []
    for r in rows:
        s = db.one("SELECT display_name FROM streamers WHERE login=?", (r["login"],))
        names.append((s["display_name"] if s else r["login"], r["login"]))
    title = f"MELHORES MOMENTOS GTA 6 DOS STREAMERS BR — {day:%d/%m}"[:100]
    desc = (
        "Os melhores momentos de GTA 6 nas lives dos maiores streamers do Brasil.\n\n"
        "Streamers neste vídeo (sigam!):\n"
        + "\n".join(f"• {n} — https://twitch.tv/{l}" for n, l in names)
        + "\n\nTodos os créditos aos criadores originais.\n\n" + " ".join(h for h in yc["hashtags"] if h != "#shorts")
    )
    when = publish_times(1, day.date(), yc["publish_slots"][-1:], cfg.tz, day)[0]
    meta = build_metadata(title, desc, make_tags(yc["tags"], "", "GTA 6 Brasil"), yc["category_id"],
                          yc["privacy"], when, yc["made_for_kids"])
    if dry_run:
        log.info("[dry-run] Compilação: %s (%d clipes)", title, len(rows))
        return "dry-run"
    out = cfg.videos_dir / f"compilacao-{day:%Y-%m-%d}.mp4"
    media.build_compilation(rows, out)
    vid = yt.upload(out, meta)
    db.execute(
        "INSERT INTO uploads (clip_id, kind, youtube_id, title, publish_at, quota_cost, uploaded_at) VALUES (?,?,?,?,?,?,?)",
        (None, "compilation", vid, title, iso(when), yc["upload_cost"], iso(utcnow())),
    )
    return vid


def export_day(db: DB, cfg: Config, count: int = 30) -> Path:
    """Gera uma pasta com os vídeos do dia + títulos/descrições para postar manualmente
    (útil enquanto a API do YouTube não está liberada para seu projeto)."""
    now = utcnow()
    day = now.astimezone(cfg.tz)
    out = cfg.data_dir / "export" / f"{day:%Y-%m-%d}"
    out.mkdir(parents=True, exist_ok=True)
    plan = plan_today(db, cfg, now, capacity=count)
    manifest = []
    for i, (clip, when) in enumerate(plan, 1):
        meta = build_video_meta(db, cfg, clip, when)
        fname = f"{i:02d}_{clip['login']}_{clip['id']}.mp4"
        shutil.copy2(clip["vertical_path"], out / fname)
        manifest.append({
            "arquivo": fname,
            "agendar_para": when.strftime("%d/%m/%Y %H:%M"),
            "titulo": meta["snippet"]["title"],
            "descricao": meta["snippet"]["description"],
            "tags": ", ".join(meta["snippet"]["tags"]),
        })
        # conta como postado (rodízio justo), mas sem gastar cota da API
        db.update_clip(clip["id"], status="exported", publish_at=iso(when))
        db.execute(
            "INSERT INTO uploads (clip_id, kind, youtube_id, title, publish_at, quota_cost, uploaded_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (clip["id"], "manual", "", meta["snippet"]["title"], iso(when), 0, iso(utcnow())),
        )
    (out / "postagens.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    with (out / "postagens.txt").open("w", encoding="utf-8") as f:
        for m in manifest:
            f.write(f"=== {m['arquivo']}  (agendar: {m['agendar_para']})\nTÍTULO: {m['titulo']}\n\n"
                    f"{m['descricao']}\n\nTAGS: {m['tags']}\n\n")
    return out
