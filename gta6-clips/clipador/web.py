"""Painel web: clipes separados por streamer, aprovação, fila de postagem."""
from __future__ import annotations

import os
import secrets
import threading
from datetime import timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from .db import parse_iso, utcnow
from .planner import quota_capacity, quota_day_start

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
security = HTTPBasic(auto_error=False)

STATUS_PT = {
    "candidate": "na fila p/ baixar",
    "downloaded": "baixado",
    "rendered": "pronto",
    "scheduled": "agendado",
    "uploaded": "publicado",
    "exported": "exportado",
    "failed": "erro",
}


def create_app(app_state) -> FastAPI:
    cfg, db = app_state.cfg, app_state.db
    password = os.environ.get("DASHBOARD_PASSWORD", "")

    def auth(request: Request, creds: HTTPBasicCredentials | None = Depends(security)) -> None:
        if not password or request.url.path == "/api/saude":
            return
        ok = creds and secrets.compare_digest(creds.username, "admin") and secrets.compare_digest(
            creds.password, password
        )
        if not ok:
            raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})

    api = FastAPI(title="Clipador GTA 6", dependencies=[Depends(auth)])
    api.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

    def local(ts: str | None) -> str:
        if not ts:
            return ""
        return parse_iso(ts).astimezone(cfg.tz).strftime("%d/%m %H:%M")

    def status_of(clip) -> str:
        if clip["status"] == "scheduled" and clip["publish_at"] and parse_iso(clip["publish_at"]) <= utcnow():
            return "publicado"
        return STATUS_PT.get(clip["status"], clip["status"])

    TEMPLATES.env.filters["local"] = local
    TEMPLATES.env.globals["status_of"] = status_of

    @api.get("/", response_class=HTMLResponse)
    def index(request: Request):
        streamers = db.query(
            """SELECT s.*,
                 (SELECT COUNT(*) FROM clips c WHERE c.login=s.login) AS total,
                 (SELECT COUNT(*) FROM clips c WHERE c.login=s.login AND c.status='rendered') AS ready,
                 (SELECT COUNT(*) FROM clips c WHERE c.login=s.login AND c.status IN ('scheduled','uploaded','exported')) AS posted
               FROM streamers s WHERE s.tracked=1
               ORDER BY s.is_live_gta DESC, s.pinned DESC, s.peak_viewers DESC"""
        )
        yc = cfg["youtube"]
        used = db.quota_used_today(quota_day_start(utcnow()))
        moments = db.query("SELECT * FROM moments ORDER BY id DESC LIMIT 12")
        return TEMPLATES.TemplateResponse(request, "index.html", {
            "streamers": streamers,
            "quota_used": used,
            "quota_total": yc["daily_quota"],
            "uploads_left": quota_capacity(yc["daily_quota"], used, yc["upload_cost"], yc["quota_reserve"]),
            "moments": moments,
            "busy": sorted(app_state.busy),
            "live_count": sum(1 for s in streamers if s["is_live_gta"]),
        })

    @api.get("/s/{login}", response_class=HTMLResponse)
    def streamer(request: Request, login: str, filtro: str = "todos"):
        s = db.one("SELECT * FROM streamers WHERE login=?", (login.lower(),))
        if not s:
            raise HTTPException(404, "Streamer não encontrado")
        where = {
            "todos": "",
            "prontos": "AND status='rendered'",
            "postados": "AND status IN ('scheduled','uploaded','exported')",
            "erros": "AND status='failed'",
        }.get(filtro, "")
        clips = db.query(f"SELECT * FROM clips WHERE login=? {where} ORDER BY clip_created_at DESC, score DESC LIMIT 200",
                         (s["login"],))
        return TEMPLATES.TemplateResponse(request, "streamer.html", {"s": s, "clips": clips, "filtro": filtro})

    @api.get("/fila", response_class=HTMLResponse)
    def queue(request: Request):
        from .publisher import plan_today
        try:
            plan = plan_today(db, cfg)
            plan_error = None
        except Exception as e:  # noqa: BLE001
            plan, plan_error = [], str(e)
        uploads = db.query(
            "SELECT u.*, c.login FROM uploads u LEFT JOIN clips c ON c.id=u.clip_id ORDER BY u.id DESC LIMIT 60"
        )
        return TEMPLATES.TemplateResponse(request, "queue.html", {
            "plan": [(c, t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")) for c, t in plan],
            "plan_error": plan_error,
            "uploads": uploads,
        })

    @api.post("/clip/{clip_id}/aprovar")
    def approve(clip_id: int, voltar: str = Form("/")):
        db.update_clip(clip_id, approved=1)
        return RedirectResponse(_safe(voltar), status_code=303)

    @api.post("/clip/{clip_id}/rejeitar")
    def reject(clip_id: int, voltar: str = Form("/")):
        db.update_clip(clip_id, approved=0)
        return RedirectResponse(_safe(voltar), status_code=303)

    @api.post("/clip/{clip_id}/titulo")
    def set_title(clip_id: int, titulo: str = Form(""), voltar: str = Form("/")):
        db.update_clip(clip_id, custom_title=titulo.strip()[:100] or None)
        return RedirectResponse(_safe(voltar), status_code=303)

    @api.post("/clip/{clip_id}/refazer")
    def retry(clip_id: int, voltar: str = Form("/")):
        db.update_clip(clip_id, status="candidate", error=None)
        return RedirectResponse(_safe(voltar), status_code=303)

    @api.post("/streamer/{login}/autorizado")
    def toggle_authorized(login: str):
        db.execute("UPDATE streamers SET authorized = 1 - authorized WHERE login=?", (login,))
        return RedirectResponse(f"/s/{login}", status_code=303)

    @api.post("/acao/{name}")
    def action(request: Request, name: str):
        if name not in {"discover", "harvest", "daily", "realtime", "channel"}:
            raise HTTPException(404)
        threading.Thread(target=app_state.run_job, args=(name,), daemon=True).start()
        if request.headers.get("accept", "").startswith("application/json"):
            return JSONResponse({"ok": True, "job": name})
        return RedirectResponse("/canal" if name == "channel" else "/", status_code=303)

    # ---------- painel do canal ----------
    @api.get("/canal", response_class=HTMLResponse)
    def channel_page(request: Request):
        return TEMPLATES.TemplateResponse(request, "canal.html", {})

    @api.get("/api/canal")
    def channel_data(dias: int = 28):
        from .analytics import build_view
        data = build_view(db, cfg, dias)
        data["busy"] = sorted(app_state.busy)
        return JSONResponse(data)

    @api.get("/api/saude")
    def health():
        """Para o Docker/monitor saberem se o robô está de pé (não pede senha)."""
        from .analytics import load_snapshot
        snap = load_snapshot(db) or {}
        return {"ok": True, "canal_atualizado_em": snap.get("fetched_at"), "jobs_rodando": sorted(app_state.busy)}

    @api.get("/media/{clip_id}/{kind}")
    def media(clip_id: int, kind: str):
        col = {"vertical": "vertical_path", "horizontal": "horizontal_path", "raw": "raw_path"}.get(kind)
        if not col:
            raise HTTPException(404)
        row = db.one(f"SELECT {col} AS p FROM clips WHERE id=?", (clip_id,))
        if not row or not row["p"]:
            raise HTTPException(404)
        path = Path(row["p"]).resolve()
        if cfg.videos_dir.resolve() not in path.parents or not path.exists():
            raise HTTPException(404)
        return FileResponse(path, media_type="video/mp4")

    return api


def _safe(url: str) -> str:
    return url if url.startswith("/") and not url.startswith("//") else "/"
