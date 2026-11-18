import json
import subprocess
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from clipador.app import Clipador
from clipador.db import iso, utcnow
from clipador.discovery import discover, refresh_live, sync_seeds
from clipador.harvest import harvest_community, harvest_moments, record_moment
from clipador.media import MediaWorker
from clipador.publisher import export_day, run_daily
from clipador.web import create_app
from clipador.youtube import YouTube


def make_video(path: Path, seconds: int = 3, size: str = "1280x720") -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=30:duration={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-shortest",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(path)],
        check=True,
    )
    return path


def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


class FakeYouTube:
    def __init__(self):
        self.calls = []

    def upload(self, path, meta):
        assert Path(path).exists()
        self.calls.append((Path(path), meta))
        return f"yt{len(self.calls)}"


@pytest.fixture
def world(cfg, fake_tw):
    """3 streamers ao vivo em GTA VI, cada um com 2 clipes da comunidade."""
    app = Clipador(cfg)
    app._tw, app._game_id = fake_tw, "999"
    now = utcnow()
    started = iso(now - timedelta(hours=2))
    for i, login in enumerate(["alpha", "beta", "gamma"], 1):
        uid = str(i)
        fake_tw.streams.append({"id": f"s{i}", "user_id": uid, "user_login": login, "user_name": login.title(),
                                "game_id": "999", "viewer_count": 1000 * i, "started_at": started, "title": "GTA 6!"})
        fake_tw.clip_map[uid] = [
            {"id": f"{login}-c{j}", "url": f"https://clips.twitch.tv/{login}{j}", "title": f"lance {j} do {login}",
             "game_id": "999", "view_count": 100 * j * i, "duration": 20.0, "created_at": iso(now - timedelta(hours=1)),
             "video_id": f"v{i}", "vod_offset": 600 * j}
            for j in (1, 2)
        ] + [{"id": f"{login}-other", "url": "x", "title": "outro jogo", "game_id": "1", "view_count": 9999,
              "duration": 20.0, "created_at": iso(now), "video_id": None, "vod_offset": None}]
        fake_tw.archive_map[uid] = [{"id": f"v{i}", "stream_id": f"s{i}", "created_at": started,
                                     "url": f"https://www.twitch.tv/videos/v{i}", "duration": "2h0m0s"}]
    return app


def fake_download(media: MediaWorker, tmp: Path):
    src = make_video(tmp / "src.mp4")

    def download(clip):
        d = media.clip_dir(clip)
        out = d / "raw.mp4"
        out.write_bytes(src.read_bytes())
        media.db.update_clip(clip["id"], raw_path=str(out), status="downloaded")
        return out

    media.download = download


