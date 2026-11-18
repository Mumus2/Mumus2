"""Títulos, descrições e tags dos vídeos (em PT-BR)."""
from __future__ import annotations

import random
import re
from datetime import datetime

from .hype import CLIP_RE

LAUGH_RE = re.compile(r"k{4,}|kekw|omegalul|lul|(?:ha){3,}|😂|🤣", re.IGNORECASE)

TEMPLATES_LAUGH = [
    "{name} NÃO AGUENTOU DE RIR no GTA 6 😂",
    "O CHAT DO {NAME} MORREU DE RIR com isso no GTA 6",
    "{name} e a cena MAIS ENGRAÇADA do GTA 6",
]
TEMPLATES_HYPE = [
    "{name} NÃO ACREDITOU no que aconteceu no GTA 6",
    "O CHAT DO {NAME} EXPLODIU com esse momento no GTA 6",
    "{name} viveu o momento MAIS INSANO do GTA 6",
    "OLHA o que aconteceu com o {name} no GTA 6 😱",
]

FORBIDDEN = re.compile(r"[<>]")  # YouTube rejeita < e > em título/descrição


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", FORBIDDEN.sub("", text or "")).strip()


def fit_title(base: str, suffix: str = "", limit: int = 100) -> str:
    base, suffix = clean(base), clean(suffix) if suffix.strip() else ""
    sep = " " if suffix else ""
    room = limit - len(suffix) - len(sep)
    if len(base) > room:
        base = base[: max(room - 1, 1)].rstrip() + "…"
    return f"{base}{sep}{suffix}".strip()[:limit]


def make_title(clip: dict, display_name: str, suffix: str, sample: str = "") -> str:
    if clip.get("custom_title"):
        return fit_title(clip["custom_title"], "")
    if clip.get("source") == "twitch_clip" and clip.get("title"):
        t = clean(clip["title"])
        # título do clipe já cita o streamer? então não repete
        base = t if display_name.lower() in t.lower() else f"{display_name}: {t}"
        return fit_title(base, suffix)
    rng = random.Random(clip.get("id", 0))
    pool = TEMPLATES_LAUGH if LAUGH_RE.search(sample or "") else TEMPLATES_HYPE
    base = rng.choice(pool).format(name=display_name, NAME=display_name.upper())
    return fit_title(base, suffix.replace("| GTA 6", "").strip() if "GTA 6" in base else suffix)


def streamer_hashtag(login: str) -> str:
    return "#" + re.sub(r"[^0-9a-zA-Z]", "", login).lower()


def make_hashtags(login: str, hashtags: list[str], limit: int = 15) -> list[str]:
    """Hashtag do streamer primeiro; sem repetidas; no máximo 15 (acima disso o YouTube ignora todas)."""
    out: list[str] = []
    for h in [streamer_hashtag(login), *hashtags]:
        h = h if h.startswith("#") else "#" + h
        if len(h) > 1 and h.lower() not in {x.lower() for x in out}:
            out.append(h)
    return out[:limit]


def make_description(clip: dict, login: str, display_name: str, hashtags: list[str], live_date: datetime | None) -> str:
    when = f"📅 Live de {live_date:%d/%m/%Y}\n" if live_date else ""
    return clean_desc(
        f"🎮 {display_name} jogando GTA 6 ao vivo na Twitch!\n"
        f"👉 Siga o {display_name}: https://twitch.tv/{login}\n"
        f"{when}\n"
        "🔔 Inscreva-se e ative o sininho: os melhores momentos de GTA 6 dos maiores "
        "streamers do Brasil, todo dia!\n"
        "💬 Comenta aí: qual streamer você quer ver aqui?\n\n"
        "Todos os créditos ao criador original. Este é um corte da live com edição e "
        "créditos ao streamer. Se você é o criador e quer a remoção, é só comentar ou "
        "mandar mensagem que retiramos.\n\n"
        + " ".join(make_hashtags(login, hashtags))
    )


def clean_desc(text: str) -> str:
    return FORBIDDEN.sub("", text)[:4900]


def make_tags(base_tags: list[str], login: str, display_name: str) -> list[str]:
    tags = [display_name, login, f"{display_name} gta 6", f"{display_name} gta rp", *base_tags]
    out, total = [], 0
    for t in tags:
        t = clean(t)
        if t and t.lower() not in {x.lower() for x in out} and total + len(t) + 1 <= 480:
            out.append(t)
            total += len(t) + 1
    return out


def is_clip_request(text: str) -> bool:
    return bool(CLIP_RE.search(text))
