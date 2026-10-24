"""Priority: a compact, whole-library view of the load order.

One short row per mod, top wins. Drag rows, use the move buttons, or type the
number a mod should have. Locked mods keep their number while everything else
moves around them. Works on a draft; nothing changes until Save.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidgetItem, QPushButton, QSpinBox, QStyle, QStyledItemDelegate, QVBoxLayout)

from sapphire import library
from sapphire.ui import theme
from sapphire.ui.reorder import ROLE_UID, ReorderList, draw_lock


class _Row(QStyledItemDelegate):
    def __init__(self, dlg: "PriorityDialog"):
        super().__init__(dlg.list)
        self.dlg = dlg

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), theme.px(36))

    def paint(self, p: QPainter, option, index):
        uid = index.data(ROLE_UID)
        mod = self.dlg.mods.get(uid)
        if mod is None:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect).adjusted(2, 1, -2, -1)
        selected = bool(option.state & QStyle.State_Selected)
        if self.dlg.list.drag_uid == uid:
            p.setOpacity(0.45)
        bg = QPainterPath()
        bg.addRoundedRect(r, 5, 5)
        p.fillPath(bg, QColor(theme.RAISED if selected else (theme.PANEL if index.row() % 2 == 0 else theme.BG)))
        if selected:
            p.setPen(QPen(QColor(theme.ACCENT_LO), 1.2))
            p.drawPath(bg)
        locked = uid in self.dlg.locks
        x = r.left() + theme.px(8)
        s = theme.px(12)
        if locked:
            draw_lock(p, QRectF(x, r.center().y() - s / 2, s, s), theme.ACCENT)
        else:
            f = QFont(p.font())
            f.setPixelSize(theme.px(13))
            p.setFont(f)
            p.setPen(QColor(theme.LINE))
            p.drawText(QRectF(x - 2, r.top(), s + 4, r.height()), Qt.AlignCenter, "⠿")
        x += s + theme.px(8)
        f = QFont(p.font())
        f.setPixelSize(theme.px(13))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.ACCENT if mod.enabled else theme.MUTED))
        nw = theme.px(34)
        p.drawText(QRectF(x, r.top(), nw, r.height()), Qt.AlignVCenter | Qt.AlignRight, f"#{index.row() + 1}")
        x += nw + theme.px(12)
        tail = []
        if locked:
            tail.append("locked")
        if not mod.enabled:
            tail.append("off")
        f.setBold(False)
        f.setPixelSize(theme.px(12))
        p.setFont(f)
        tail_text = "  ·  ".join(tail)
        tw = p.fontMetrics().horizontalAdvance(tail_text) if tail_text else 0
        if tail_text:
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(r.right() - tw - theme.px(10), r.top(), tw, r.height()),
                       Qt.AlignVCenter | Qt.AlignRight, tail_text)
        avail = r.right() - x - tw - theme.px(20)
        f.setPixelSize(theme.px(13))
        p.setFont(f)
        p.setPen(QColor(theme.TEXT if mod.enabled else theme.MUTED))
        name = mod.name + (f"   {mod.category}" if mod.category else "")
        p.drawText(QRectF(x, r.top(), avail, r.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   p.fontMetrics().elidedText(name, Qt.ElideRight, int(avail)))
        p.restore()


class PriorityDialog(QDialog):
    def __init__(self, parent, manager, select: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Priority")
        self.mgr = manager
        self.mods = dict(manager.lib.mods)
        self.order: list[str] = [u for u in manager.lib.order if u in self.mods]
        self.locks: dict[str, int] = manager.lib.locks()
        self.resize(theme.px(720), theme.px(640))

        lay = QVBoxLayout(self)
        intro = QLabel("Top wins: when two mods change the same file, the one with the lower number is used. "
                       "Drag rows, or pick one and use the buttons. A locked mod keeps its number while "
                       "everything else moves around it, including when you install or remove mods.")
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        find = QLineEdit()
        find.setPlaceholderText("Find a mod (jumps to it)")
        find.setClearButtonEnabled(True)
        find.textChanged.connect(self._find)
        lay.addWidget(find)
        self.find = find

        body = QHBoxLayout()
        self.list = ReorderList()
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setUniformItemSizes(True)
        self.list.setItemDelegate(_Row(self))
        self.list.can_drag = lambda uid: uid not in self.locks
        self.list.moved.connect(self._move)
        self.list.refused.connect(lambda uid: self.note.setText(
            f"{self.mods[uid].name} is locked. Unlock it to drag it, or type a new number for its lock."))
        self.list.currentItemChanged.connect(lambda *_: self._sync_buttons())
        body.addWidget(self.list, 1)

        side = QVBoxLayout()
        self.buttons = {}
        for key, label in (("top", "Move to top"), ("up", "Up"), ("down", "Down"), ("bottom", "Move to bottom")):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, k=key: self._step(k))
            side.addWidget(b)
            self.buttons[key] = b
        side.addSpacing(theme.px(10))
        side.addWidget(QLabel("Move to number"))
        num = QHBoxLayout()
        self.number = QSpinBox()
        self.number.setRange(1, max(1, len(self.order)))
        num.addWidget(self.number, 1)
        go = QPushButton("Go")
        go.clicked.connect(self._go)
        num.addWidget(go)
        side.addLayout(num)
        side.addSpacing(theme.px(10))
        self.lock_btn = QPushButton("Lock")
        self.lock_btn.clicked.connect(self._toggle_lock)
        side.addWidget(self.lock_btn)
        unlock_all = QPushButton("Unlock all")
        unlock_all.clicked.connect(self._unlock_all)
        side.addWidget(unlock_all)
        self.unlock_all = unlock_all
        side.addStretch(1)
        body.addLayout(side)
        lay.addLayout(body, 1)

        self.note = QLabel("")
        self.note.setObjectName("Muted")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

        self._fill(select)

    # ----------------------------------------------------------------- state
    def _fill(self, select: str | None = None):
        bar = self.list.verticalScrollBar().value()
        self.list.clear()
        for uid in self.order:
            item = QListWidgetItem()
            item.setData(ROLE_UID, uid)
            item.setToolTip(self.mods[uid].name)
            self.list.addItem(item)
        self.list.verticalScrollBar().setValue(bar)
        if select in self.order:
            self.list.setCurrentRow(self.order.index(select))
            self.list.scrollToItem(self.list.currentItem())
        self._sync_buttons()

    def current(self) -> str | None:
        item = self.list.currentItem()
        return item.data(ROLE_UID) if item else None

    def _sync_buttons(self):
        uid = self.current()
        locked = uid in self.locks
        i = self.order.index(uid) if uid else -1
        for key, b in self.buttons.items():
            edge = (key in ("top", "up") and i == 0) or (key in ("down", "bottom") and i == len(self.order) - 1)
            b.setEnabled(uid is not None and not locked and not edge)
        self.number.setEnabled(uid is not None)
        if uid:
            self.number.blockSignals(True)
            self.number.setValue(i + 1)
            self.number.blockSignals(False)
        self.lock_btn.setEnabled(uid is not None)
        self.lock_btn.setText(f"Unlock from #{i + 1}" if locked else (f"Lock at #{i + 1}" if uid else "Lock"))
        self.unlock_all.setEnabled(bool(self.locks))

    def _move(self, uid: str, index: int):
        self.order = library.move(self.order, self.locks, uid, index)
        self.note.setText("")
        self._fill(uid)

    def _step(self, key: str):
        uid = self.current()
        if not uid:
            return
        i = self.order.index(uid)
        self._move(uid, {"top": 0, "up": i - 1, "down": i + 1, "bottom": len(self.order) - 1}[key])

    def _go(self):
        uid = self.current()
        if uid:
            self._move(uid, self.number.value() - 1)

    def _toggle_lock(self):
        uid = self.current()
        if not uid:
            return
        if uid in self.locks:
            del self.locks[uid]
        else:
            self.locks[uid] = self.order.index(uid)
        self._fill(uid)

    def _unlock_all(self):
        self.locks.clear()
        self._fill(self.current())

    def _find(self, text: str, step: bool = False):
        text = text.strip().lower()
        if not text:
            return
        hits = [i for i, u in enumerate(self.order) if text in self.mods[u].name.lower()]
        if not hits:
            return
        cur = self.list.currentRow()
        i = next((h for h in hits if h > cur), hits[0]) if step else (cur if cur in hits else hits[0])
        self.list.setCurrentRow(i)
        self.list.scrollToItem(self.list.currentItem(), QAbstractItemView.PositionAtCenter)

    def keyPressEvent(self, e):
        # Enter in the number or find box acts there instead of pressing Save.
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            w = self.focusWidget()
            if w is self.number or (w is not None and w.parent() is self.number):
                self.number.interpretText()
                self._go()
                return
            if w is self.find:
                self._find(self.find.text(), step=True)
                return
        super().keyPressEvent(e)

    def accept(self):
        self.mgr.set_priority(self.order, self.locks)
        super().accept()