def test_full_pipeline(world, tmp_path):
    app, db, cfg = world, world.db, world.cfg
    assert sync_seeds(db, app.tw, cfg) == ["naoexiste"]
    discover(db, app.tw, cfg, "999")
    live = refresh_live(db, app.tw, "999")
    assert set(live) == {"alpha", "beta", "gamma"}
    assert {r["login"] for r in db.tracked_streamers()} == {"alpha", "beta", "gamma"}

    assert harvest_community(db, app.tw, cfg, "999") == 6       # ignora o clipe de outro jogo
    assert harvest_community(db, app.tw, cfg, "999") == 0       # idempotente

    # momento de hype 30 min após o início da live do beta → recorte do VOD
    at = (utcnow() - timedelta(hours=1, minutes=30)).timestamp()
    record_moment(db, "beta", live["beta"], at, 6.2, 80, ["KEKW", "kkkkk"])
    # momento que cai em cima de um clipe da comunidade (offset 600s) → descartado
    at_dup = (utcnow() - timedelta(hours=2) + timedelta(seconds=620)).timestamp()
    record_moment(db, "beta", live["beta"], at_dup, 5.0, 60, ["CLIPA"])
    assert harvest_moments(db, app.tw, cfg) == 1
    hype = db.one("SELECT * FROM clips WHERE source='hype'")
    assert hype["login"] == "beta" and 1700 < hype["start_s"] < 1800 and hype["end_s"] - hype["start_s"] == 55

    fake_download(app.media, tmp_path)
    assert app.media.process_pending() == 7
    vert = Path(db.one("SELECT vertical_path FROM clips LIMIT 1")["vertical_path"])
    v = next(s for s in probe(vert)["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (1080, 1920)

    # cota para 2 uploads: 1 compilação + 1 short
    cfg.raw["youtube"].update(daily_quota=3600, quota_reserve=0)
    yt = FakeYouTube()
    ids = run_daily(db, cfg, yt, app.media)
    assert ids == ["yt1", "yt2"]
    comp_path, comp_meta = yt.calls[0]
    assert comp_path.name.startswith("compilacao-")
    assert "Alpha" in comp_meta["snippet"]["description"] or "alpha" in comp_meta["snippet"]["description"]
    short_meta = yt.calls[1][1]
    assert short_meta["status"]["privacyStatus"] in ("private", "public")
    assert len(short_meta["snippet"]["title"]) <= 100

    # cota acabou → nada mais sobe hoje
    assert run_daily(db, cfg, FakeYouTube(), app.media) == []

    # com mais cota, sobe 1 por streamer que ainda não postou hoje
    cfg.raw["youtube"].update(daily_quota=100000)
    yt2 = FakeYouTube()
    run_daily(db, cfg, yt2, app.media)
    logins = [db.one("SELECT login FROM clips WHERE youtube_id=?", (f"yt{i}",)) for i in range(1, 3)]
    assert len(yt2.calls) == 2
    up_logins = [r["login"] for r in db.query("SELECT c.login FROM uploads u JOIN clips c ON c.id=u.clip_id")]
    assert sorted(up_logins) == ["alpha", "beta", "gamma"]       # 1 por streamer, sem repetir
    assert logins  # silencia lint


def test_upload_only_authorized_and_manual_approval(world, tmp_path):
    app, db, cfg = world, world.db, world.cfg
    sync_seeds(db, app.tw, cfg); discover(db, app.tw, cfg, "999"); refresh_live(db, app.tw, "999")
    harvest_community(db, app.tw, cfg, "999")
    fake_download(app.media, tmp_path)
    app.media.process_pending()
    cfg.raw["youtube"].update(daily_quota=100000, upload_only_authorized=True)
    cfg.raw["youtube"]["compilation"]["enabled"] = False
    assert run_daily(db, cfg, FakeYouTube(), app.media) == []    # ninguém autorizou
    db.execute("UPDATE streamers SET authorized=1 WHERE login='gamma'")
    cfg.raw["youtube"]["auto_approve"] = False
    assert run_daily(db, cfg, FakeYouTube(), app.media) == []    # falta aprovar
    db.execute("UPDATE clips SET approved=1 WHERE login='gamma'")
    assert len(run_daily(db, cfg, FakeYouTube(), app.media)) == 1


def test_export_for_manual_posting(world, tmp_path):
    app, db, cfg = world, world.db, world.cfg
    sync_seeds(db, app.tw, cfg); discover(db, app.tw, cfg, "999"); refresh_live(db, app.tw, "999")
    harvest_community(db, app.tw, cfg, "999")
    fake_download(app.media, tmp_path)
    app.media.process_pending()
    out = export_day(db, cfg)
    manifest = json.loads((out / "postagens.json").read_text(encoding="utf-8"))
    assert len(manifest) == 3 and all((out / m["arquivo"]).exists() for m in manifest)
    assert "twitch.tv/" in manifest[0]["descricao"]


def test_dashboard(world, tmp_path):
    app, db, cfg = world, world.db, world.cfg
    sync_seeds(db, app.tw, cfg); discover(db, app.tw, cfg, "999"); refresh_live(db, app.tw, "999")
    harvest_community(db, app.tw, cfg, "999")
    fake_download(app.media, tmp_path)
    app.media.process_pending()
    client = TestClient(create_app(app))
    r = client.get("/")
    assert r.status_code == 200 and "Gamma" in r.text and "AO VIVO" in r.text
    r = client.get("/s/beta")
    assert r.status_code == 200 and "lance 2 do beta" in r.text
    clip_id = db.one("SELECT id FROM clips WHERE login='beta'")["id"]
    r = client.post(f"/clip/{clip_id}/titulo", data={"titulo": "Título novo", "voltar": "/s/beta"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/s/beta"
    client.post(f"/clip/{clip_id}/rejeitar", data={"voltar": "//evil.com"})
    row = db.one("SELECT approved, custom_title FROM clips WHERE id=?", (clip_id,))
    assert row["approved"] == 0 and row["custom_title"] == "Título novo"
    assert client.get(f"/media/{clip_id}/vertical").status_code == 200
    assert client.get("/fila").status_code == 200
    assert client.get("/s/ninguem").status_code == 404


def test_dashboard_password(world, monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "segredo")
    client = TestClient(create_app(world))
    assert client.get("/").status_code == 401
    assert client.get("/", auth=("admin", "segredo")).status_code == 200


def test_youtube_resumable_upload(tmp_path):
    token = tmp_path / "tok.json"
    token.write_text(json.dumps({"refresh_token": "r"}))
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x" * 1000)
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "a", "expires_in": 3600})
        if req.method == "POST":
            seen["meta"] = json.loads(req.content)
            seen["len"] = req.headers["X-Upload-Content-Length"]
            return httpx.Response(200, headers={"Location": "https://upload.example/sess"})
        assert req.headers["Content-Range"] == "bytes 0-999/1000"
        return httpx.Response(200, json={"id": "abc123"})

    yt = YouTube("id", "secret", token, http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert yt.upload(video, {"snippet": {"title": "t"}}) == "abc123"
    assert seen == {"meta": {"snippet": {"title": "t"}}, "len": "1000"}


def test_youtube_quota_error_is_explained(tmp_path):
    token = tmp_path / "tok.json"
    token.write_text(json.dumps({"refresh_token": "r"}))
    (tmp_path / "v.mp4").write_bytes(b"x")

    def handler(req):
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "a", "expires_in": 3600})
        return httpx.Response(403, json={"error": {"errors": [{"reason": "quotaExceeded"}], "message": "q"}})

    yt = YouTube("id", "s", token, http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(Exception, match="quotaExceeded"):
        yt.upload(tmp_path / "v.mp4", {})


def test_youtube_branding_update(tmp_path):
    token = tmp_path / "tok.json"
    token.write_text(json.dumps({"refresh_token": "r"}))
    banner = tmp_path / "b.png"
    banner.write_bytes(b"png")
    sent = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "a", "expires_in": 3600})
        if "channelBanners" in req.url.path:
            assert req.headers["Content-Type"] == "image/png" and req.content == b"png"
            return httpx.Response(200, json={"url": "https://banner/1"})
        if req.method == "GET":
            return httpx.Response(200, json={"items": [{"id": "UC1", "brandingSettings": {
                "channel": {"title": "Velho", "unsubscribedTrailer": "vid"}}}]})
        sent.update(json.loads(req.content))
        return httpx.Response(200, json=sent)

    yt = YouTube("id", "s", token, http=httpx.Client(transport=httpx.MockTransport(handler)))
    url = yt.upload_banner(banner)
    yt.update_branding("Descrição <nova>", ["GTA 6", "cortes"], url)
    ch = sent["brandingSettings"]["channel"]
    assert sent["id"] == "UC1"
    assert ch["title"] == "Velho" and ch["unsubscribedTrailer"] == "vid"   # preserva o que já existia
    assert ch["keywords"] == '"GTA 6" cortes' and ch["country"] == "BR"
    assert ch["description"] == "Descrição nova"
    assert sent["brandingSettings"]["image"] == {"bannerExternalUrl": "https://banner/1"}


