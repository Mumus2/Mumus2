import json
from datetime import date, timedelta
from urllib.parse import parse_qs

import httpx
from fastapi.testclient import TestClient

from clipador.analytics import build_view, collect, parse_iso_duration, rows_to_dicts
from clipador.app import Clipador
from clipador.youtube import YouTube

TODAY = date(2026, 12, 20)


def fake_google(monetized=True, deny_revenue=False, broken=()):
    """Simula Data API + Analytics API. `broken`: relatórios (dimensões) que devem falhar."""
    def handler(req: httpx.Request) -> httpx.Response:
        q = {k: v[0] for k, v in parse_qs(req.url.query.decode()).items()}
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "a", "expires_in": 3600})
        path = req.url.path
        if path.endswith("/channels"):
            return httpx.Response(200, json={"items": [{
                "id": "UC1",
                "snippet": {"title": "Clipou! • Cortes de GTA 6", "customUrl": "@clipoubr", "description": "Cortes",
                            "publishedAt": "2026-11-18T10:00:00Z", "country": "BR",
                            "thumbnails": {"high": {"url": "https://yt3/avatar.jpg"}}},
                "statistics": {"subscriberCount": "1500", "viewCount": "2500000", "videoCount": "3"},
                "contentDetails": {"relatedPlaylists": {"uploads": "UU1"}},
                "brandingSettings": {"image": {"bannerExternalUrl": "https://yt3/banner"}},
                "status": {"privacyStatus": "public", "longUploadsStatus": "allowed"},
            }]})
        if path.endswith("/playlistItems"):
            return httpx.Response(200, json={"items": [{"contentDetails": {"videoId": v}} for v in ("v1", "v2", "v3")]})
        if path.endswith("/videos"):
            ids = q["id"].split(",")
            return httpx.Response(200, json={"items": [{
                "id": v, "snippet": {"title": f"Vídeo {v}", "publishedAt": "2026-12-01T12:00:00Z",
                                     "thumbnails": {"medium": {"url": f"https://i.ytimg/{v}.jpg"}}},
                "statistics": {"viewCount": str(1000 * (i + 1)), "likeCount": "10", "commentCount": "2"},
                "contentDetails": {"duration": "PT45S" if v != "v3" else "PT12M3S"},
                "status": {"privacyStatus": "public"},
            } for i, v in enumerate(ids)]})
        if "youtubeanalytics" in req.url.host:
            dims, metrics = q.get("dimensions", ""), q["metrics"].split(",")
            if dims in broken:
                return httpx.Response(500, text="erro interno")
            if "estimatedRevenue" in metrics and deny_revenue:
                return httpx.Response(403, json={"error": {"message": "Insufficient permission"}})
            headers = [{"name": d} for d in dims.split(",") if d] + [{"name": m} for m in metrics]
            start, end = date.fromisoformat(q["startDate"]), date.fromisoformat(q["endDate"])
            if dims == "day":
                rows = []
                d = start
                while d <= end:
                    i = (d - start).days
                    if "estimatedRevenue" in metrics:
                        rev = 1.5 if monetized else 0
                        rows.append([d.isoformat(), rev, rev * .8, rev * 1.2, 4.0, 3.0, 100 if monetized else 0])
                    else:
                        rows.append([d.isoformat(), 100 + i, 60 * (1 + i % 3), 30, 5, 1, 7, 1, 1])
                    d += timedelta(days=1)
            elif dims == "creatorContentType":
                rows = [["shorts", 900000, 10000], ["videoOnDemand", 50000, 120000]]
            elif dims == "insightTrafficSourceType":
                rows = [["SHORTS", 800, 100], ["YT_SEARCH", 200, 50]]
            elif dims == "country":
                rows = [["BR", 900, 100], ["PT", 50, 5]]
            elif dims == "deviceType":
                rows = [["MOBILE", 900], ["DESKTOP", 100]]
            elif dims == "ageGroup,gender":
                rows = [["age18-24", "male", 40.0], ["age18-24", "female", 10.0], ["age25-34", "male", 50.0]]
            elif dims == "video":
                rows = [["v2", 2000, 30, 85.5, 4], ["v1", 1000, 10, 70.0, 1]]
            else:
                rows = []
            return httpx.Response(200, json={"columnHeaders": headers, "rows": rows})
        return httpx.Response(404, text=path)
    return handler


