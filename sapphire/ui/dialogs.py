"""Small dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QInputDialog, QLabel,
                               QMessageBox, QScrollArea, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from sapphire.ui import theme
from sapphire.vpk import VpkSet


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


class VariantDialog(QDialog):
    """Shown when a download contains several VPKs (colour variants, optional parts...)."""

    def __init__(self, sets: list[VpkSet], mod_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose what to install")
        self.setMinimumWidth(460)
        self.sets = sets
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        title = QLabel(f"“{mod_name}” comes with {len(sets)} VPK files.")
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 15px;")
        hint = QLabel("These are usually variants (pick one) or optional extras (pick any). "
                      "Sapphire remembers your choice for future updates.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(title)
        lay.addWidget(hint)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 4, 0, 4)
        self.boxes: list[QCheckBox] = []
        for i, s in enumerate(sets):
            label = s.rel.rsplit("/", 1)[0] if "/" in s.rel else s.rel
            cb = QCheckBox(f"{label}    ({human_size(s.size)})")
            cb.setToolTip(s.rel)
            cb.setChecked(i == 0)
            cb.toggled.connect(self._sync)
            il.addWidget(cb)
            self.boxes.append(cb)
        il.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setMaximumHeight(320)
        scroll.setFrameShape(QScrollArea.NoFrame)
        lay.addWidget(scroll)
        self.buttons = QDialogButtonBox()
        self.ok = self.buttons.addButton("Install selected", QDialogButtonBox.AcceptRole)
        self.ok.setProperty("kind", "primary")
        self.buttons.addButton("Cancel", QDialogButtonBox.RejectRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self._sync()

    def _sync(self):
        self.ok.setEnabled(any(b.isChecked() for b in self.boxes))

    def chosen(self) -> list[VpkSet]:
        return [s for s, b in zip(self.sets, self.boxes) if b.isChecked()]


def choose_variants(parent, sets: list[VpkSet], name: str) -> list[VpkSet] | None:
    dlg = VariantDialog(sets, name, parent)
    if dlg.exec() == QDialog.Accepted:
        return dlg.chosen()
    return None


class FileVariantDialog(QDialog):
    """Every file a mod has on GameBanana (colour options are usually separate
    files), with the installed one marked. Pick one to switch to it."""

    def __init__(self, files: list, mod, parent=None):
        super().__init__(parent)
        from sapphire.ui.browse import fmt_date
        self.setWindowTitle("Other variants")
        self.setMinimumSize(620, 380)
        self.files = sorted(files, key=lambda f: (f.archived, -f.date_added, -f.id))
        self.mod = mod
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        n = sum(1 for f in self.files if not f.archived)
        title = QLabel(f"“{mod.name}” has {len(self.files)} file{'s' if len(self.files) != 1 else ''} on GameBanana"
                       + (f" ({len(self.files) - n} old)" if n != len(self.files) else "") + ".")
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 15px;")
        lay.addWidget(title)
        if len(self.files) > 1:
            hint = ("Colour and style options are usually separate files, one per option. Pick the one you "
                    "want and Sapphire downloads it in place of the current file. Picking the file you already "
                    "have downloads it again and keeps every VPK inside it, in case it holds several variants.")
        else:
            hint = ("This mod has a single file, so any variants are inside it. Download it again and Sapphire "
                    "keeps every VPK it ships; they then show up as tick boxes in the details panel.")
        h = QLabel(hint)
        h.setObjectName("Muted")
        h.setWordWrap(True)
        lay.addWidget(h)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["File", "Size", "Added", "Notes"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionMode(QTreeWidget.SingleSelection)
        self.tree.setAllColumnsShowFocus(True)
        current = None
        for f in self.files:
            installed = f.id == mod.file_id
            notes = f.description or ""
            if installed:
                notes = ("Installed · " + notes) if notes else "Installed"
            if f.archived:
                notes = ("Old file · " + notes) if notes else "Old file"
            it = QTreeWidgetItem([f.filename, human_size(f.size), fmt_date(f.date_added), notes])
            it.setToolTip(0, f.filename)
            it.setToolTip(3, f.description or "")
            it.setData(0, Qt.UserRole, f.id)
            if installed:
                font = it.font(0)
                font.setBold(True)
                for c in range(4):
                    it.setFont(c, font)
                current = it
            if f.archived:
                for c in range(4):
                    it.setForeground(c, QColor(theme.MUTED))
            self.tree.addTopLevelItem(it)
        for c in range(4):
            self.tree.resizeColumnToContents(c)
        self.tree.setColumnWidth(0, max(self.tree.columnWidth(0), 220))
        self.tree.header().setStretchLastSection(True)
        self.tree.itemSelectionChanged.connect(self._sync)
        self.tree.itemDoubleClicked.connect(lambda *_: self.accept() if self.ok.isEnabled() else None)
        lay.addWidget(self.tree, 1)
        self.buttons = QDialogButtonBox()
        self.ok = self.buttons.addButton("Switch to this file", QDialogButtonBox.AcceptRole)
        self.ok.setProperty("kind", "primary")
        page = self.buttons.addButton("Open GameBanana page", QDialogButtonBox.ActionRole)
        page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(mod.url)))
        page.setVisible(bool(mod.url))
        self.buttons.addButton("Cancel", QDialogButtonBox.RejectRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        if current is not None:
            self.tree.setCurrentItem(current)
        elif self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self._sync()

    def _sync(self):
        f = self.chosen()
        self.ok.setEnabled(f is not None)
        if f is not None and f.id == self.mod.file_id:
            self.ok.setText("Download again")
        else:
            self.ok.setText("Switch to this file")

    def chosen(self):
        it = self.tree.currentItem()
        if it is None:
            return None
        fid = it.data(0, Qt.UserRole)
        return next((f for f in self.files if f.id == fid), None)


def choose_file(parent, files: list, mod):
    dlg = FileVariantDialog(files, mod, parent)
    if dlg.exec() == QDialog.Accepted:
        return dlg.chosen()
    return None


def confirm(parent, title: str, text: str, action: str, danger: bool = False) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Warning if danger else QMessageBox.Question)
    ok = box.addButton(action, QMessageBox.AcceptRole)
    ok.setProperty("kind", "danger" if danger else "primary")
    box.addButton("Cancel", QMessageBox.RejectRole)
    box.setDefaultButton(ok if not danger else None)
    box.exec()
    return box.clickedButton() is ok


def ask_text(parent, title: str, label: str, text: str = "") -> str | None:
    value, ok = QInputDialog.getText(parent, title, label, text=text)
    value = value.strip()
    return value if ok and value else None


def error(parent, title: str, text: str) -> None:
    QMessageBox.warning(parent, title, text)
