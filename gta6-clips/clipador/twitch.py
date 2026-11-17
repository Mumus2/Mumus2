"""Cliente mínimo da Twitch Helix API (token de app, client credentials)."""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Iterable, Iterator

import httpx

from .db import iso

log = logging.getLogger(__name__)

HELIX = "https://api.twitch.tv/helix"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"


def chunks(items: list, size: int) -> Iterator[list]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


class Twitch:
    def __init__(self, client_id: str, client_secret: str, http: httpx.Client | None = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.http = http or httpx.Client(timeout=30)
        self._token: str | None = None
        self._token_exp = 0.0

    # ---------- autenticação ----------
    def _ensure_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        r = self.http.post(
            TOKEN_URL,
            params={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
        )
        r.raise_for_status()
        body = r.json()
        self._token = body["access_token"]
        self._token_exp = time.time() + int(body.get("expires_in", 3600))
        return self._token

    def get(self, path: str, params: Any = None) -> dict:
        for attempt in range(5):
            headers = {
                "Client-Id": self.client_id,
                "Authorization": f"Bearer {self._ensure_token()}",
            }
            r = self.http.get(f"{HELIX}{path}", params=params, headers=headers)
            if r.status_code == 401:
                self._token = None
                continue
            if r.status_code == 429:
                reset = float(r.headers.get("Ratelimit-Reset", time.time() + 2))
                time.sleep(max(1.0, reset - time.time()))
                continue
            if r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"Twitch API falhou repetidamente em {path}")

    def paginate(self, path: str, params: list[tuple[str, Any]], limit: int) -> Iterator[dict]:
        cursor = None
        seen = 0
        while True:
            p = list(params) + ([("after", cursor)] if cursor else [])
            body = self.get(path, p)
            for item in body.get("data", []):
                yield item
                seen += 1
                if seen >= limit:
                    return
            cursor = body.get("pagination", {}).get("cursor")
            if not cursor or not body.get("data"):
                return

    # ---------- endpoints ----------
    def find_game_id(self, name: str) -> str | None:
        body = self.get("/games", [("name", name)])
        if body.get("data"):
            return body["data"][0]["id"]
        body = self.get("/search/categories", [("query", name), ("first", 10)])
        for item in body.get("data", []):
            if item["name"].lower() == name.lower():
                return item["id"]
        return body["data"][0]["id"] if body.get("data") else None

    def users(self, logins: Iterable[str]) -> list[dict]:
        out: list[dict] = []
        for group in chunks(sorted(set(logins)), 100):
            out += self.get("/users", [("login", l) for l in group]).get("data", [])
        return out

    def top_streams(self, game_id: str, language: str, limit: int = 300) -> list[dict]:
        params = [("game_id", game_id), ("language", language), ("first", 100)]
        return list(self.paginate("/streams", params, limit))

    def live_streams(self, user_ids: Iterable[str]) -> list[dict]:
        out: list[dict] = []
        for group in chunks(sorted(set(user_ids)), 100):
            params = [("user_id", u) for u in group] + [("first", 100)]
            out += self.get("/streams", params).get("data", [])
        return out

    def clips(self, broadcaster_id: str, start: datetime, end: datetime, limit: int = 100) -> list[dict]:
        """Clipes criados pela comunidade, ordenados por visualizações."""
        params = [
            ("broadcaster_id", broadcaster_id),
            ("started_at", iso(start)),
            ("ended_at", iso(end)),
            ("first", 100),
        ]
        return list(self.paginate("/clips", params, limit))

    def archives(self, user_id: str, limit: int = 20) -> list[dict]:
        params = [("user_id", user_id), ("type", "archive"), ("first", min(limit, 100))]
        return self.get("/videos", params).get("data", [])


def parse_twitch_duration(value: str) -> int:
    """'3h8m33s' -> 11313 segundos."""
    total, num = 0, ""
    for ch in value:
        if ch.isdigit():
            num += ch
        else:
            total += int(num or 0) * {"h": 3600, "m": 60, "s": 1}.get(ch, 0)
            num = ""
    return total