def make_yt(tmp_path, handler):
    token = tmp_path / "tok.json"
    token.write_text(json.dumps({"refresh_token": "r"}))
    return YouTube("id", "s", token, http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_helpers():
    assert parse_iso_duration("PT1M5S") == 65 and parse_iso_duration("PT2H") == 7200 and parse_iso_duration("") == 0
    assert rows_to_dicts({"columnHeaders": [{"name": "a"}, {"name": "b"}], "rows": [[1, 2]]}) == [{"a": 1, "b": 2}]
    assert rows_to_dicts({"columnHeaders": [{"name": "a"}]}) == []


def test_collect_and_view_monetized(cfg, tmp_path):
    app = Clipador(cfg)
    db = app.db
    # um corte nosso publicado → aparece em "desempenho por streamer"
    db.upsert_streamer("gaules", display_name="Gaules")
    cid = db.add_clip(login="gaules", source="twitch_clip", source_id="x", url="u", score=1)
    db.update_clip(cid, youtube_id="v2", status="scheduled")

    snap = collect(db, cfg, make_yt(tmp_path, fake_google()), today=TODAY)
    assert snap["errors"] == {}
    assert snap["channel"]["subscribers"] == 1500 and snap["channel"]["handle"] == "@clipoubr"
    assert len(snap["daily"]) == 365 and snap["monetization"]["status"] == "active"
    assert snap["ypp"] == {"subscribers": 1500, "long_hours_12m": 2000.0, "shorts_views_90d": 900000, "approximate": False}

    v = build_view(db, cfg, 28)
    assert v["ready"] and v["days"] == 28 and len(v["series"]) == 28
    k = v["kpis"]
    assert k["views"] == sum(100 + i for i in range(337, 365))
    assert k["views_prev"] == sum(100 + i for i in range(309, 337))
    assert k["subs_net"] == 28 * 4 and k["revenue"] == 42.0 and k["cpm"] == 3.0   # +5 −1 por dia
    assert k["rpm"] == round(42 / k["views"] * 1000, 2)
    # total de inscritos reconstruído: último dia = total atual, cresce 4/dia
    assert v["series"][-1]["subs_total"] == 1500 and v["series"][-2]["subs_total"] == 1496
    assert v["streamers"] == [{"login": "gaules", "name": "Gaules", "videos": 1, "views": 2000, "likes": 10, "avg_views": 2000}]
    assert v["top_videos"][0]["streamer"] == "gaules" and v["top_videos"][0]["title"] == "Vídeo v2"
    assert {r["is_short"] for r in v["videos"]} == {True, False}
    assert v["ages"] == [{"name": "18–24", "pct": 50.0}, {"name": "25–34", "pct": 50.0}]
    assert v["genders"][0] == {"name": "Masculino", "pct": 90.0}
    assert build_view(db, cfg, 999)["days"] == 28          # período inválido cai no padrão
    year = build_view(db, cfg, 365)["series"]
    assert year[0]["subs_total"] == 1500 - 364 * 4          # total reconstruído para trás
    # contagem pública arredondada (menor que a soma do Analytics) → nunca fica negativo
    from clipador.analytics import _save, load_snapshot
    snap2 = load_snapshot(db)
    snap2["channel"]["subscribers"] = 100
    _save(db, snap2)
    year = build_view(db, cfg, 365)["series"]
    assert min(r["subs_total"] for r in year) == 0 and year[-1]["subs_total"] == 100


def test_collect_survives_failures_and_no_monetization(cfg, tmp_path):
    db = Clipador(cfg).db
    snap = collect(db, cfg, make_yt(tmp_path, fake_google(monetized=False, broken=("country", "creatorContentType"))),
                   today=TODAY)
    assert snap["monetization"]["status"] == "inactive"
    assert set(snap["errors"]) == {f"paises_{d}" for d in (7, 28, 90, 365)} | {f"formato_{d}" for d in (7, 28, 90, 365)}
    assert snap["ypp"]["approximate"] is True                 # sem recorte por formato → estimativa
    v = build_view(db, cfg, 7)
    assert v["countries"] == [] and v["traffic"] and v["kpis"]["rpm"] == 0.0

    snap = collect(db, cfg, make_yt(tmp_path, fake_google(deny_revenue=True)), today=TODAY)
    assert snap["monetization"]["status"] == "no_permission"
    assert "youtube-auth" in snap["errors"]["receita"]


def test_collect_without_channel(cfg, tmp_path):
    def handler(req):
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "a", "expires_in": 3600})
        return httpx.Response(200, json={"items": []})
    db = Clipador(cfg).db
    snap = collect(db, cfg, make_yt(tmp_path, handler), today=TODAY)
    assert "canal" in snap["errors"] and "channel" not in snap


def test_dashboard_routes(cfg, tmp_path, monkeypatch):
    from clipador.web import create_app
    app = Clipador(cfg)
    client = TestClient(create_app(app))
    assert client.get("/api/canal").json()["ready"] is False          # antes da 1ª coleta
    page = client.get("/canal")
    assert page.status_code == 200 and "canal.js" in page.text and "Caminho para a monetização" in page.text
    assert client.get("/static/canal.js").status_code == 200
    collect(app.db, cfg, make_yt(tmp_path, fake_google()), today=TODAY)
    data = client.get("/api/canal?dias=90").json()
    assert data["ready"] and data["days"] == 90 and data["channel"]["title"].startswith("Clipou")
    assert "bot" in data and data["bot"]["mode"] == "realtime"

    monkeypatch.setenv("DASHBOARD_PASSWORD", "x")
    locked = TestClient(create_app(app))
    assert locked.get("/api/canal").status_code == 401
    assert locked.get("/api/saude").json()["ok"] is True                # health check sem senha
    r = locked.post("/acao/channel", headers={"accept": "application/json"}, auth=("admin", "x"))
    assert r.json() == {"ok": True, "job": "channel"}
