"""Linha de comando:  python -m clipador <comando>"""
from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import subprocess
import sys

from .config import Config, load_config


def _app(args):
    from .app import Clipador
    return Clipador(load_config(args.config))


def cmd_check(args) -> int:
    cfg = load_config(args.config)
    ok = True

    def line(good: bool, msg: str) -> None:
        nonlocal ok
        ok &= good
        print(("✅ " if good else "❌ ") + msg)

    line(shutil.which("ffmpeg") is not None, "ffmpeg instalado")
    ytdlp = subprocess.run([sys.executable, "-m", "yt_dlp", "--version"], capture_output=True, text=True)
    line(ytdlp.returncode == 0, f"yt-dlp {ytdlp.stdout.strip()}")
    from pathlib import Path
    line(Path(cfg["render"]["font_file"]).exists(), f"fonte {cfg['render']['font_file']}")
    try:
        app = _app(args)
        gid = app.game_id
        line(True, f"Twitch OK — '{cfg['twitch']['game_name']}' = game_id {gid}")
        from .discovery import sync_seeds
        bad = sync_seeds(app.db, app.tw, cfg)
        line(not bad, "streamers.yaml válido" + (f" (inexistentes: {', '.join(bad)})" if bad else ""))
    except Exception as e:  # noqa: BLE001
        line(False, f"Twitch: {e}")
    try:
        ch = _app(args).youtube().channel()
        line(bool(ch), f"YouTube OK — canal: {ch.get('snippet', {}).get('title', '?')}")
    except Exception as e:  # noqa: BLE001
        line(False, f"YouTube: {e}")
    return 0 if ok else 1


def cmd_discover(args) -> int:
    app = _app(args)
    app.job_discover()
    live = app.job_refresh_live()
    for s in app.db.tracked_streamers():
        flag = "🔴 AO VIVO" if s["login"] in live else ""
        print(f"{s['display_name'] or s['login']:<22} pico {s['peak_viewers']:>7}  {flag}")
    return 0


def cmd_harvest(args) -> int:
    _app(args).job_harvest()
    return 0


def cmd_process(args) -> int:
    print(f"{_app(args).media.process_pending()} clipes prontos")
    return 0


def cmd_plan(args) -> int:
    from .publisher import plan_today
    app = _app(args)
    plan = plan_today(app.db, app.cfg)
    for clip, when in plan:
        print(f"{when.astimezone(app.cfg.tz):%d/%m %H:%M}  {clip['login']:<18} #{clip['id']}  {clip['title'] or 'hype'}")
    if not plan:
        print("Nada para postar agora.")
    return 0


def cmd_post(args) -> int:
    ids = _app(args).job_daily(dry_run=args.dry_run)
    print(f"{len(ids)} vídeos enviados: {ids}")
    return 0


def cmd_export(args) -> int:
    from .publisher import export_day
    app = _app(args)
    print(f"Pasta pronta para postar manualmente: {export_day(app.db, app.cfg, args.count)}")
    return 0


def cmd_youtube_auth(args) -> int:
    from .youtube import authorize
    cfg = load_config(args.config)
    authorize(Config.env("YOUTUBE_CLIENT_ID"), Config.env("YOUTUBE_CLIENT_SECRET"),
              cfg.data_dir / "youtube_token.json", port=args.port, manual=args.manual)
    return 0


def cmd_web(args) -> int:
    import uvicorn
    from .web import create_app
    app = _app(args)
    uvicorn.run(create_app(app), host=app.cfg.web_host, port=app.cfg["web"]["port"])
    return 0


def cmd_run(args) -> int:
    app = _app(args)
    try:
        asyncio.run(app.run(with_web=not args.no_web))
    except KeyboardInterrupt:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="clipador", description="Cortes automáticos de GTA 6 dos streamers BR")
    p.add_argument("-c", "--config", help="caminho do config.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="testa ffmpeg, yt-dlp, Twitch e YouTube").set_defaults(fn=cmd_check)
    sub.add_parser("discover", help="descobre os maiores streamers BR em GTA 6").set_defaults(fn=cmd_discover)
    sub.add_parser("harvest", help="coleta clipes + recorta momentos + edita").set_defaults(fn=cmd_harvest)
    sub.add_parser("process", help="só baixa/edita candidatos pendentes").set_defaults(fn=cmd_process)
    sub.add_parser("plan", help="mostra o que seria postado agora").set_defaults(fn=cmd_plan)
    sp = sub.add_parser("post", help="faz a rodada de uploads no YouTube")
    sp.add_argument("--dry-run", action="store_true", help="só mostra, não envia")
    sp.set_defaults(fn=cmd_post)
    se = sub.add_parser("export", help="gera pasta com vídeos + títulos para postar à mão")
    se.add_argument("--count", type=int, default=30)
    se.set_defaults(fn=cmd_export)
    sa = sub.add_parser("youtube-auth", help="autoriza o canal do YouTube (uma vez)")
    sa.add_argument("--manual", action="store_true", help="servidor sem navegador: colar a URL de retorno")
    sa.add_argument("--port", type=int, default=8765)
    sa.set_defaults(fn=cmd_youtube_auth)
    sub.add_parser("web", help="só o painel web").set_defaults(fn=cmd_web)
    sr = sub.add_parser("run", help="roda TUDO 24h (robô + painel)")
    sr.add_argument("--no-web", action="store_true")
    sr.set_defaults(fn=cmd_run)

    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%d/%m %H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return args.fn(args)
