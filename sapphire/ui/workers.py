"""Running slow things (network, disk) off the UI thread."""

from __future__ import annotations

import logging
import threading
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot

log = logging.getLogger(__name__)

# Separate pools so a slow download never blocks browsing.
NET_POOL = QThreadPool()
NET_POOL.setMaxThreadCount(6)
JOB_POOL = QThreadPool()          # installs / applies: one at a time, in order
JOB_POOL.setMaxThreadCount(1)


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object)
    progress = Signal(object)


class Task(QRunnable):
    def __init__(self, fn: Callable[..., Any], *args, with_progress: bool = False, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = _Signals()
        self.with_progress = with_progress
        # Python owns the task; Qt deleting it early would drop queued signals.
        self.setAutoDelete(False)

    @Slot()
    def run(self):
        try:
            if self.with_progress:
                self.kwargs["progress"] = lambda *a: self.signals.progress.emit(a)
            result = self.fn(*self.args, **self.kwargs)
        except BaseException as exc:  # noqa: BLE001 - surface everything to the UI
            if not type(exc).__name__ == "Cancelled":
                log.error("task %s failed: %s\n%s", getattr(self.fn, "__name__", self.fn), exc,
                          traceback.format_exc())
            try:
                self.signals.failed.emit(exc)
            except RuntimeError:
                pass
            return
        try:
            self.signals.done.emit(result)
        except RuntimeError:  # receiver deleted
            pass


_LIVE: set[Task] = set()


def keep_alive(task: Task) -> None:
    """Hold a reference until the task's result has been delivered on the UI thread."""
    _LIVE.add(task)
    task.signals.done.connect(lambda _r, t=task: _LIVE.discard(t), Qt.QueuedConnection)
    task.signals.failed.connect(lambda _e, t=task: _LIVE.discard(t), Qt.QueuedConnection)


def run(fn: Callable[..., Any], *args, on_done: Callable | None = None,
        on_error: Callable | None = None, on_progress: Callable | None = None,
        pool: QThreadPool = NET_POOL, **kwargs) -> Task:
    task = Task(fn, *args, with_progress=on_progress is not None, **kwargs)
    if on_done:
        task.signals.done.connect(on_done, Qt.QueuedConnection)
    if on_error:
        task.signals.failed.connect(on_error, Qt.QueuedConnection)
    if on_progress:
        task.signals.progress.connect(lambda a: on_progress(*a), Qt.QueuedConnection)
    keep_alive(task)
    pool.start(task)
    return task


class MainThreadCaller(QObject):
    """Lets a worker thread run a function on the UI thread and wait for its result
    (used to show the 'which variant?' dialog in the middle of an install)."""

    _call = Signal(object)

    def __init__(self):
        super().__init__()
        self._call.connect(self._run, Qt.QueuedConnection)

    @Slot(object)
    def _run(self, job):
        fn, args, box, ev = job
        try:
            box["result"] = fn(*args)
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc
        finally:
            ev.set()

    def call(self, fn: Callable, *args):
        if threading.current_thread() is threading.main_thread():
            return fn(*args)
        box: dict = {}
        ev = threading.Event()
        self._call.emit((fn, args, box, ev))
        ev.wait()
        if "error" in box:
            raise box["error"]
        return box.get("result")
