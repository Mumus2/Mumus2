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
    out = export_day(app.db, app.cfg, args.count, login=args.streamer, all_clips=args.todos)
    n = len(list(out.glob("*.mp4")))
    if not n:
        print("Nenhum clipe pronto para exportar agora" + (f" do {args.streamer}." if args.streamer else ".")
              + " Veja no painel se há clipes em 'Prontos'.")
    else:
        print(f"✅ {n} vídeo(s) prontos em: {out}")
        print("   Abra no Windows com:  explorer.exe " + str(out.relative_to(app.cfg.root)))
    return 0
    return 0


def cmd_youtube_auth(args) -> int:
    from .youtube import authorize
    cfg = load_config(args.config)
    authorize(Config.env("YOUTUBE_CLIENT_ID"), Config.env("YOUTUBE_CLIENT_SECRET"),
              cfg.data_dir / "youtube_token.json", port=args.port, manual=args.manual)
    return 0


def cmd_brand(args) -> int:
    """Aplica a identidade do canal (branding/canal.yaml) via API."""
    import yaml
    from pathlib import Path
    app = _app(args)
    brand_dir = app.cfg.root / "branding"
    data = yaml.safe_load((brand_dir / "canal.yaml").read_text(encoding="utf-8"))
    yt = app.youtube()
    banner_url = None if args.no_banner else yt.upload_banner(brand_dir / data.get("banner", "banner.png"))
    yt.update_branding(data["descricao"], data["palavras_chave"], banner_url)
    print("✅ Descrição, palavras-chave, país e" + (" banner" if banner_url else "") + " aplicados.")
    print("Falta fazer à mão no YouTube Studio (a API não permite):")
    print(f"  • Nome do canal: {data['nome']}   • Identificador: {data['handle']}")
    print(f"  • Foto de perfil: {Path(brand_dir / 'avatar.png')}")
    print(f"  • Marca d'água dos vídeos: {Path(brand_dir / 'watermark.png')}")
    return 0


def cmd_channel(args) -> int:
    snap = _app(args).job_channel()
    ch = snap.get("channel", {})
    print(f"Canal: {ch.get('title', '?')}  ·  {ch.get('subscribers', 0)} inscritos  ·  {ch.get('views', 0)} views")
    print(f"Monetização: {snap.get('monetization', {}).get('status', '?')}")
    for name, err in snap.get("errors", {}).items():
        print(f"  ⚠ {name}: {err}")
    return 0


def cmd_test_upload(args) -> int:
    """Envia um vídeo de teste (privado) — útil para gravar o fluxo completo para a auditoria."""
    from pathlib import Path
    from .media import run
    from .youtube import build_metadata
    app = _app(args)
    video = Path(args.arquivo) if args.arquivo else app.cfg.data_dir / "teste_upload.mp4"
    if not args.arquivo:
        font = app.cfg["render"]["font_file"]
        txt = app.cfg.data_dir / "teste_upload.txt"
        txt.write_text("Teste do Clipador", encoding="utf-8")
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "color=c=0x3b0a4f:s=1080x1920:d=5", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
             "-shortest", "-vf", f"drawtext=fontfile='{font}':textfile='{txt}':fontsize=80:fontcolor=white:"
             "x=(w-tw)/2:y=(h-th)/2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)])
    print(f"Enviando {video} como PRIVADO...")
    meta = build_metadata("Teste do Clipador", "Vídeo de teste enviado pelo Clipador.", ["teste"],
                          app.cfg["youtube"]["category_id"], "private", None, False)
    vid = app.youtube().upload(video, meta)
    print(f"✅ Enviado: https://youtu.be/{vid}  (abra no YouTube Studio → Conteúdo)")
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
    se.add_argument("--streamer", help="só os clipes deste streamer (login da Twitch, ex.: alanzoka)")
    se.add_argument("--todos", action="store_true", help="todos os clipes prontos, não só o melhor de cada streamer")
    se.set_defaults(fn=cmd_export)
    sa = sub.add_parser("youtube-auth", help="autoriza o canal do YouTube (uma vez)")
    sa.add_argument("--manual", action="store_true", help="servidor sem navegador: colar a URL de retorno")
    sa.add_argument("--port", type=int, default=8765)
    sa.set_defaults(fn=cmd_youtube_auth)
    sb = sub.add_parser("brand", help="aplica descrição, palavras-chave e banner no canal")
    sb.add_argument("--no-banner", action="store_true")
    sb.set_defaults(fn=cmd_brand)
    sub.add_parser("canal", help="coleta agora os números do canal para o painel /canal").set_defaults(fn=cmd_channel)
    st = sub.add_parser("teste-upload", help="envia um vídeo de teste privado (para gravar a auditoria)")
    st.add_argument("--arquivo", help="mp4 a enviar (padrão: gera um vídeo de 5 s)")
    st.set_defaults(fn=cmd_test_upload)
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
