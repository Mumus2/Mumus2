from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from clipador.db import iso
from clipador.planner import realtime_gap, window_bounds
from clipador.publisher import post_realtime

BRT = ZoneInfo("America/Sao_Paulo")


class FakeYT:
    def __init__(self):
        self.calls = []

    def upload(self, path, meta):
        self.calls.append(meta)
        return f"rt{len(self.calls)}"


def test_window_bounds_crossing_midnight():
    assert window_bounds(datetime(2026, 11, 19, 8, 59, tzinfo=BRT), "09:00", "01:00") is None
    ws, we = window_bounds(datetime(2026, 11, 19, 23, 0, tzinfo=BRT), "09:00", "01:00")
    assert (ws.day, ws.hour, we.day, we.hour) == (19, 9, 20, 1)
    ws, we = window_bounds(datetime(2026, 11, 20, 0, 30, tzinfo=BRT), "09:00", "01:00")
    assert (ws.day, we.day, we.hour) == (19, 20, 1)
    assert window_bounds(datetime(2026, 11, 19, 12, 0, tzinfo=BRT), "10:00", "22:00") is not None


def test_realtime_gap_spreads_quota():
    now = datetime(2026, 11, 19, 9, 0, tzinfo=BRT)
    end = datetime(2026, 11, 20, 1, 0, tzinfo=BRT)
    assert realtime_gap(now, end, 4, 10) == timedelta(hours=4)
    assert realtime_gap(now, end, 1000, 10) == timedelta(minutes=10)


def _setup(cfg):
    from clipador.db import DB
    db = DB(cfg.db_path)
    for login in ("a", "b"):
        db.upsert_streamer(login, display_name=login.upper(), user_id=login)
    return db


def _clip(db, cfg, login, score, created):
    p = cfg.videos_dir / f"{login}{score}.mp4"
    p.write_bytes(b"x")
    return db.add_clip(login=login, source="twitch_clip", source_id=f"{login}{score}", title=f"lance {login}",
                       url="u", score=score, clip_created_at=iso(created), status="rendered", vertical_path=str(p))


def test_post_realtime_posts_fresh_clips_paced_and_fair(cfg):
    db = _setup(cfg)
    yc = cfg.raw["youtube"]
    yc["compilation"]["enabled"] = False
    yc.update(daily_quota=1600 * 4, quota_reserve=0)        # 4 uploads hoje
    now = datetime(2026, 11, 19, 15, 0, tzinfo=BRT).astimezone(timezone.utc)
    _clip(db, cfg, "a", 9.0, now - timedelta(minutes=10))
    _clip(db, cfg, "a", 12.0, now - timedelta(minutes=5))
    _clip(db, cfg, "b", 5.0, now - timedelta(minutes=3))
    _clip(db, cfg, "b", 50.0, now - timedelta(hours=8))       # velho demais para "tempo real"
    yt = FakeYT()

    assert post_realtime(db, cfg, yt, now) == "rt1"           # melhor clipe recente: a (12)
    assert "lance a" in yt.calls[0]["snippet"]["title"]
    assert "publishAt" not in yt.calls[0]["status"]           # público na hora
    assert post_realtime(db, cfg, yt, now + timedelta(minutes=5)) is None   # respeita o ritmo
    # 10h restantes / 3 uploads ≈ 3h20 depois
    assert post_realtime(db, cfg, yt, now + timedelta(hours=3, minutes=30)) == "rt2"
    assert "lance b" in yt.calls[1]["snippet"]["title"]       # rodízio: b ainda não postou hoje
    # os dois já postaram hoje (limite 1/dia) → nada
    assert post_realtime(db, cfg, yt, now + timedelta(hours=7)) is None


def test_post_realtime_outside_window_and_reserves_compilation(cfg):
    db = _setup(cfg)
    yc = cfg.raw["youtube"]
    night = datetime(2026, 11, 19, 3, 0, tzinfo=BRT).astimezone(timezone.utc)
    _clip(db, cfg, "a", 9.0, night - timedelta(minutes=1))
    assert post_realtime(db, cfg, FakeYT(), night) is None    # fora da janela 09:00–01:00
    day = datetime(2026, 11, 19, 12, 0, tzinfo=BRT).astimezone(timezone.utc)
    _clip(db, cfg, "a", 10.0, day - timedelta(minutes=1))
    yc.update(daily_quota=1600, quota_reserve=0)              # só 1 upload: fica para a compilação
    assert post_realtime(db, cfg, FakeYT(), day) is None
    yc["compilation"]["enabled"] = False
    assert post_realtime(db, cfg, FakeYT(), day) == "rt1"
