"""Playing GameBanana's preview clips for sound mods.

One player for the whole app (starting a preview stops the last one). Clips are
fetched to the cache first and played from disk, which works with every Qt
media backend and means replaying is instant.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtWidgets import QPushButton

from sapphire import paths
from sapphire.ui.workers import NET_POOL, run

log = logging.getLogger(__name__)

MAX_CLIP = 25 * 1024 * 1024


def pick_audio_backend(env=None) -> str | None:
    """Choose Qt's audio backend before QtMultimedia loads, unless the user already did.
    Qt's PipeWire backend crashes the whole process when PipeWire is only half
    there (library installed, no daemon/config), so prefer PulseAudio, which
    Ubuntu and Bazzite both provide through pipewire-pulse and Flatpak exposes as
    its sound socket; then PipeWire only when it's fully present; then ALSA."""
    import os
    env = os.environ if env is None else env
    if env.get("QT_AUDIO_BACKEND"):
        return None
    runtime = Path(env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
    pulse = Path(env.get("PULSE_SERVER", "").removeprefix("unix:")) if env.get("PULSE_SERVER") else runtime / "pulse" / "native"
    if pulse.exists():
        choice = "pulseaudio"
    elif (runtime / "pipewire-0").exists() and any(Path(d).is_dir() for d in ("/usr/share/pipewire", "/etc/pipewire")):
        choice = "pipewire"
    else:
        choice = "alsa"
    env["QT_AUDIO_BACKEND"] = choice
    log.info("audio backend: %s", choice)
    return choice


class PreviewPlayer(QObject):
    changed = Signal()   # playing url / state changed

    def __init__(self, session):
        super().__init__()
        self.session = session
        self.url = ""            # what's playing (or loading)
        self.loading = False
        self.error = ""
        self._player = None
        self._audio = None

    def _ensure(self):
        if self._player is None:
            pick_audio_backend()
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            self._audio = QAudioOutput(self)
            self._audio.setVolume(0.8)
            self._player = QMediaPlayer(self)
            self._player.setAudioOutput(self._audio)
            self._player.playbackStateChanged.connect(self._state)
            self._player.errorOccurred.connect(self._failed)
        return self._player

    def is_playing(self, url: str) -> bool:
        return bool(url) and url == self.url

    def toggle(self, url: str):
        if self.is_playing(url):
            self.stop()
        else:
            self.play(url)

    def play(self, url: str):
        self.stop()
        self.url, self.loading, self.error = url, True, ""
        self.changed.emit()
        run(self._fetch, url, on_done=lambda p, u=url: self._ready(u, p),
            on_error=lambda e, u=url: self._fetch_failed(u, e), pool=NET_POOL)

    def stop(self):
        if self._player is not None:
            self._player.stop()
        if self.url:
            self.url, self.loading = "", False
            self.changed.emit()

    def _fetch(self, url: str) -> Path:
        folder = paths.cache_dir() / "previews"
        folder.mkdir(parents=True, exist_ok=True)
        ext = Path(QUrl(url).path()).suffix.lower()[:5] or ".mp3"
        dest = folder / (hashlib.sha1(url.encode()).hexdigest()[:20] + ext)
        if dest.is_file() and dest.stat().st_size > 0:
            return dest
        resp = self.session.get(url, timeout=(5, 30), stream=True)
        resp.raise_for_status()
        data = bytearray()
        for chunk in resp.iter_content(64 * 1024):
            data += chunk
            if len(data) > MAX_CLIP:
                raise ValueError("preview clip is too large")
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(bytes(data))
        tmp.replace(dest)
        return dest

    def _ready(self, url: str, path: Path):
        if url != self.url:
            return    # something else was started meanwhile
        self.loading = False
        p = self._ensure()
        from PySide6.QtMultimedia import QMediaDevices
        if not QMediaDevices.audioOutputs():
            self.url, self.error = "", "No speakers or headphones found."
            self.changed.emit()
            return
        p.setSource(QUrl.fromLocalFile(str(path)))
        p.play()
        self.changed.emit()

    def _fetch_failed(self, url: str, exc):
        if url != self.url:
            return
        log.warning("preview fetch failed: %s", exc)
        self.url, self.loading, self.error = "", False, "Couldn't load the preview."
        self.changed.emit()

    def _state(self, state):
        from PySide6.QtMultimedia import QMediaPlayer
        if state == QMediaPlayer.StoppedState and self.url and not self.loading:
            self.url = ""
            self.changed.emit()

    def _failed(self, _err, text):
        log.warning("preview playback failed: %s", text)
        self.url, self.loading, self.error = "", False, "This preview can't be played here."
        self.changed.emit()


class PreviewButton(QPushButton):
    """▶ Preview / ■ Stop for one clip, kept in step with the shared player."""

    def __init__(self, player: PreviewPlayer, url: str, parent=None):
        super().__init__(parent)
        self.player, self.url = player, url
        self.setToolTip("Play GameBanana's preview of this sound")
        self.clicked.connect(lambda: player.toggle(url))
        player.changed.connect(self._sync)   # Qt drops this connection when the button is deleted
        self._sync()

    def _sync(self):
        try:
            if self.player.is_playing(self.url):
                self.setText("Loading…" if self.player.loading else "■  Stop")
            elif self.player.error:
                self.setText(f"▶  Preview   ({self.player.error.rstrip('.')})")
            else:
                self.setText("▶  Preview")
        except RuntimeError:
            pass
