"""Upload para o YouTube (Data API v3) com agendamento via publishAt.

Autenticação OAuth "Desktop app":  python -m clipador youtube-auth
O refresh token fica salvo em data/youtube_token.json.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import logging
import secrets
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
API = "https://www.googleapis.com/youtube/v3"
# youtube.upload: enviar vídeos · youtube: editar descrição/banner do canal (comando `brand`)
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube"
BANNER_URL = "https://www.googleapis.com/upload/youtube/v3/channelBanners/insert"
CHUNK = 8 * 1024 * 1024


class YouTubeError(RuntimeError):
    pass


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize(client_id: str, client_secret: str, token_file: Path, port: int = 8765, manual: bool = False) -> None:
    """Fluxo OAuth. manual=True: para servidores sem navegador (cole a URL de retorno)."""
    redirect = f"http://127.0.0.1:{port}/"
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(16)
    url = AUTH_URL + "?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    print("\n1) Abra este link no navegador e entre na conta do SEU CANAL:\n\n" + url + "\n")
    if manual:
        print("2) Depois de autorizar, o navegador vai para uma página 127.0.0.1 que não abre.")
        back = input("   Copie a URL inteira da barra de endereço e cole aqui: ").strip()
        q = urllib.parse.parse_qs(urllib.parse.urlparse(back).query)
    else:
        q = _wait_for_redirect(port)
    if q.get("state", [""])[0] != state:
        raise YouTubeError("state OAuth não confere — tente de novo")
    if "code" not in q:
        raise YouTubeError(f"Autorização negada: {q.get('error')}")
    r = httpx.post(
        TOKEN_URL,
        data={
            "code": q["code"][0],
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect,
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        },
        timeout=30,
    )
    r.raise_for_status()
    tok = r.json()
    if "refresh_token" not in tok:
        raise YouTubeError("Google não devolveu refresh_token; revogue o acesso do app e tente de novo")
    token_file.write_text(json.dumps({"refresh_token": tok["refresh_token"]}), encoding="utf-8")
    token_file.chmod(0o600)
    print(f"\n✅ Canal autorizado. Token salvo em {token_file}")


def _wait_for_redirect(port: int) -> dict:
    result: dict = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            result.update(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>Pronto! Pode fechar esta aba e voltar ao terminal.</h2>".encode())
            done.set()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", port), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    print(f"2) Aguardando o retorno em http://127.0.0.1:{port}/ ...")
    done.wait()
    srv.shutdown()
    return result


def build_metadata(title: str, description: str, tags: list[str], category_id: str, privacy: str,
                   publish_at: datetime | None, made_for_kids: bool, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    status: dict = {"selfDeclaredMadeForKids": made_for_kids, "containsSyntheticMedia": False}
    if publish_at and publish_at > now:
        # agendamento exige privacyStatus=private; o YouTube torna público na hora marcada
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    else:
        status["privacyStatus"] = privacy
    return {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id,
            "defaultLanguage": "pt-BR",
            "defaultAudioLanguage": "pt-BR",
        },
        "status": status,
    }


class YouTube:
    def __init__(self, client_id: str, client_secret: str, token_file: Path, http: httpx.Client | None = None):
        if not token_file.exists():
            raise YouTubeError("Canal não autorizado. Rode: python -m clipador youtube-auth")
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = json.loads(token_file.read_text())["refresh_token"]
        self.http = http or httpx.Client(timeout=120)
        self._access: str | None = None
        self._exp = 0.0

    def _token(self) -> str:
        if self._access and time.time() < self._exp - 60:
            return self._access
        r = self.http.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if r.status_code != 200:
            raise YouTubeError(f"Falha ao renovar token do YouTube: {r.text}")
        body = r.json()
        self._access, self._exp = body["access_token"], time.time() + body.get("expires_in", 3600)
        return self._access

    def channel(self) -> dict:
        r = self.http.get(f"{API}/channels", params={"part": "snippet,statistics", "mine": "true"},
                          headers={"Authorization": f"Bearer {self._token()}"})
        r.raise_for_status()
        items = r.json().get("items", [])
        return items[0] if items else {}

    def upload_banner(self, path: Path) -> str:
        """Envia a imagem do banner (2560x1440, até 6 MB) e devolve a URL temporária dela."""
        r = self.http.post(BANNER_URL, params={"uploadType": "media"},
                           headers={"Authorization": f"Bearer {self._token()}", "Content-Type": "image/png"},
                           content=path.read_bytes())
        if r.status_code != 200:
            raise YouTubeError(_explain(r))
        return r.json()["url"]

    def update_branding(self, description: str, keywords: list[str], banner_url: str | None = None,
                        country: str = "BR", language: str = "pt") -> dict:
        """Atualiza descrição, palavras-chave, país, idioma e (opcional) banner do canal.
        Nome e foto de perfil a API não deixa mudar: isso é feito no YouTube Studio."""
        auth = {"Authorization": f"Bearer {self._token()}"}
        r = self.http.get(f"{API}/channels", params={"part": "brandingSettings", "mine": "true"}, headers=auth)
        r.raise_for_status()
        items = r.json().get("items", [])
        if not items:
            raise YouTubeError("Esta conta Google ainda não tem canal no YouTube")
        ch = items[0]
        channel = dict(ch.get("brandingSettings", {}).get("channel", {}))
        channel.update(
            description=description.replace("<", "").replace(">", "")[:1000],  # YouTube recusa < >
            keywords=" ".join(f'"{k}"' if " " in k else k for k in keywords)[:500],
            country=country,
            defaultLanguage=language,
        )
        body: dict = {"id": ch["id"], "brandingSettings": {"channel": channel}}
        if banner_url:
            body["brandingSettings"]["image"] = {"bannerExternalUrl": banner_url}
        r = self.http.put(f"{API}/channels", params={"part": "brandingSettings"}, headers=auth, json=body)
        if r.status_code != 200:
            raise YouTubeError(_explain(r))
        return r.json()

    def upload(self, path: Path, metadata: dict) -> str:
        size = path.stat().st_size
        r = self.http.post(
            UPLOAD_URL,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(size),
            },
            content=json.dumps(metadata).encode(),
        )
        if r.status_code != 200:
            raise YouTubeError(_explain(r))
        session = r.headers["Location"]
        offset = 0
        with path.open("rb") as f:
            while offset < size:
                f.seek(offset)
                chunk = f.read(CHUNK)
                end = offset + len(chunk) - 1
                for attempt in range(5):
                    try:
                        resp = self.http.put(
                            session,
                            headers={
                                "Authorization": f"Bearer {self._token()}",
                                "Content-Length": str(len(chunk)),
                                "Content-Range": f"bytes {offset}-{end}/{size}",
                            },
                            content=chunk,
                        )
                    except httpx.TransportError:
                        time.sleep(2 ** attempt)
                        continue
                    if resp.status_code in (500, 502, 503, 504):
                        time.sleep(2 ** attempt)
                        continue
                    break
                else:
                    raise YouTubeError("Upload falhou após várias tentativas")
                if resp.status_code in (200, 201):
                    return resp.json()["id"]
                if resp.status_code == 308:
                    rng = resp.headers.get("Range")
                    offset = int(rng.split("-")[1]) + 1 if rng else 0
                    continue
                raise YouTubeError(_explain(resp))
        raise YouTubeError("Upload terminou sem resposta final do YouTube")


def _explain(r: httpx.Response) -> str:
    try:
        err = r.json().get("error", {})
        reason = (err.get("errors") or [{}])[0].get("reason", "")
    except Exception:
        return f"HTTP {r.status_code}: {r.text[:300]}"
    hints = {
        "quotaExceeded": "Cota diária da API esgotada (zera à meia-noite do horário do Pacífico).",
        "uploadLimitExceeded": "Limite de uploads do canal atingido hoje.",
        "forbidden": "Sem permissão — confira se autorizou a conta certa.",
    }
    return f"HTTP {r.status_code} {reason}: {hints.get(reason, err.get('message', ''))}"
