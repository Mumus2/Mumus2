"""Detector de momentos de hype a partir da velocidade do chat.

Ideia: cada canal tem um "ritmo normal" de chat (média móvel exponencial).
Quando acontece algo marcante na live, o chat explode (kkkkk, KEKW, CLIPA...).
Medimos quantas mensagens chegaram nos últimos N segundos, comparamos com o
normal via z-score e, se passar do limite, registramos um momento.

Esta parte não faz rede nenhuma — é lógica pura, fácil de testar.
"""
from __future__ import annotations

import math
import re
from collections import deque
from dataclasses import dataclass, field

HYPE_RE = re.compile(
    r"(k{4,}|(?:ha){3,}|(?:rs){3,}|kekw|omegalul|lul\b|lmao|icant|clip|"
    r"pog|wtf|caralho|mds|meu deus|nossa|😂|🤣|💀|😭)",
    re.IGNORECASE,
)
CLIP_RE = re.compile(r"\bclip", re.IGNORECASE)


def hype_weight(text: str, keyword_weight: float) -> float:
    """Peso de uma mensagem: 1 + bônus se for reação (risada, 'clipa', etc.)."""
    w = 1.0
    if HYPE_RE.search(text):
        w += keyword_weight
    if CLIP_RE.search(text):  # chat pedindo clipe é o sinal mais forte que existe
        w += keyword_weight * 2
    return w


@dataclass
class Moment:
    channel: str
    at: float            # unix ts do início da explosão do chat
    peak_at: float
    score: float         # z-score no pico
    rate: float          # peso de mensagens/janela no pico
    sample: list[str] = field(default_factory=list)


@dataclass
class _ChannelState:
    window: deque = field(default_factory=deque)   # (ts, peso, texto)
    weighted: float = 0.0
    mean: float = 0.0
    var: float = 1.0
    first_ts: float | None = None
    last_tick: float | None = None
    last_emit: float = -math.inf
    burst_start: float | None = None
    burst_peak: float = 0.0
    burst_peak_at: float = 0.0
    burst_rate: float = 0.0
    burst_sample: list[str] = field(default_factory=list)


class HypeDetector:
    def __init__(
        self,
        window_seconds: float = 10,
        baseline_halflife_seconds: float = 300,
        z_threshold: float = 3.5,
        min_messages_per_window: float = 25,
        cooldown_seconds: float = 90,
        keyword_weight: float = 0.6,
        warmup_seconds: float = 60,
        max_burst_seconds: float = 30,
    ):
        self.window = window_seconds
        self.halflife = baseline_halflife_seconds
        self.z_threshold = z_threshold
        self.min_msgs = min_messages_per_window
        self.cooldown = cooldown_seconds
        self.kw = keyword_weight
        self.warmup = warmup_seconds
        self.max_burst = max_burst_seconds
        self.channels: dict[str, _ChannelState] = {}

    @classmethod
    def from_config(cls, hype_cfg: dict) -> "HypeDetector":
        keys = (
            "window_seconds",
            "baseline_halflife_seconds",
            "z_threshold",
            "min_messages_per_window",
            "cooldown_seconds",
            "keyword_weight",
        )
        return cls(**{k: hype_cfg[k] for k in keys if k in hype_cfg})

    def feed(self, channel: str, ts: float, text: str) -> None:
        st = self.channels.setdefault(channel, _ChannelState())
        if st.first_ts is None:
            st.first_ts = ts
        w = hype_weight(text, self.kw)
        st.window.append((ts, w, text))
        st.weighted += w

    def reset(self, channel: str) -> None:
        self.channels.pop(channel, None)

    def tick(self, now: float) -> list[Moment]:
        """Chame ~1x por segundo. Devolve momentos que terminaram agora."""
        out = []
        for channel, st in self.channels.items():
            m = self._tick_channel(channel, st, now)
            if m:
                out.append(m)
        return out

    def _tick_channel(self, channel: str, st: _ChannelState, now: float) -> Moment | None:
        while st.window and st.window[0][0] < now - self.window:
            st.weighted -= st.window.popleft()[1]
        c = max(st.weighted, 0.0)

        dt = 1.0 if st.last_tick is None else max(now - st.last_tick, 0.0)
        st.last_tick = now
        std = math.sqrt(max(st.var, 1.0))
        z = (c - st.mean) / std

        warmed = st.first_ts is not None and now - st.first_ts >= self.warmup
        hot = warmed and z >= self.z_threshold and c >= self.min_msgs

        if st.burst_start is None:
            # só atualiza o "normal" fora de explosões, para não contaminar a média
            alpha = 1 - 0.5 ** (dt / self.halflife) if st.first_ts and now - st.first_ts > self.window else 0.5
            delta = c - st.mean
            st.mean += alpha * delta
            st.var = (1 - alpha) * (st.var + alpha * delta * delta)
            if hot and now - st.last_emit >= self.cooldown:
                st.burst_start = now - self.window / 2
                st.burst_peak, st.burst_peak_at, st.burst_rate = z, now, c
                st.burst_sample = [t for _, _, t in list(st.window)[-8:]]
            return None

        if z > st.burst_peak:
            st.burst_peak, st.burst_peak_at, st.burst_rate = z, now, c
            st.burst_sample = [t for _, _, t in list(st.window)[-8:]]
        if z < self.z_threshold / 2 or now - st.burst_start >= self.max_burst:
            m = Moment(
                channel=channel,
                at=st.burst_start,
                peak_at=st.burst_peak_at,
                score=round(st.burst_peak, 2),
                rate=round(st.burst_rate, 1),
                sample=st.burst_sample,
            )
            st.last_emit = now
            st.burst_start = None
            return m
        return None


def clip_window(offset_s: float, pre_roll: float, post_roll: float, max_len: float = 60) -> tuple[float, float]:
    """Trecho do VOD a recortar em volta de um momento (offset em segundos)."""
    start = max(0.0, offset_s - pre_roll)
    end = offset_s + post_roll
    if end - start > max_len:
        start = end - max_len
    return round(start, 1), round(end, 1)
