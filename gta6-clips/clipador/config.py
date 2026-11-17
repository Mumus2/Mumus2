"""Carrega config.yaml + variáveis de ambiente (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class Config:
    raw: dict[str, Any]
    root: Path = field(default=ROOT)

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.raw.get("timezone", "America/Sao_Paulo"))

    @property
    def data_dir(self) -> Path:
        p = Path(self.raw.get("data_dir", "data"))
        p = p if p.is_absolute() else self.root / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_path(self) -> Path:
        return self.data_dir / "clipador.db"

    @property
    def videos_dir(self) -> Path:
        p = self.data_dir / "videos"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def seed_file(self) -> Path:
        p = Path(self.raw["discovery"]["seed_file"])
        return p if p.is_absolute() else self.root / p

    @property
    def web_host(self) -> str:
        return os.environ.get("CLIPADOR_WEB_HOST") or self.raw["web"]["host"]

    @staticmethod
    def env(name: str, required: bool = True) -> str:
        value = os.environ.get(name, "")
        if required and not value:
            raise RuntimeError(
                f"Variável {name} não definida. Copie .env.example para .env e preencha."
            )
        return value


def load_config(path: str | Path | None = None, root: Path = ROOT) -> Config:
    _load_dotenv(root / ".env")
    base = yaml.safe_load((root / "config.example.yaml").read_text(encoding="utf-8"))
    cfg_path = Path(path) if path else root / "config.yaml"
    if cfg_path.exists():
        override = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        base = _deep_merge(base, override)
    return Config(raw=base, root=root)


def load_seeds(cfg: Config) -> list[dict[str, Any]]:
    if not cfg.seed_file.exists():
        return []
    data = yaml.safe_load(cfg.seed_file.read_text(encoding="utf-8")) or {}
    seeds = []
    for item in data.get("streamers", []):
        if isinstance(item, str):
            item = {"login": item}
        seeds.append(
            {
                "login": item["login"].strip().lower(),
                "pinned": bool(item.get("pinned", True)),
                "authorized": bool(item.get("authorized", False)),
                "priority": int(item.get("priority", 1)),
            }
        )
    return seeds
