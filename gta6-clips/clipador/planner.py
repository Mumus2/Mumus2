"""Planejamento diário: quais clipes sobem hoje e em que horário.

Regras:
- No máximo 1 clipe por streamer por dia (rodízio justo).
- Streamers com menos vídeos postados até agora têm prioridade, depois quem tem
  `priority` maior, depois o clipe com maior nota.
- Respeita a cota da YouTube Data API (cada upload custa ~1600 unidades).
- Distribui as publicações ao longo do dia nos horários configurados.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")  # a cota do YouTube zera à meia-noite do Pacífico


@dataclass
class Candidate:
    clip_id: int
    login: str
    score: float
    priority: int = 1
    uploads_so_far: int = 0


def quota_capacity(daily_quota: int, used: int, cost: int, reserve: int = 0) -> int:
    return max(0, (daily_quota - reserve - used) // cost)


def quota_day_start(now_utc: datetime) -> datetime:
    local = now_utc.astimezone(PACIFIC)
    return datetime.combine(local.date(), time(0), tzinfo=PACIFIC)


def pick_clips(cands: list[Candidate], limit: int) -> list[Candidate]:
    best: dict[str, Candidate] = {}
    for c in cands:
        cur = best.get(c.login)
        if cur is None or c.score > cur.score:
            best[c.login] = c
    ordered = sorted(best.values(), key=lambda c: (c.uploads_so_far, -c.priority, -c.score))
    return ordered[: max(limit, 0)]


def parse_slots(slots: list[str]) -> list[time]:
    out = []
    for s in slots:
        h, m = s.split(":")
        out.append(time(int(h), int(m)))
    return sorted(out)


def publish_times(n: int, day: date, slots: list[str], tz: ZoneInfo, now: datetime, margin_min: int = 20) -> list[datetime]:
    """n horários de publicação. Se faltar horário hoje, espalha entre os restantes
    e, se o dia já acabou, usa o dia seguinte."""
    if n <= 0:
        return []
    earliest = now + timedelta(minutes=margin_min)
    base = [datetime.combine(day, t, tzinfo=tz) for t in parse_slots(slots)]
    remaining = [d for d in base if d >= earliest]
    if not remaining:
        base = [d + timedelta(days=1) for d in base]
        remaining = base
    if n <= len(remaining):
        if n == 1:
            return [remaining[0]]
        idx = [round(i * (len(remaining) - 1) / (n - 1)) for i in range(n)]
        return [remaining[i] for i in idx]
    first, last = remaining[0], remaining[-1]
    if first == last:
        last = first + timedelta(hours=12)
    step = (last - first) / (n - 1)
    return [first + step * i for i in range(n)]


def window_bounds(local_now: datetime, start: str, end: str) -> tuple[datetime, datetime] | None:
    """Janela de postagem que contém local_now, ou None se estiver fora.
    Aceita janelas que passam da meia-noite (ex.: 09:00 → 01:00)."""
    s, e = parse_slots([start])[0], parse_slots([end])[0]
    tz = local_now.tzinfo
    today = local_now.date()
    candidates_ = []
    for day in (today - timedelta(days=1), today):
        ws = datetime.combine(day, s, tzinfo=tz)
        we = datetime.combine(day if e > s else day + timedelta(days=1), e, tzinfo=tz)
        candidates_.append((ws, we))
    for ws, we in candidates_:
        if ws <= local_now < we:
            return ws, we
    return None


def realtime_gap(now: datetime, window_end: datetime, capacity: int, min_gap_minutes: float) -> timedelta:
    """Intervalo entre uploads para a cota que sobrou durar até o fim da janela."""
    if capacity <= 0:
        return timedelta.max
    spread = (window_end - now) / capacity
    return max(spread, timedelta(minutes=min_gap_minutes))
