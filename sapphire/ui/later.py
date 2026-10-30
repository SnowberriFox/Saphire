"""Queued for later: reminders you add mid-match ("swap this variant", "get rid
of this one") and work through once Deadlock is closed (Ham's idea)."""

from __future__ import annotations

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QRadioButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from sapphire.ui import theme

# what each kind means, as you pick it and as it's shown back
KINDS = {
    "variant": ("Change the variant", "Change variant"),
    "swap": ("Swap it for a different mod", "Find a different one"),
    "remove": ("Get rid of it", "Remove it"),
    "note": ("Something else (just a note)", "Note"),
}


def describe(item) -> str:
    """'Change variant: the blue one', for lists and the detail panel."""
    short = KINDS.get(item.kind, KINDS["note"])[1]
    if item.kind == "note":
        return item.note or "No note"
    return f"{short}: {item.note}" if item.note else short


class RemindDialog(QDialog):
    """Pick what to do with a mod later, plus an optional note."""

    def __init__(self, parent, mod, existing=None, running: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Remind me later")
        self.setMinimumWidth(theme.px(420))
        self.setStyleSheet("QLabel, QRadioButton { background: transparent; }")
        self.cleared = False
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        title = QLabel(f"What do you want to do with “{mod.name}”?")
        title.setWordWrap(True)
        lay.addWidget(title)
        hint = QLabel("Sapphire keeps a list and shows it when Deadlock closes."
                      if running else "It goes on your Queued for later list on the Installed page.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.group = QButtonGroup(self)
        self.radios: dict[str, QRadioButton] = {}
        for kind, (label, _short) in KINDS.items():
            rb = QRadioButton(label)
            self.group.addButton(rb)
            self.radios[kind] = rb
            lay.addWidget(rb)
        (self.radios.get(existing.kind) if existing else self.radios["variant"]).setChecked(True)
        self.note = QLineEdit(existing.note if existing else "")
        self.note.setPlaceholderText("Note (optional), e.g. “try the red one”")
        self.note.setMaxLength(200)
        lay.addWidget(self.note)
        box = QDialogButtonBox()
        ok = box.addButton("Save" if existing else "Add to the list", QDialogButtonBox.AcceptRole)
        ok.setProperty("kind", "primary")
        if existing:
            clear = box.addButton("Remove reminder", QDialogButtonBox.DestructiveRole)
            clear.clicked.connect(self._clear)
        box.addButton("Cancel", QDialogButtonBox.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.note.setFocus()

    def _clear(self):
        self.cleared = True
        self.accept()

    @property
    def kind(self) -> str:
        return next(k for k, rb in self.radios.items() if rb.isChecked())


class LaterDialog(QDialog):
    """The profile's queue, each row with buttons to deal with it right there.
    Modeless, so you can tick variants in the Installed panel while it's open."""

    act = Signal(str, str)   # uid, action: show / variant / swap / remove_profile / uninstall / done

    def __init__(self, parent, manager):
        super().__init__(parent)
        self.mgr = manager
        self.setWindowTitle("Queued for later")
        self.resize(theme.px(560), theme.px(480))
        self.setStyleSheet("QLabel { background: transparent; } QScrollArea, #LaterBody { background: transparent; }")
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        self.head = QLabel()
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lay.addWidget(self.scroll, 1)
        self.empty = QLabel("All done. Nothing left on the list.")
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.empty, 1)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.close)
        lay.addWidget(box)
        self.after_game = False
        self.rows: dict[str, QWidget] = {}

    def reload(self, after_game: bool | None = None, running: bool = False):
        if after_game is not None:
            self.after_game = after_game
        items = self.mgr.lib.later()
        n = len(items)
        prof = html.escape(self.mgr.lib.active_profile or "")
        if self.after_game and n:
            self.head.setText(f"Deadlock's closed. While you were playing you queued "
                              f"{n} thing{'s' if n != 1 else ''} in <b>{prof}</b>:")
        elif running and n:
            self.head.setText(f"Deadlock is running, so changes apply when you close it. "
                              f"Queued in <b>{prof}</b>:")
        else:
            self.head.setText(f"Things you queued in <b>{prof}</b>. Deal with each one, or mark it done.")
        body = QWidget()
        body.setObjectName("LaterBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 4, 0)
        bl.setSpacing(8)
        self.rows = {}
        for item in items:
            mod = self.mgr.lib.mods[item.uid]
            row = self._row(item, mod)
            self.rows[item.uid] = row
            bl.addWidget(row)
        bl.addStretch(1)
        self.scroll.setWidget(body)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setVisible(bool(items))
        self.empty.setVisible(not items)

    def _row(self, item, mod) -> QWidget:
        frame = QFrame()
        frame.setObjectName("LaterRow")
        frame.setStyleSheet(f"#LaterRow {{ background: {theme.PANEL}; border: 1px solid {theme.LINE}; "
                            f"border-radius: {theme.rad(7):g}px; }} #LaterRow QLabel {{ background: transparent; }}")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        name = QLabel(f"<b>{html.escape(mod.name)}</b>" + ("" if mod.enabled else "  <i>(off)</i>"))
        name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lay.addWidget(name)
        what = QLabel(describe(item))
        what.setObjectName("Muted")
        what.setWordWrap(True)
        what.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lay.addWidget(what)
        buttons = QHBoxLayout()
        uid = item.uid

        def add(label, action, kind=None, tip=""):
            b = QPushButton(label)
            if kind:
                b.setProperty("kind", kind)
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(lambda _c=False: self.act.emit(uid, action))
            buttons.addWidget(b)
            return b

        if item.kind == "variant":
            add("Pick a variant", "variant", "primary",
                "Shows its variants (or its other files on GameBanana) so you can switch")
        elif item.kind == "swap":
            add("Find a different one", "swap", "primary", "Opens Browse on the same category")
        elif item.kind == "remove":
            add(f"Remove from {self.mgr.lib.active_profile}", "remove_profile", "primary",
                "Takes it out of this profile. It stays downloaded for your other profiles.")
            add("Uninstall…", "uninstall", "danger", "Deletes it from Sapphire and every profile")
        add("Show", "show", tip="Select it on the Installed page")
        buttons.addStretch(1)
        add("Done", "done", tip="Take it off the list")
        lay.addLayout(buttons)
        return frame
