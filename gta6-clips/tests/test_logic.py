from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from clipador.chat import parse_privmsg
from clipador.discovery import select_tracked
from clipador.hype import HypeDetector, clip_window, hype_weight
from clipador.metadata import fit_title, make_tags, make_title
from clipador.planner import Candidate, pick_clips, publish_times, quota_capacity
from clipador.twitch import parse_twitch_duration
from clipador.youtube import build_metadata

BRT = ZoneInfo("America/Sao_Paulo")


# ---------------- detector de hype ----------------
def _simulate(det, start, seconds, per_sec, text="oi", channel="c"):
    moments = []
    for s in range(seconds):
        t = start + s
        for i in range(per_sec):
            det.feed(channel, t + i / max(per_sec, 1), text)
        moments += det.tick(t + 1)
    return moments


def test_hype_detects_burst_once():
    det = HypeDetector(z_threshold=3.5, min_messages_per_window=25, cooldown_seconds=90)
    assert _simulate(det, 0, 300, 1) == []                # chat calmo: 1 msg/s
    burst = _simulate(det, 300, 12, 12, text="KKKKKKKK")   # explosão de risada
    burst += _simulate(det, 312, 40, 1)                    # volta ao normal
    assert len(burst) == 1
    m = burst[0]
    assert m.channel == "c" and m.score >= 3.5
    assert 290 <= m.at <= 312                              # início da explosão
    assert any("KKKK" in s for s in m.sample)


def test_hype_respects_warmup_and_cooldown():
    det = HypeDetector(cooldown_seconds=200)
    assert _simulate(det, 0, 20, 30) == []                 # ainda aquecendo
    det = HypeDetector(cooldown_seconds=200)
    _simulate(det, 0, 300, 1)
    first = _simulate(det, 300, 10, 15, "CLIPA") + _simulate(det, 310, 30, 1)
    second = _simulate(det, 340, 10, 15, "CLIPA") + _simulate(det, 350, 30, 1)
    assert len(first) == 1 and second == []


def test_hype_ignores_busy_but_steady_chat():
    det = HypeDetector()
    assert _simulate(det, 0, 400, 20) == []                # canal grande, chat sempre rápido


def test_hype_weight_and_clip_window():
    assert hype_weight("oi", 0.6) == 1.0
    assert hype_weight("kkkkkk", 0.6) > 1.0
    assert hype_weight("CLIPA ISSO", 0.6) > hype_weight("kkkkkk", 0.6)
    assert clip_window(100, 40, 15) == (60.0, 115.0)
    assert clip_window(10, 40, 15) == (0.0, 25.0)
    assert clip_window(200, 80, 15, max_len=60) == (155.0, 215.0)


# ---------------- parsers ----------------
def test_parse_privmsg():
    line = ":fulano!fulano@fulano.tmi.twitch.tv PRIVMSG #Gaules :KEKW que isso : kkk"
    assert parse_privmsg(line) == ("gaules", "KEKW que isso : kkk")
    tagged = "@badge-info=;color=#FF0000 :a!a@a.tmi.twitch.tv PRIVMSG #x :oi"
    assert parse_privmsg(tagged) == ("x", "oi")
    assert parse_privmsg(":tmi.twitch.tv 001 justinfan :Welcome") is None


def test_parse_twitch_duration():
    assert parse_twitch_duration("3h8m33s") == 11313
    assert parse_twitch_duration("45s") == 45
    assert parse_twitch_duration("2m") == 120


def test_select_tracked_keeps_pinned_then_top():
    rows = [
        {"login": "p", "pinned": 1, "peak_viewers": 10, "last_viewers": 0},
        {"login": "a", "pinned": 0, "peak_viewers": 900, "last_viewers": 0},
        {"login": "b", "pinned": 0, "peak_viewers": 5000, "last_viewers": 0},
        {"login": "c", "pinned": 0, "peak_viewers": 100, "last_viewers": 0},
    ]
    assert select_tracked(rows, 3) == {"p", "b", "a"}


# ---------------- planejamento ----------------
def test_quota_capacity():
    assert quota_capacity(10000, 0, 1600, 400) == 6
    assert quota_capacity(10000, 9000, 1600, 400) == 0


def test_pick_clips_one_per_streamer_fair_rotation():
    cands = [
        Candidate(1, "a", 9.0, uploads_so_far=5),
        Candidate(2, "a", 12.0, uploads_so_far=5),
        Candidate(3, "b", 4.0, uploads_so_far=0),
        Candidate(4, "c", 7.0, uploads_so_far=1),
    ]
    picked = pick_clips(cands, 2)
    assert [c.clip_id for c in picked] == [3, 4]          # quem postou menos vem antes
    assert [c.clip_id for c in pick_clips(cands, 10)] == [3, 4, 2]  # melhor clipe do "a"


def test_publish_times_spreads_over_remaining_slots():
    slots = ["10:00", "14:00", "18:00", "22:00"]
    now = datetime(2026, 11, 19, 8, 0, tzinfo=BRT)
    times = publish_times(2, date(2026, 11, 19), slots, BRT, now)
    assert [t.hour for t in times] == [10, 22]
    late = datetime(2026, 11, 19, 15, 0, tzinfo=BRT)
    times = publish_times(5, date(2026, 11, 19), slots, BRT, late)
    assert len(times) == 5 and times[0].hour == 18 and times[-1].hour == 22
    assert times == sorted(times)
    night = datetime(2026, 11, 19, 23, 50, tzinfo=BRT)
    assert publish_times(1, date(2026, 11, 19), slots, BRT, night)[0].day == 20


# ---------------- metadados ----------------
def test_titles_are_valid_for_youtube():
    long = "a" * 300 + " <script>"
    t = fit_title(long, " | GTA 6")
    assert len(t) <= 100 and "<" not in t and t.endswith("| GTA 6")
    clip = {"id": 1, "source": "twitch_clip", "title": "ele caiu do prédio KKKK"}
    assert make_title(clip, "Gaules", " | GTA 6") == "Gaules: ele caiu do prédio KKKK | GTA 6"
    clip = {"id": 1, "source": "twitch_clip", "title": "GAULES PERDEU TUDO"}
    assert make_title(clip, "Gaules", " | GTA 6").startswith("GAULES PERDEU TUDO")
    hype = make_title({"id": 7, "source": "hype"}, "Alan", " | GTA 6", "kkkkkkk")
    assert "ALAN" in hype.upper() and len(hype) <= 100
    assert make_title({"id": 1, "custom_title": "Meu título"}, "x", " | GTA 6") == "Meu título"


def test_tags_unique_and_short():
    tags = make_tags(["gta 6", "GTA 6", "cortes"], "gaules", "Gaules")
    assert len({t.lower() for t in tags}) == len(tags)
    assert sum(len(t) + 1 for t in tags) <= 500


def test_build_metadata_scheduling():
    now = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
    future = datetime(2026, 11, 19, 15, tzinfo=timezone.utc)
    m = build_metadata("t", "d", [], "20", "public", future, False, now=now)
    assert m["status"]["privacyStatus"] == "private"
    assert m["status"]["publishAt"] == "2026-11-19T15:00:00.000Z"
    m = build_metadata("t", "d", [], "20", "public", now, False, now=now)
    assert m["status"] == {"selfDeclaredMadeForKids": False, "containsSyntheticMedia": False, "privacyStatus": "public"}
