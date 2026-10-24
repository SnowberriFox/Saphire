"""Installing a GameBanana collection: pick which of its mods to get."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout)

from sapphire.ui.workers import run


class CollectionDialog(QDialog):
    def __init__(self, manager, collection_id: int, images, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self.cid = collection_id
        self.col = None
        self.setWindowTitle("Install a collection")
        self.setMinimumSize(560, 520)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        self.title = QLabel("Loading the collection from GameBanana…")
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-size: 15px;")
        lay.addWidget(self.title)
        self.hint = QLabel("")
        self.hint.setObjectName("Muted")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        self.list = QListWidget()
        self.list.itemChanged.connect(lambda *_: self._sync())
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.all_box = QCheckBox("Select all")
        self.all_box.toggled.connect(self._select_all)
        row.addWidget(self.all_box)
        self.skip_nsfw = QCheckBox("Skip 18+ mods")
        self.skip_nsfw.setChecked(manager.lib.settings.hide_nsfw)
        self.skip_nsfw.toggled.connect(lambda *_: self._fill())
        row.addWidget(self.skip_nsfw)
        row.addStretch(1)
        lay.addLayout(row)
        self.buttons = QDialogButtonBox()
        self.ok = self.buttons.addButton("Install selected", QDialogButtonBox.AcceptRole)
        self.ok.setProperty("kind", "primary")
        self.ok.setEnabled(False)
        page = QPushButton("Open on GameBanana")
        page.clicked.connect(self._open_page)
        self.buttons.addButton(page, QDialogButtonBox.ActionRole)
        self.buttons.addButton("Cancel", QDialogButtonBox.RejectRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        run(manager.gb.collection, collection_id, on_done=self._loaded, on_error=self._failed)

    def _open_page(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(f"https://gamebanana.com/collections/{self.cid}"))

    def _failed(self, exc):
        self.title.setText("Couldn't load that collection.")
        self.hint.setText(str(exc))

    def _loaded(self, col):
        self.col = col
        self.title.setText(f"“{col.name}”" + (f" by {col.author}" if col.author else ""))
        self._fill()

    def _fill(self):
        col = self.col
        if col is None:
            return
        self.list.blockSignals(True)
        self.list.clear()
        have = 0
        shown = [s for s in col.items if not (self.skip_nsfw.isChecked() and s.nsfw)]
        for sub in shown:
            installed = self.mgr.lib.by_gb(sub.model, sub.id) is not None
            have += installed
            label = sub.name
            bits = [sub.category_label or sub.model]
            if sub.author:
                bits.append(f"by {sub.author}")
            if installed:
                bits.append("already installed")
            if sub.obsolete:
                bits.append("outdated")
            it = QListWidgetItem(f"{label}\n{'  ·  '.join(bits)}")
            it.setData(Qt.UserRole, sub)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked if installed or sub.obsolete else Qt.Checked)
            if installed:
                it.setFlags(it.flags() & ~Qt.ItemIsEnabled)
            self.list.addItem(it)
        self.list.blockSignals(False)
        notes = [f"{len(shown)} Deadlock mod{'s' if len(shown) != 1 else ''}"]
        if have:
            notes.append(f"{have} you already have")
        if col.skipped:
            notes.append(f"{col.skipped} item{'s' if col.skipped != 1 else ''} that aren't installable mods "
                         "(other games, work-in-progress pages) left out")
        hidden = len(col.items) - len(shown)
        if hidden:
            notes.append(f"{hidden} 18+ hidden")
        self.hint.setText(". ".join(notes) + ". Each one installs with its newest file, like Install in Browse; "
                          "variants are asked about as usual.")
        self._sync()

    def _items(self):
        return [self.list.item(i) for i in range(self.list.count())]

    def _select_all(self, on: bool):
        self.list.blockSignals(True)
        for it in self._items():
            if it.flags() & Qt.ItemIsEnabled:
                it.setCheckState(Qt.Checked if on else Qt.Unchecked)
        self.list.blockSignals(False)
        self._sync()

    def _sync(self):
        n = len(self.chosen())
        self.ok.setEnabled(n > 0)
        self.ok.setText(f"Install {n} mod{'s' if n != 1 else ''}" if n else "Install selected")

    def chosen(self):
        return [it.data(Qt.UserRole) for it in self._items()
                if it.checkState() == Qt.Checked and it.flags() & Qt.ItemIsEnabled]
