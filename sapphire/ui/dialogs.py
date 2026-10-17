"""Small dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QInputDialog, QLabel,
                               QMessageBox, QScrollArea, QVBoxLayout, QWidget)

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
