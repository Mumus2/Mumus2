"""Leitor anônimo do chat da Twitch (IRC) para vários canais ao mesmo tempo.

Login anônimo "justinfan" só lê o chat — não precisa de token nem de conta.
"""
from __future__ import annotations

import asyncio
import logging
import random
import ssl
import time
from typing import Awaitable, Callable

log = logging.getLogger(__name__)

HOST, PORT = "irc.chat.twitch.tv", 6697
OnMessage = Callable[[str, float, str], None]


def parse_privmsg(line: str) -> tuple[str, str] | None:
    """':nick!nick@nick.tmi.twitch.tv PRIVMSG #canal :texto' -> ('canal', 'texto')."""
    if line.startswith("@"):  # tags IRCv3, se existirem
        _, _, line = line.partition(" ")
    parts = line.split(" ", 3)
    if len(parts) < 4 or parts[1] != "PRIVMSG":
        return None
    channel = parts[2].lstrip("#").lower()
    text = parts[3][1:] if parts[3].startswith(":") else parts[3]
    return channel, text


class ChatReader:
    def __init__(self, on_message: OnMessage):
        self.on_message = on_message
        self.wanted: set[str] = set()
        self.joined: set[str] = set()
        self._writer: asyncio.StreamWriter | None = None
        self._stop = asyncio.Event()

    async def set_channels(self, channels: set[str]) -> None:
        self.wanted = {c.lower() for c in channels}
        await self._sync()

    async def _send(self, line: str) -> None:
        if self._writer:
            self._writer.write((line + "\r\n").encode())
            await self._writer.drain()

    async def _sync(self) -> None:
        if not self._writer:
            return
        for ch in sorted(self.joined - self.wanted):
            await self._send(f"PART #{ch}")
            self.joined.discard(ch)
        to_join = sorted(self.wanted - self.joined)
        # limite de JOIN da Twitch para contas não verificadas: ~20 a cada 10s
        for i in range(0, len(to_join), 15):
            batch = to_join[i : i + 15]
            await self._send("JOIN " + ",".join(f"#{c}" for c in batch))
            self.joined.update(batch)
            if i + 15 < len(to_join):
                await asyncio.sleep(11)

    async def run(self) -> None:
        backoff = 1
        while not self._stop.is_set():
            try:
                await self._session()
                backoff = 1
            except (OSError, asyncio.IncompleteReadError, ConnectionError) as e:
                log.warning("Chat desconectado (%s). Reconectando em %ss", e, backoff)
            self._writer = None
            self.joined.clear()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    async def _session(self) -> None:
        reader, writer = await asyncio.open_connection(HOST, PORT, ssl=ssl.create_default_context())
        self._writer = writer
        await self._send("PASS SCHMOOPIIE")
        await self._send(f"NICK justinfan{random.randint(10000, 99999)}")
        await self._sync()
        log.info("Chat conectado: %d canais", len(self.joined))
        while True:
            raw = await asyncio.wait_for(reader.readline(), timeout=360)
            if not raw:
                raise ConnectionError("conexão fechada")
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith("PING"):
                await self._send("PONG" + line[4:])
                continue
            if " RECONNECT" in line:
                raise ConnectionError("servidor pediu RECONNECT")
            parsed = parse_privmsg(line)
            if parsed:
                self.on_message(parsed[0], time.time(), parsed[1])

    def stop(self) -> None:
        self._stop.set()
