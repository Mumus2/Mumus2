"""Coleta tudo sobre o canal: perfil, números, vídeos, analytics e monetização.

Fontes:
- YouTube Data API v3      → perfil, inscritos/views totais (quase em tempo real), vídeos
- YouTube Analytics API v2 → views/horas/inscritos por dia, receita, tráfego, público
  (os dados do Analytics chegam com ~48h de atraso — é assim no próprio YouTube Studio)

Cada relatório roda isolado: se um falhar (sem permissão, canal sem monetização,
API fora do ar), os outros continuam e o painel mostra o motivo.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from .config import Config
from .db import DB, iso, utcnow
from .youtube import API, YouTube

log = logging.getLogger(__name__)

ANALYTICS = "https://youtubeanalytics.googleapis.com/v2/reports"
PERIODS = (7, 28, 90, 365)

DAILY_METRICS = (
    "views,estimatedMinutesWatched,averageViewDuration,subscribersGained,"
    "subscribersLost,likes,comments,shares"
)
REVENUE_METRICS = "estimatedRevenue,estimatedAdRevenue,grossRevenue,cpm,playbackBasedCpm,monetizedPlaybacks"

SCHEMA = """
CREATE TABLE IF NOT EXISTS yt_videos (
    id           TEXT PRIMARY KEY,
    title        TEXT,
    published_at TEXT,
    duration_s   INTEGER,
    is_short     INTEGER,
    views        INTEGER,
    likes        INTEGER,
    comments     INTEGER,
    thumbnail    TEXT,
    privacy      TEXT,
    updated_at   TEXT
);
CREATE TABLE IF NOT EXISTS channel_history (
    ts       TEXT PRIMARY KEY,
    subs     INTEGER,
    views    INTEGER,
    videos   INTEGER
);
"""


class AnalyticsError(RuntimeError):
    pass


def parse_iso_duration(value: str) -> int:
    """'PT1M5S' -> 65; 'PT2H' -> 7200; 'P1DT1S' -> 86401."""
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def rows_to_dicts(body: dict) -> list[dict]:
    names = [h["name"] for h in body.get("columnHeaders", [])]
    return [dict(zip(names, row)) for row in body.get("rows", []) or []]


def explain(status: int, text: str) -> str:
    low = text.lower()
    if status == 403 and ("insufficient" in low or "scope" in low or "permission" in low):
        return "sem permissão — rode de novo: python -m clipador youtube-auth"
    if status == 403 and "monetary" in low:
        return "sem permissão de monetização"
    if status == 401:
        return "token expirado ou revogado — rode: python -m clipador youtube-auth"
    return f"HTTP {status}: {text[:200]}"


class ChannelStats:
    def __init__(self, yt: YouTube, currency: str = "BRL"):
        self.yt = yt
        self.currency = currency

    def _get(self, url: str, params: dict) -> dict:
        r = self.yt.http.get(url, params=params, headers={"Authorization": f"Bearer {self.yt._token()}"})
        if r.status_code != 200:
            raise AnalyticsError(explain(r.status_code, r.text))
        return r.json()

    # ---------- Data API ----------
    def channel(self) -> dict:
        body = self._get(f"{API}/channels", {
            "part": "snippet,statistics,brandingSettings,contentDetails,status", "mine": "true"})
        items = body.get("items", [])
        if not items:
            raise AnalyticsError("esta conta ainda não tem canal no YouTube")
        return items[0]

    def upload_ids(self, playlist_id: str, limit: int) -> list[str]:
        ids, token = [], None
        while len(ids) < limit:
            params = {"part": "contentDetails", "playlistId": playlist_id, "maxResults": 50}
            if token:
                params["pageToken"] = token
            body = self._get(f"{API}/playlistItems", params)
            ids += [i["contentDetails"]["videoId"] for i in body.get("items", [])]
            token = body.get("nextPageToken")
            if not token:
                break
        return ids[:limit]

    def videos(self, ids: list[str]) -> list[dict]:
        out = []
        for i in range(0, len(ids), 50):
            body = self._get(f"{API}/videos", {"part": "snippet,statistics,contentDetails,status",
                                               "id": ",".join(ids[i:i + 50]), "maxResults": 50})
            out += body.get("items", [])
        return out

    # ---------- Analytics API ----------
    def report(self, start: date, end: date, metrics: str, dimensions: str | None = None,
               sort: str | None = None, max_results: int | None = None, filters: str | None = None,
               currency: bool = False) -> list[dict]:
        params: dict[str, Any] = {"ids": "channel==MINE", "startDate": start.isoformat(),
                                  "endDate": end.isoformat(), "metrics": metrics}
        if dimensions:
            params["dimensions"] = dimensions
        if sort:
            params["sort"] = sort
        if max_results:
            params["maxResults"] = max_results
        if filters:
            params["filters"] = filters
        if currency:
            params["currency"] = self.currency
        return rows_to_dicts(self._get(ANALYTICS, params))


def ensure_schema(db: DB) -> None:
    with db.tx() as c:
        c.executescript(SCHEMA)


def _profile(ch: dict) -> dict:
    sn, st = ch.get("snippet", {}), ch.get("statistics", {})
    thumbs = sn.get("thumbnails", {})
    avatar = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
    banner = ch.get("brandingSettings", {}).get("image", {}).get("bannerExternalUrl", "")
    return {
        "id": ch.get("id"),
        "title": sn.get("title", ""),
        "handle": sn.get("customUrl", ""),
        "description": sn.get("description", ""),
        "published_at": sn.get("publishedAt", ""),
        "country": sn.get("country", ""),
        "avatar": avatar,
        "banner": banner,
        "subscribers": int(st.get("subscriberCount", 0) or 0),
        "subscribers_hidden": bool(st.get("hiddenSubscriberCount")),
        "views": int(st.get("viewCount", 0) or 0),
        "videos": int(st.get("videoCount", 0) or 0),
        "uploads_playlist": ch.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", ""),
        "privacy": ch.get("status", {}).get("privacyStatus", ""),
        "long_uploads": ch.get("status", {}).get("longUploadsStatus", ""),
        "made_for_kids": bool(ch.get("status", {}).get("madeForKids")),
    }


def collect(db: DB, cfg: Config, yt: YouTube, today: date | None = None) -> dict:
    """Coleta tudo e grava o snapshot no banco (meta 'dashboard'). Devolve o snapshot."""
    ensure_schema(db)
    dcfg = cfg.raw.get("dashboard", {})
    stats = ChannelStats(yt, dcfg.get("currency", "BRL"))
    today = today or utcnow().astimezone(cfg.tz).date()
    snap: dict[str, Any] = {"fetched_at": iso(utcnow()), "errors": {}, "currency": stats.currency}

    def attempt(name: str, fn, default=None):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — um relatório nunca derruba os outros
            snap["errors"][name] = str(e)[:300]
            log.warning("Painel do canal: %s falhou: %s", name, e)
            return default

    ch = attempt("canal", stats.channel)
    if ch is None:
        _save(db, snap)
        return snap
    prof = _profile(ch)
    snap["channel"] = prof
    db.execute("INSERT OR REPLACE INTO channel_history (ts, subs, views, videos) VALUES (?,?,?,?)",
               (snap["fetched_at"], prof["subscribers"], prof["views"], prof["videos"]))

    # ---------- vídeos ----------
    def load_videos():
        ids = stats.upload_ids(prof["uploads_playlist"], int(dcfg.get("max_videos", 200)))
        now = iso(utcnow())
        for v in stats.videos(ids):
            dur = parse_iso_duration(v.get("contentDetails", {}).get("duration", ""))
            st, sn = v.get("statistics", {}), v.get("snippet", {})
            th = sn.get("thumbnails", {})
            db.execute(
                "INSERT OR REPLACE INTO yt_videos (id, title, published_at, duration_s, is_short, views, likes, "
                "comments, thumbnail, privacy, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (v["id"], sn.get("title", ""), sn.get("publishedAt", ""), dur, int(0 < dur <= 180),
                 int(st.get("viewCount", 0) or 0), int(st.get("likeCount", 0) or 0),
                 int(st.get("commentCount", 0) or 0),
                 (th.get("medium") or th.get("default") or {}).get("url", ""),
                 v.get("status", {}).get("privacyStatus", ""), now),
            )
        return len(ids)

    snap["videos_synced"] = attempt("videos", load_videos, 0)

    # ---------- séries diárias (365 dias) ----------
    start = today - timedelta(days=364)
    daily = attempt("diario", lambda: stats.report(start, today, DAILY_METRICS, "day", "day"), [])
    revenue = attempt("receita", lambda: stats.report(start, today, REVENUE_METRICS, "day", "day",
                                                      currency=True), None)
    by_day = {r["day"]: dict(r) for r in daily}
    if revenue:
        for r in revenue:
            by_day.setdefault(r["day"], {"day": r["day"]}).update(r)
    snap["daily"] = [by_day[k] for k in sorted(by_day)]

    total_rev = sum(float(r.get("estimatedRevenue") or 0) for r in revenue or [])
    if revenue is None:
        err = snap["errors"].get("receita", "")
        status = "no_permission" if "permiss" in err else "unavailable"
    elif total_rev > 0:
        status = "active"
    else:
        status = "inactive"
    snap["monetization"] = {"status": status, "revenue_365": round(total_rev, 2)}

    # ---------- recortes por período ----------
    breakdowns: dict[str, dict] = {}
    for days in PERIODS:
        s = today - timedelta(days=days - 1)
        b: dict[str, Any] = {}
        b["traffic"] = attempt(f"trafego_{days}", lambda: stats.report(
            s, today, "views,estimatedMinutesWatched", "insightTrafficSourceType", "-views"), [])
        b["countries"] = attempt(f"paises_{days}", lambda: stats.report(
            s, today, "views,estimatedMinutesWatched", "country", "-views", 10), [])
        b["devices"] = attempt(f"dispositivos_{days}", lambda: stats.report(
            s, today, "views", "deviceType", "-views"), [])
        b["demographics"] = attempt(f"publico_{days}", lambda: stats.report(
            s, today, "viewerPercentage", "ageGroup,gender"), [])
        b["content_type"] = attempt(f"formato_{days}", lambda: stats.report(
            s, today, "views,estimatedMinutesWatched", "creatorContentType"), [])
        b["top_videos"] = attempt(f"top_{days}", lambda: stats.report(
            s, today, "views,estimatedMinutesWatched,averageViewPercentage,subscribersGained",
            "video", "-views", 25), [])
        breakdowns[str(days)] = b
    snap["breakdowns"] = breakdowns
    snap["ypp"] = ypp_progress(db, snap)
    _save(db, snap)
    log.info("Painel do canal atualizado: %s inscritos, %d erros", prof["subscribers"], len(snap["errors"]))
    return snap


def ypp_progress(db: DB, snap: dict) -> dict:
    """Progresso para o Programa de Parcerias (valores oficiais: YouTube Studio)."""
    prof = snap.get("channel", {})
    year = snap.get("breakdowns", {}).get("365", {}).get("content_type") or []
    q90 = snap.get("breakdowns", {}).get("90", {}).get("content_type") or []
    approx = False
    if year:
        long_min = sum(float(r.get("estimatedMinutesWatched") or 0) for r in year
                       if str(r.get("creatorContentType", "")).lower() in ("videoondemand", "livestream"))
    else:  # sem o recorte por formato: usa o total (superestima) e avisa
        approx = True
        long_min = sum(float(r.get("estimatedMinutesWatched") or 0) for r in snap.get("daily", []))
    if q90:
        shorts_90 = sum(int(r.get("views") or 0) for r in q90 if str(r.get("creatorContentType", "")).lower() == "shorts")
    else:
        approx = True
        cutoff = iso(utcnow() - timedelta(days=90))
        row = db.one("SELECT COALESCE(SUM(views),0) AS v FROM yt_videos WHERE is_short=1 AND published_at >= ?", (cutoff,))
        shorts_90 = int(row["v"]) if row else 0
    return {"subscribers": prof.get("subscribers", 0), "long_hours_12m": round(long_min / 60, 1),
            "shorts_views_90d": shorts_90, "approximate": approx}


def _save(db: DB, snap: dict) -> None:
    db.set_meta("dashboard", json.dumps(snap, ensure_ascii=False))


def load_snapshot(db: DB) -> dict | None:
    raw = db.get_meta("dashboard")
    return json.loads(raw) if raw else None


# ---------------- montagem do JSON do painel ----------------

def _num(r: dict, k: str) -> float:
    try:
        return float(r.get(k) or 0)
    except (TypeError, ValueError):
        return 0.0


def _sum(rows: list[dict], key: str) -> float:
    return sum(_num(r, key) for r in rows)


def build_view(db: DB, cfg: Config, days: int, now: datetime | None = None) -> dict:
    """JSON consumido pela página /canal (filtra tudo pelo mesmo período)."""
    ensure_schema(db)
    snap = load_snapshot(db)
    days = days if days in PERIODS else 28
    bot = _bot_status(db, cfg, now or utcnow())
    if not snap:
        return {"ready": False, "days": days, "bot": bot}
    daily = snap.get("daily", [])
    cur, prev = daily[-days:], daily[-2 * days:-days] if len(daily) >= 2 * days else []
    prof = snap.get("channel", {})

    # inscritos totais por dia: total atual menos o saldo dos dias seguintes.
    # A contagem pública é arredondada e o Analytics atrasa ~2 dias, então nunca deixa ficar < 0.
    total, subs_series = prof.get("subscribers", 0), []
    for r in reversed(daily):
        subs_series.append(max(0, total))
        total -= int(_num(r, "subscribersGained") - _num(r, "subscribersLost"))
    subs_series.reverse()

    series = [{
        "day": r["day"],
        "views": int(_num(r, "views")),
        "hours": round(_num(r, "estimatedMinutesWatched") / 60, 1),
        "subs_net": int(_num(r, "subscribersGained") - _num(r, "subscribersLost")),
        "subs_total": subs_series[len(daily) - len(cur) + i] if subs_series else None,
        "revenue": round(_num(r, "estimatedRevenue"), 2),
        "likes": int(_num(r, "likes")),
    } for i, r in enumerate(cur)]

    def kpi(key_fn, rows):
        return round(sum(key_fn(r) for r in rows), 2)

    k = {
        "views": kpi(lambda r: _num(r, "views"), cur),
        "views_prev": kpi(lambda r: _num(r, "views"), prev) if prev else None,
        "hours": round(_sum(cur, "estimatedMinutesWatched") / 60, 1),
        "hours_prev": round(_sum(prev, "estimatedMinutesWatched") / 60, 1) if prev else None,
        "subs_net": int(kpi(lambda r: _num(r, "subscribersGained") - _num(r, "subscribersLost"), cur)),
        "subs_net_prev": int(kpi(lambda r: _num(r, "subscribersGained") - _num(r, "subscribersLost"), prev)) if prev else None,
        "revenue": kpi(lambda r: _num(r, "estimatedRevenue"), cur),
        "revenue_prev": kpi(lambda r: _num(r, "estimatedRevenue"), prev) if prev else None,
        "likes": int(_sum(cur, "likes")),
        "comments": int(_sum(cur, "comments")),
        "shares": int(_sum(cur, "shares")),
    }
    views = k["views"] or 0
    k["rpm"] = round(k["revenue"] / views * 1000, 2) if views else None
    playbacks = _sum(cur, "monetizedPlaybacks")
    k["cpm"] = round(sum(_num(r, "playbackBasedCpm") * _num(r, "monetizedPlaybacks") for r in cur) / playbacks, 2) \
        if playbacks else None
    avg = [_num(r, "averageViewDuration") for r in cur if _num(r, "views")]
    k["avg_view_s"] = round(sum(avg) / len(avg)) if avg else None

    b = snap.get("breakdowns", {}).get(str(days), {})
    titles = {r["id"]: r for r in db.query("SELECT * FROM yt_videos")}
    top = []
    for r in b.get("top_videos", []):
        v = titles.get(r.get("video"), {})
        top.append({
            "id": r.get("video"), "title": v["title"] if v else r.get("video"),
            "thumbnail": v["thumbnail"] if v else "", "published_at": v["published_at"] if v else "",
            "is_short": bool(v["is_short"]) if v else None,
            "views": int(_num(r, "views")), "hours": round(_num(r, "estimatedMinutesWatched") / 60, 1),
            "avg_pct": round(_num(r, "averageViewPercentage"), 1), "subs": int(_num(r, "subscribersGained")),
        })
    streamer_of = {r["youtube_id"]: r["login"] for r in db.query(
        "SELECT youtube_id, login FROM clips WHERE youtube_id IS NOT NULL")}
    for t in top:
        t["streamer"] = streamer_of.get(t["id"])

    return {
        "ready": True,
        "days": days,
        "fetched_at": snap.get("fetched_at"),
        "currency": snap.get("currency", "BRL"),
        "channel": prof,
        "monetization": snap.get("monetization", {}),
        "ypp": snap.get("ypp", {}),
        "kpis": k,
        "series": series,
        "traffic": [{"name": r.get("insightTrafficSourceType"), "views": int(_num(r, "views"))} for r in b.get("traffic", [])],
        "countries": [{"name": r.get("country"), "views": int(_num(r, "views"))} for r in b.get("countries", [])],
        "devices": [{"name": r.get("deviceType"), "views": int(_num(r, "views"))} for r in b.get("devices", [])],
        "ages": _ages(b.get("demographics", [])),
        "genders": _genders(b.get("demographics", [])),
        "content_type": [{"name": r.get("creatorContentType"), "views": int(_num(r, "views")),
                          "hours": round(_num(r, "estimatedMinutesWatched") / 60, 1)} for r in b.get("content_type", [])],
        "top_videos": top,
        "streamers": _streamer_performance(db),
        "videos": _recent_videos(db, streamer_of),
        "errors": snap.get("errors", {}),
        "bot": bot,
    }


def _ages(rows: list[dict]) -> list[dict]:
    order = ["age13-17", "age18-24", "age25-34", "age35-44", "age45-54", "age55-64", "age65-"]
    acc: dict[str, float] = {}
    for r in rows:
        acc[r.get("ageGroup", "")] = acc.get(r.get("ageGroup", ""), 0) + _num(r, "viewerPercentage")
    return [{"name": a.replace("age", "").replace("-", "–").rstrip("–") + ("+" if a.endswith("-") else ""),
             "pct": round(acc[a], 1)} for a in order if a in acc]


def _genders(rows: list[dict]) -> list[dict]:
    acc: dict[str, float] = {}
    for r in rows:
        acc[r.get("gender", "")] = acc.get(r.get("gender", ""), 0) + _num(r, "viewerPercentage")
    names = {"male": "Masculino", "female": "Feminino", "user_specified": "Outro"}
    return [{"name": names.get(g, g), "pct": round(p, 1)} for g, p in sorted(acc.items(), key=lambda x: -x[1])]


def _streamer_performance(db: DB) -> list[dict]:
    rows = db.query(
        "SELECT c.login, COALESCE(s.display_name, c.login) AS name, COUNT(v.id) AS videos, "
        "COALESCE(SUM(v.views),0) AS views, COALESCE(SUM(v.likes),0) AS likes "
        "FROM clips c JOIN yt_videos v ON v.id=c.youtube_id LEFT JOIN streamers s ON s.login=c.login "
        "GROUP BY c.login ORDER BY views DESC"
    )
    return [{"login": r["login"], "name": r["name"], "videos": r["videos"], "views": r["views"],
             "likes": r["likes"], "avg_views": round(r["views"] / r["videos"]) if r["videos"] else 0} for r in rows]


def _recent_videos(db: DB, streamer_of: dict) -> list[dict]:
    rows = db.query("SELECT * FROM yt_videos ORDER BY published_at DESC LIMIT 200")
    return [{"id": r["id"], "title": r["title"], "published_at": r["published_at"], "views": r["views"],
             "likes": r["likes"], "comments": r["comments"], "thumbnail": r["thumbnail"],
             "is_short": bool(r["is_short"]), "privacy": r["privacy"], "streamer": streamer_of.get(r["id"])}
            for r in rows]


def _bot_status(db: DB, cfg: Config, now: datetime) -> dict:
    from .planner import quota_capacity, quota_day_start
    yc = cfg["youtube"]
    used = db.quota_used_today(quota_day_start(now))
    one = lambda sql, *p: (db.one(sql, p) or {"n": 0})["n"]  # noqa: E731
    day_start = iso(datetime.combine(now.astimezone(cfg.tz).date(), datetime.min.time(), tzinfo=cfg.tz))
    return {
        "live": one("SELECT COUNT(*) AS n FROM streamers WHERE tracked=1 AND is_live_gta=1"),
        "tracked": one("SELECT COUNT(*) AS n FROM streamers WHERE tracked=1"),
        "ready": one("SELECT COUNT(*) AS n FROM clips WHERE status='rendered'"),
        "posted_today": one("SELECT COUNT(*) AS n FROM uploads WHERE uploaded_at >= ? AND quota_cost > 0", day_start),
        "moments_today": one("SELECT COUNT(*) AS n FROM moments WHERE at_utc >= ?", day_start),
        "quota_used": used,
        "quota_total": yc["daily_quota"],
        "uploads_left": quota_capacity(yc["daily_quota"], used, yc["upload_cost"], yc["quota_reserve"]),
        "mode": yc.get("mode", "daily"),
    }
