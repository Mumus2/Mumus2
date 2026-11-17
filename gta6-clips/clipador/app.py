"""Orquestrador: roda tudo 24h — descoberta, chat, coleta, edição e postagem."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

from .chat import ChatReader
from .config import Config
from .db import DB, utcnow
from .discovery import discover, refresh_live, resolve_game_id, sync_seeds
from .harvest import harvest_community, harvest_moments, record_moment
from .hype import HypeDetector
from .media import MediaWorker

log = logging.getLogger(__name__)


class Clipador:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.db = DB(cfg.db_path)
        self.media = MediaWorker(cfg, self.db)
        self.detector = HypeDetector.from_config(cfg["hype"])
        self._tw = None
        self._game_id: str | None = None
        self.live_gta: dict[str, dict] = {}
        self.busy: set[str] = set()   # jobs rodando agora (mostrado no painel)

    # ---------- dependências preguiçosas (para o painel abrir sem credenciais) ----------
    @property
    def tw(self):
        if self._tw is None:
            from .twitch import Twitch
            self._tw = Twitch(Config.env("TWITCH_CLIENT_ID"), Config.env("TWITCH_CLIENT_SECRET"))
        return self._tw

    @property
    def game_id(self) -> str:
        if self._game_id is None:
            self._game_id = resolve_game_id(self.cfg, self.tw)
        return self._game_id

    def youtube(self):
        from .youtube import YouTube
        return YouTube(Config.env("YOUTUBE_CLIENT_ID"), Config.env("YOUTUBE_CLIENT_SECRET"),
                       self.cfg.data_dir / "youtube_token.json")

    # ---------- jobs (síncronos; rodam em thread) ----------
    def job_discover(self) -> None:
        sync_seeds(self.db, self.tw, self.cfg)
        discover(self.db, self.tw, self.cfg, self.game_id)

    def job_refresh_live(self) -> dict[str, dict]:
        self.live_gta = refresh_live(self.db, self.tw, self.game_id)
        return self.live_gta

    def job_harvest(self) -> None:
        harvest_community(self.db, self.tw, self.cfg, self.game_id)
        harvest_moments(self.db, self.tw, self.cfg)
        self.media.process_pending()

    @property
    def realtime(self) -> bool:
        return self.cfg["youtube"].get("mode", "daily") == "realtime"

    def job_daily(self, dry_run: bool = False) -> list[str]:
        """Modo daily: compilação + plano agendado. Modo realtime: só a compilação."""
        from .publisher import run_daily
        return run_daily(self.db, self.cfg, self.youtube(), self.media, dry_run=dry_run,
                         with_plan=not self.realtime)

    def job_realtime(self) -> str | None:
        from .publisher import post_realtime
        return post_realtime(self.db, self.cfg, self.youtube())

    def run_job(self, name: str) -> None:
        """Usado pelo painel ("rodar agora")."""
        if name in self.busy:
            return
        self.busy.add(name)
        try:
            getattr(self, f"job_{name}")()
        except Exception:
            log.exception("Job %s falhou", name)
        finally:
            self.busy.discard(name)

    # ---------- loop principal ----------
    def on_chat(self, channel: str, ts: float, text: str) -> None:
        if channel in self.live_gta:
            self.detector.feed(channel, ts, text)

    async def _every(self, seconds: float, name: str, first_delay: float = 0) -> None:
        await asyncio.sleep(first_delay)
        while True:
            await asyncio.to_thread(self.run_job, name)
            await asyncio.sleep(seconds)

    async def _live_loop(self, chat: ChatReader) -> None:
        while True:
            before = set(self.live_gta)
            try:
                await asyncio.to_thread(self.job_refresh_live)
            except Exception:
                log.exception("Falha ao atualizar quem está ao vivo")
            for gone in before - set(self.live_gta):
                self.detector.reset(gone)
            await chat.set_channels({r["login"] for r in self.db.tracked_streamers()})
            await asyncio.sleep(60)

    async def _harvest_loop(self) -> None:
        """Com streamer ao vivo, coleta a cada poucos minutos; senão, de tempos em tempos."""
        h = self.cfg["harvest"]
        await asyncio.sleep(120)
        while True:
            await asyncio.to_thread(self.run_job, "harvest")
            if self.realtime:
                await asyncio.to_thread(self.run_job, "realtime")
            minutes = h["live_interval_minutes"] if (self.live_gta and self.realtime) else h["interval_minutes"]
            await asyncio.sleep(minutes * 60)

    async def _realtime_loop(self) -> None:
        while True:
            await asyncio.sleep(120)
            await asyncio.to_thread(self.run_job, "realtime")

    async def _hype_loop(self) -> None:
        while True:
            for m in self.detector.tick(time.time()):
                stream = self.live_gta.get(m.channel)
                record_moment(self.db, m.channel, stream, m.at, m.score, m.rate, m.sample)
                log.info("🔥 Momento em %s (z=%.1f, %.0f msg/janela)", m.channel, m.score, m.rate)
            await asyncio.sleep(1)

    async def _daily_loop(self) -> None:
        times = self.cfg["youtube"]["daily_run_time"]
        times = [times] if isinstance(times, str) else list(times)
        while True:
            now = utcnow().astimezone(self.cfg.tz)
            for t in times:
                hh, mm = (int(x) for x in t.split(":"))
                key = f"daily_done:{now.date()}:{t}"
                if (now.hour, now.minute) >= (hh, mm) and not self.db.get_meta(key):
                    self.db.set_meta(key, datetime.now().isoformat())
                    await asyncio.to_thread(self.run_job, "daily")
            await asyncio.sleep(60)

    async def run(self, with_web: bool = True) -> None:
        await asyncio.to_thread(self.job_discover)
        chat = ChatReader(self.on_chat)
        tasks = [
            chat.run(),
            self._live_loop(chat),
            self._hype_loop(),
            self._every(self.cfg["discovery"]["interval_minutes"] * 60, "discover",
                        first_delay=self.cfg["discovery"]["interval_minutes"] * 60),
            self._harvest_loop(),
            self._daily_loop(),
        ]
        if self.realtime:
            tasks.append(self._realtime_loop())
            log.info("Modo TEMPO REAL: clipes são publicados assim que ficam prontos")
        if with_web:
            import uvicorn
            from .web import create_app
            server = uvicorn.Server(uvicorn.Config(create_app(self), host=self.cfg.web_host,
                                                   port=self.cfg["web"]["port"], log_level="warning"))
            tasks.append(server.serve())
            log.info("Painel em http://%s:%s", self.cfg.web_host, self.cfg["web"]["port"])
        await asyncio.gather(*tasks)
