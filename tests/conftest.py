import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test gets its own Sapphire data folder and can't see the real Steam."""
    monkeypatch.setenv("SAPPHIRE_HOME", str(tmp_path / "sapphire-home"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    from sapphire import steam
    monkeypatch.setattr(steam, "is_game_running", lambda *a, **k: False)
    yield
