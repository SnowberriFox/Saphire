"""Import-from-another-manager dialog: preview the plan, then run it."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout)

from sapphire.importers import ImportPlan
from sapphire.ui import theme
from sapphire.ui.dialogs import human_size
from sapphire.ui.workers import run

SOURCE_NAMES = {"dmm": "Deadlock Mod Manager", "grimoire": "Grimoire"}


class ImportDialog(QDialog):
    def __init__(self, manager, which: str, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self.which = which
        self.plan: ImportPlan | None = None
        name = SOURCE_NAMES.get(which, which)
        self.setWindowTitle(f"Import from {name}")
        self.setMinimumSize(640, 480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        title = QLabel(f"Import from {name}")
        title.setObjectName("PageTitle")
        lay.addWidget(title)
        self.summary = QLabel("Reading its data…")
        self.summary.setObjectName("Muted")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Mod", "Source", "On"])
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, self.tree.header().ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, self.tree.header().ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, self.tree.header().ResizeMode.ResizeToContents)
        self.tree.setRootIsDecorated(False)
        lay.addWidget(self.tree, 1)
        self.note = QLabel(f"Nothing in {name} is changed or deleted. Mods are copied into Sapphire's library.")
        self.note.setObjectName("Muted")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.go = QPushButton("Import")
        self.go.setProperty("kind", "primary")
        self.go.setEnabled(False)
        self.go.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(self.go)
        lay.addLayout(row)
        run(self.mgr.plan_import, which, on_done=self._planned, on_error=self._failed)

    def _failed(self, exc):
        self.summary.setText(f"Couldn't read {SOURCE_NAMES.get(self.which, self.which)}: {exc}")
        self.summary.setStyleSheet("color: #E8A598;")

    def _planned(self, plan: ImportPlan):
        self.plan = plan
        self.tree.clear()
        if not plan.mods:
            self.summary.setText("\n".join(plan.warnings) or "Nothing to import.")
            return
        local = [m for m in plan.mods if m.vpks]
        dl = plan.downloadable
        skipped = plan.skipped
        bits = [f"{len(local)} mod{'s' if len(local) != 1 else ''} found on this computer"]
        if dl:
            bits.append(f"{len(dl)} will be re-downloaded from GameBanana")
        if skipped:
            bits.append(f"{len(skipped)} can't be recovered")
        if plan.profiles:
            bits.append(f"{len(plan.profiles)} profile{'s' if len(plan.profiles) != 1 else ''}: "
                        + ", ".join(p.name for p in plan.profiles[:6]))
        self.summary.setText(". ".join(bits) + ".")
        self.summary.setStyleSheet("")
        for m in plan.mods:
            if m.vpks:
                size = sum(v.main.stat().st_size for v in m.vpks if v.main.exists())
                src = f"local ({human_size(size)}{', ' + str(len(m.vpks)) + ' VPKs' if len(m.vpks) > 1 else ''})"
                color = theme.TEXT
            elif m.can_download:
                src, color = "download", theme.ACCENT_HI
            else:
                src, color = "skipped", theme.MUTED
            item = QTreeWidgetItem([m.name, src, "yes" if m.enabled else "no"])
            item.setForeground(1, QColor(color))
            if not m.vpks and not m.can_download:
                item.setForeground(0, QColor(theme.MUTED))
            self.tree.addTopLevelItem(item)
        for w in plan.warnings:
            item = QTreeWidgetItem([w, "", ""])
            item.setForeground(0, QColor("#E8A598"))
            self.tree.addTopLevelItem(item)
        self.go.setEnabled(bool(local or dl))
        self.go.setText(f"Import {len(local) + len(dl)} mod{'s' if len(local) + len(dl) != 1 else ''}")
