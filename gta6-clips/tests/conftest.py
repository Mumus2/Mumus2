import shutil
from pathlib import Path

import pytest

from clipador.config import ROOT, load_config


@pytest.fixture
def cfg(tmp_path: Path):
    shutil.copy(ROOT / "config.example.yaml", tmp_path / "config.example.yaml")
    (tmp_path / "streamers.yaml").write_text(
        "streamers:\n  - {login: alpha, pinned: true}\n  - {login: naoexiste}\n", encoding="utf-8"
    )
    return load_config(tmp_path / "config.yaml", root=tmp_path)


class FakeTwitch:
    """Imita só o que o pipeline usa da Twitch."""

    def __init__(self):
        self.users_db = {
            "alpha": {"id": "1", "login": "alpha", "display_name": "Alpha", "profile_image_url": ""},
            "beta": {"id": "2", "login": "beta", "display_name": "Beta", "profile_image_url": ""},
            "gamma": {"id": "3", "login": "gamma", "display_name": "Gamma", "profile_image_url": ""},
        }
        self.streams = []
        self.clip_map = {}
        self.archive_map = {}

    def find_game_id(self, name):
        return "999"

    def users(self, logins):
        return [self.users_db[l] for l in logins if l in self.users_db]

    def top_streams(self, game_id, language, limit=300):
        return [s for s in self.streams if s["game_id"] == game_id]

    def live_streams(self, user_ids):
        return [s for s in self.streams if s["user_id"] in set(user_ids)]

    def clips(self, broadcaster_id, start, end, limit=100):
        return self.clip_map.get(broadcaster_id, [])

    def archives(self, user_id, limit=20):
        return self.archive_map.get(user_id, [])


@pytest.fixture
def fake_tw():
    return FakeTwitch()
