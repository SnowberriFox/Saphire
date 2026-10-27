"""Downloads page: every install/update/import job this session, with progress."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from sapphire.ui import theme
from sapphire.ui.dialogs import human_size


@dataclass
class Job:
    label: str
    kind: str = "install"            # install / update / import / app-update
    state: str = "queued"            # queued / running / done / failed / cancelled
    stage: str = ""
    done: int = 0
    total: int = 0
    error: str = ""
    created: float = field(default_factory=time.time)
    finished: float = 0.0
    cancel: threading.Event = field(default_factory=threading.Event)
    retry: object = None             # callable to run it again, if any
    key: str = ""                    # what it works on ("mod:<uid>"); one active job per key

    @property
    def active(self) -> bool:
        return self.state in ("queued", "running")


class JobList(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.jobs: list[Job] = []

    def add(self, job: Job) -> Job:
        self.jobs.insert(0, job)
        self.changed.emit()
        return job

    def active(self) -> list[Job]:
        return [j for j in self.jobs if j.active]

    def active_for(self, key: str) -> Job | None:
        """The queued or running job working on `key`, if any."""
        if not key:
            return None
        return next((j for j in self.jobs if j.active and j.key == key), None)

    def running(self) -> Job | None:
        return next((j for j in self.jobs if j.state == "running"), None)

    def update(self, job: Job, **fields) -> None:
        for k, v in fields.items():
            setattr(job, k, v)
        if job.state in ("done", "failed", "cancelled") and not job.finished:
            job.finished = time.time()
        self.changed.emit()

    def clear_finished(self) -> None:
        self.jobs = [j for j in self.jobs if j.active]
        self.changed.emit()


class JobRow(QFrame):
    def __init__(self, job: Job, jobs: JobList):
        super().__init__()
        self.job, self.jobs = job, jobs
        self.setObjectName("Panel")
        self.setStyleSheet(f"#Panel {{ background: {theme.PANEL}; border-radius: {theme.rad(7):g}px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(6)
        top = QHBoxLayout()
        self.name = QLabel(job.label)
        self.name.setStyleSheet("background: transparent; font-weight: 600;")
        self.name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        top.addWidget(self.name, 1)
        self.status = QLabel()
        self.status.setObjectName("Muted")
        top.addWidget(self.status)
        self.button = QPushButton()
        self.button.clicked.connect(self._action)
        top.addWidget(self.button)
        lay.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setFixedHeight(6)
        lay.addWidget(self.bar)
        self.detail = QLabel()
        self.detail.setObjectName("Muted")
        self.detail.setWordWrap(True)
        lay.addWidget(self.detail)
        self.refresh()

    def refresh(self):
        j = self.job
        kind = {"install": "Install", "update": "Update", "import": "Import", "app-update": "Sapphire update"}.get(j.kind, j.kind)
        if j.state == "queued":
            self.status.setText(f"{kind} · queued")
            self.bar.setRange(0, 0)
            self.bar.show()
            self.detail.setText("Waiting for the downloads ahead of it.")
            self.button.setText("Cancel")
            self.button.show()
        elif j.state == "running":
            self.status.setText(f"{kind} · {j.stage or 'working'}")
            if j.total:
                self.bar.setRange(0, 1000)
                self.bar.setValue(int(j.done / j.total * 1000))
                self.detail.setText(f"{human_size(j.done)} of {human_size(j.total)}")
            else:
                self.bar.setRange(0, 0)
                self.detail.setText(j.stage or "")
            self.bar.show()
            self.button.setText("Cancel")
            self.button.show()
        else:
            self.bar.hide()
            when = time.strftime("%H:%M", time.localtime(j.finished)) if j.finished else ""
            if j.state == "done":
                self.status.setText(f"{kind} · done {when}")
                self.status.setStyleSheet(f"background: transparent; color: {theme.VERDIGRIS};")
                self.detail.setText("")
                self.button.hide()
            elif j.state == "cancelled":
                self.status.setText(f"{kind} · cancelled")
                self.detail.setText("")
                self.button.setText("Retry")
                self.button.setVisible(j.retry is not None)
            else:
                self.status.setText(f"{kind} · failed {when}")
                self.status.setStyleSheet(f"background: transparent; color: {theme.DANGER_TEXT};")
                self.detail.setText(j.error)
                self.button.setText("Retry")
                self.button.setVisible(j.retry is not None)

    def _action(self):
        if self.job.active:
            self.job.cancel.set()
            if self.job.state == "queued":
                self.jobs.update(self.job, state="cancelled")
        elif self.job.retry:
            self.job.retry()


class DownloadsPage(QWidget):
    def __init__(self, jobs: JobList):
        super().__init__()
        self.jobs = jobs
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(10)
        top = QHBoxLayout()
        title = QLabel("Downloads")
        title.setObjectName("PageTitle")
        top.addWidget(title)
        self.summary = QLabel()
        self.summary.setObjectName("Muted")
        top.addWidget(self.summary)
        top.addStretch(1)
        self.cancel_all = QPushButton("Cancel all")
        self.cancel_all.clicked.connect(self._cancel_all)
        self.clear_btn = QPushButton("Clear finished")
        self.clear_btn.clicked.connect(jobs.clear_finished)
        top.addWidget(self.cancel_all)
        top.addWidget(self.clear_btn)
        root.addLayout(top)
        hint = QLabel("Downloads run one at a time, in the order you started them, so a big skin never "
                      "starves the small ones. Installs continue if you switch pages.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.body = QWidget()
        self.lay = QVBoxLayout(self.body)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(8)
        self.lay.addStretch(1)
        self.scroll.setWidget(self.body)
        root.addWidget(self.scroll, 1)
        self.empty = QLabel("Nothing downloading. Install something from Browse and it shows up here.")
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignCenter)
        root.addWidget(self.empty, 1)
        self.rows: dict[int, JobRow] = {}
        jobs.changed.connect(self.refresh)
        self.refresh()

    def _cancel_all(self):
        for j in self.jobs.active():
            j.cancel.set()
            if j.state == "queued":
                j.state = "cancelled"
                j.finished = time.time()
        self.jobs.changed.emit()

    def refresh(self):
        live = {id(j): j for j in self.jobs.jobs}
        for jid in list(self.rows):
            if jid not in live:
                row = self.rows.pop(jid)
                self.lay.removeWidget(row)
                row.deleteLater()
        order = sorted(self.jobs.jobs, key=lambda j: (
            0 if j.state == "running" else 1 if j.state == "queued" else 2,
            j.created if j.active else -j.finished))
        for i, j in enumerate(order):
            row = self.rows.get(id(j))
            if row is None:
                row = JobRow(j, self.jobs)
                self.rows[id(j)] = row
            if self.lay.indexOf(row) != i:
                self.lay.removeWidget(row)
                self.lay.insertWidget(i, row)
            row.refresh()
        active = self.jobs.active()
        done = sum(1 for j in self.jobs.jobs if j.state == "done")
        failed = sum(1 for j in self.jobs.jobs if j.state == "failed")
        bits = []
        if active:
            bits.append(f"{len(active)} in progress")
        if done:
            bits.append(f"{done} done")
        if failed:
            bits.append(f"{failed} failed")
        self.summary.setText(", ".join(bits))
        self.cancel_all.setVisible(bool(active))
        self.clear_btn.setVisible(len(self.jobs.jobs) > len(active))
        self.empty.setVisible(not self.jobs.jobs)
        self.scroll.setVisible(bool(self.jobs.jobs))