def test_export_single_streamer_all_clips(world, tmp_path):
    app, db, cfg = world, world.db, world.cfg
    sync_seeds(db, app.tw, cfg); discover(db, app.tw, cfg, "999"); refresh_live(db, app.tw, "999")
    harvest_community(db, app.tw, cfg, "999")
    fake_download(app.media, tmp_path)
    app.media.process_pending()
    out = export_day(db, cfg, login="beta", all_clips=True)
    manifest = json.loads((out / "postagens.json").read_text(encoding="utf-8"))
    assert [m["arquivo"].split("_")[1] for m in manifest] == ["beta", "beta"]     # os 2 clipes do beta
    assert out.name.endswith("_beta")
    desc = manifest[0]["descricao"]
    assert desc.split()[-8:][0] == "#beta" and "#gta6" in desc and "twitch.tv/beta" in desc
    # segunda rodada no mesmo dia: pasta nova, não apaga a primeira; beta já exportado
    out2 = export_day(db, cfg)
    assert out2 != out and (out / "postagens.json").exists()
    assert {m["arquivo"].split("_")[1] for m in json.loads((out2 / "postagens.json").read_text())} == {"alpha", "gamma"}


def test_hashtags_streamer_first_and_capped():
    from clipador.metadata import make_hashtags
    tags = make_hashtags("loud_coringa", ["#gta6", "gta6", "#GTA6", "#shorts"] + [f"#t{i}" for i in range(20)])
    assert tags[:3] == ["#loudcoringa", "#gta6", "#shorts"] and len(tags) == 15
