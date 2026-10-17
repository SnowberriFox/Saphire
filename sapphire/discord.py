"""Discord Rich Presence over the local IPC socket (no library, no network).

Talks only to the Discord client running on this computer, through its Unix
socket. Nothing is sent anywhere else. Off by default; needs a Discord
Application ID (Settings → Discord), which is a public, non-secret number you
get by creating an application at discord.com/developers.

Socket locations tried: $XDG_RUNTIME_DIR, $TMPDIR, /tmp, plus the Flatpak and
Snap sandboxes' copies, each with discord-ipc-0 … discord-ipc-9.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import struct
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

OP_HANDSHAKE, OP_FRAME, OP_CLOSE = 0, 1, 2
RECONNECT_EVERY = 30.0


def socket_candidates() -> list[Path]:
    roots: list[Path] = []
    for var in ("XDG_RUNTIME_DIR", "TMPDIR", "TMP", "TEMP"):
        v = os.environ.get(var)
        if v:
            roots.append(Path(v))
    roots.append(Path("/tmp"))
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        r = Path(runtime)
        roots += [r / "app" / "com.discordapp.Discord", r / "app" / "com.discordapp.DiscordCanary",
                  r / "snap.discord", r / "snap.discord-canary"]
    out: list[Path] = []
    for root in roots:
        for i in range(10):
            p = root / f"discord-ipc-{i}"
            if p not in out:
                out.append(p)
    return out


class Presence:
    """Keeps one activity shown on Discord while enabled. Thread-safe; all socket
    work happens on a background thread so the UI never waits on Discord."""

    def __init__(self, client_id: str = ""):
        self.client_id = client_id.strip()
        self._sock: socket.socket | None = None
        self._activity: dict | None = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_sent: str | None = None
        self._last_try = 0.0
        self.connected = False
        self.start_time = int(time.time())

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="discord-presence", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._close()

    def set_client_id(self, client_id: str) -> None:
        cid = client_id.strip()
        if cid != self.client_id:
            self.client_id = cid
            self._last_sent = None
            self._close()
            self._last_try = 0
            self._wake.set()

    def update(self, details: str, state: str = "", large_image: str = "", large_text: str = "",
               buttons: list[dict] | None = None) -> None:
        act: dict = {"details": details[:128], "timestamps": {"start": self.start_time}}
        if state:
            act["state"] = state[:128]
        assets = {}
        if large_image:
            assets["large_image"] = large_image
        if large_text:
            assets["large_text"] = large_text[:128]
        if assets:
            act["assets"] = assets
        if buttons:
            act["buttons"] = buttons[:2]
        with self._lock:
            self._activity = act
        self._wake.set()

    def clear(self) -> None:
        with self._lock:
            self._activity = None
        self._wake.set()

    # ------------------------------------------------------------ transport
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001 - never let presence kill the app
                log.debug("presence: %s", exc)
                self._close()
            self._wake.wait(15)
            self._wake.clear()

    def _tick(self) -> None:
        if not self.client_id:
            self._close()
            return
        if self._sock is None:
            if time.monotonic() - self._last_try < RECONNECT_EVERY:
                return
            self._last_try = time.monotonic()
            if not self._connect():
                return
        with self._lock:
            act = self._activity
        payload = json.dumps(act, sort_keys=True) if act else "null"
        if payload == self._last_sent:
            return
        self._send(OP_FRAME, {"cmd": "SET_ACTIVITY", "nonce": str(time.time()),
                              "args": {"pid": os.getpid(), "activity": act}})
        resp = self._recv()
        if resp and resp.get("evt") == "ERROR":
            log.warning("discord rejected the activity: %s", resp.get("data"))
        self._last_sent = payload

    def _connect(self) -> bool:
        for path in socket_candidates():
            if not path.exists():
                continue
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(3)
            try:
                s.connect(str(path))
                self._sock = s
                self._send(OP_HANDSHAKE, {"v": 1, "client_id": self.client_id})
                resp = self._recv()
                if not resp or resp.get("evt") != "READY":
                    raise OSError(f"bad handshake: {resp}")
                self.connected = True
                self._last_sent = None
                log.info("discord presence connected via %s", path)
                return True
            except OSError as exc:
                log.debug("discord socket %s: %s", path, exc)
                try:
                    s.close()
                except OSError:
                    pass
                self._sock = None
        self.connected = False
        return False

    def _send(self, op: int, data: dict) -> None:
        if self._sock is None:
            return
        body = json.dumps(data).encode()
        self._sock.sendall(struct.pack("<II", op, len(body)) + body)

    def _recv(self) -> dict | None:
        if self._sock is None:
            return None
        head = self._read(8)
        if not head:
            return None
        _op, length = struct.unpack("<II", head)
        body = self._read(length)
        try:
            return json.loads(body.decode()) if body else None
        except ValueError:
            return None

    def _read(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n and self._sock is not None:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise OSError("discord closed the socket")
            buf += chunk
        return buf

    def _close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None
        self.connected = False
