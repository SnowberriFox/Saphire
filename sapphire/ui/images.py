"""Thumbnail loading with an on-disk cache, so scrolling stays smooth."""

from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict

import requests
from PySide6.QtCore import QObject, QThreadPool, Qt, Signal
from PySide6.QtGui import QImage, QPixmap

from sapphire import paths
from sapphire.ui.workers import Task, keep_alive

log = logging.getLogger(__name__)

POOL = QThreadPool()
POOL.setMaxThreadCount(8)
ALLOWED_HOSTS = ("https://images.gamebanana.com/", "https://gamebanana.com/", "https://files.gamebanana.com/")


class ImageCache(QObject):
    loaded = Signal(str)  # url

    def __init__(self, session: requests.Session, max_items: int = 600):
        super().__init__()
        self.session = session
        self._pix: OrderedDict[str, QPixmap] = OrderedDict()
        self._inflight: set[str] = set()
        self._failed: set[str] = set()
        self.max_items = max_items

    def _file(self, url: str):
        return paths.thumbs_dir() / (hashlib.sha1(url.encode()).hexdigest() + ".img")

    def get(self, url: str) -> QPixmap | None:
        """Return the pixmap if ready; otherwise start loading it and return None."""
        if not url:
            return None
        pix = self._pix.get(url)
        if pix is not None:
            self._pix.move_to_end(url)
            return pix
        if url in self._inflight or url in self._failed or not url.startswith(ALLOWED_HOSTS):
            return None
        self._inflight.add(url)
        task = Task(self._fetch, url)
        task.signals.done.connect(self._ready, Qt.QueuedConnection)
        task.signals.failed.connect(lambda _e, u=url: self._fail(u), Qt.QueuedConnection)
        keep_alive(task)
        POOL.start(task)
        return None

    def _fetch(self, url: str):
        path = self._file(url)
        data = None
        if path.is_file():
            data = path.read_bytes()
        else:
            resp = self.session.get(url, timeout=(5, 20))
            resp.raise_for_status()
            data = resp.content
            if len(data) > 8 * 1024 * 1024:
                raise ValueError("image too large")
            tmp = path.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(path)
        img = QImage()
        if not img.loadFromData(data):
            path.unlink(missing_ok=True)
            raise ValueError("not an image")
        if img.width() > 900:
            img = img.scaledToWidth(900, Qt.SmoothTransformation)
        return url, img

    def _ready(self, result):
        url, img = result
        self._inflight.discard(url)
        self._pix[url] = QPixmap.fromImage(img)
        while len(self._pix) > self.max_items:
            self._pix.popitem(last=False)
        self.loaded.emit(url)

    def _fail(self, url: str):
        self._inflight.discard(url)
        self._failed.add(url)
