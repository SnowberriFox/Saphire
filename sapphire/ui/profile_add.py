"""Add downloaded mods to the active profile (no download needed)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QVBoxLayout)


class AddDownloadedDialog(QDialog):
    """Mods that are downloaded but not in this profile, with which profiles
    have them. Tick the ones to add; they go in on and at the top."""

    def __init__(self, parent, manager):
        super().__init__(parent)
        lib = manager.lib
        self.chosen: list[str] = []
        self.setWindowTitle(f"Add to {lib.active_profile}")
        self.resize(560, 560)
        lay = QVBoxLayout(self)
        hint = QLabel("These are downloaded already (for other profiles, or not in any). Tick the ones you "
                      f"want in “{lib.active_profile}”: nothing needs downloading.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.find = QLineEdit()
        self.find.setPlaceholderText("Filter")
        self.find.setClearButtonEnabled(True)
        self.find.textChanged.connect(self._filter)
        lay.addWidget(self.find)
        self.list = QListWidget()
        for mod in lib.not_in_profile():
            where = lib.profiles_with(mod.uid)
            item = QListWidgetItem(f"{mod.name}\n" + (f"in {', '.join(where)}" if where else "in no profile"))
            item.setData(Qt.UserRole, mod.uid)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list.addItem(item)
        self.list.itemChanged.connect(lambda *_: self._sync())
        lay.addWidget(self.list, 1)
        box = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.ok = box.addButton("Add", QDialogButtonBox.AcceptRole)
        self.ok.setProperty("kind", "primary")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self._sync()

    def _items(self):
        return [self.list.item(i) for i in range(self.list.count())]

    def _filter(self, text: str):
        text = text.strip().lower()
        for item in self._items():
            item.setHidden(bool(text) and text not in item.text().lower())

    def _sync(self):
        n = sum(1 for i in self._items() if i.checkState() == Qt.Checked)
        self.ok.setText(f"Add {n}" if n else "Add")
        self.ok.setEnabled(bool(n))

    def accept(self):
        self.chosen = [i.data(Qt.UserRole) for i in self._items() if i.checkState() == Qt.Checked]
        super().accept()
