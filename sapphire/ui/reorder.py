"""Drag-to-reorder for item lists, in list and grid layouts.

Qt's built-in drag and drop isn't used for this: in grid (icon) mode QListView
treats an internal drop as "move the icon to a free spot" rather than a
reorder, and some Qt versions delete the dragged item afterwards; on Wayland
the drag also goes through the compositor. Instead the list follows the mouse
itself, draws an insertion marker and emits `moved(uid, index)` on release.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractItemView, QApplication, QListView, QListWidget

from sapphire.ui import theme

ROLE_UID = Qt.UserRole + 1


def draw_lock(p: QPainter, r: QRectF, color: str) -> None:
    """A small padlock filling `r` (drawn, so it doesn't depend on an emoji font)."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    w, h = r.width(), r.height()
    body = QRectF(r.left() + w * 0.14, r.top() + h * 0.44, w * 0.72, h * 0.52)
    shackle = QRectF(r.left() + w * 0.28, r.top() + h * 0.08, w * 0.44, h * 0.62)
    p.setPen(QPen(QColor(color), max(1.4, w * 0.13), Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    p.drawArc(shackle, 0, 180 * 16)
    p.drawLine(QPointF(shackle.left(), shackle.center().y()), QPointF(shackle.left(), body.top()))
    p.drawLine(QPointF(shackle.right(), shackle.center().y()), QPointF(shackle.right(), body.top()))
    path = QPainterPath()
    path.addRoundedRect(body, w * 0.12, w * 0.12)
    p.fillPath(path, QColor(color))
    p.restore()


class ReorderList(QListWidget):
    moved = Signal(str, int)      # uid, the index it should end up at (0 = top)
    refused = Signal(str)         # tried to drag something can_drag() said no to

    def __init__(self):
        super().__init__()
        self.setDragDropMode(QAbstractItemView.NoDragDrop)
        self.setDragEnabled(False)
        self.reorderable = True               # off while the list is filtered
        self.can_drag = lambda uid: True      # e.g. locked mods say no
        self.drag_uid: str | None = None
        self._press: tuple[QPoint, object] | None = None
        self._target: int | None = None
        self._pos = QPoint()
        self._scroll = QTimer(self)
        self._scroll.setInterval(30)
        self._scroll.timeout.connect(self._auto_scroll)

    # ------------------------------------------------------------- geometry
    def _visible(self):
        return [(i, self.item(i)) for i in range(self.count()) if not self.item(i).isHidden()]

    def _wrapped(self) -> bool:
        return self.viewMode() == QListView.IconMode or self.isWrapping()

    def target_at(self, pos: QPoint) -> int:
        """Insertion index for a viewport point: the dragged item goes before this row."""
        wrapped = self._wrapped()
        for i, item in self._visible():
            r = self.visualItemRect(item)
            if wrapped:
                if pos.y() < r.top() or (pos.y() <= r.bottom() and pos.x() < r.center().x()):
                    return i
            elif pos.y() < r.center().y():
                return i
        return self.count()

    def index_of(self, uid: str) -> int:
        return next((i for i in range(self.count()) if self.item(i).data(ROLE_UID) == uid), -1)

    @staticmethod
    def final_index(current: int, target: int) -> int:
        """Where an item at `current` ends up when inserted before row `target`."""
        return target - 1 if target > current else target

    # ---------------------------------------------------------------- mouse
    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        if e.button() == Qt.LeftButton:
            pos = e.position().toPoint()
            item = self.itemAt(pos)
            self._press = (pos, item) if item is not None else None

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if self.drag_uid:
            self._pos = pos
            self._set_target(self.target_at(pos))
            return
        if self._press and e.buttons() & Qt.LeftButton:
            start, item = self._press
            if (pos - start).manhattanLength() < QApplication.startDragDistance():
                return
            self._press = None
            uid = item.data(ROLE_UID)
            if not self.reorderable:
                return
            if not self.can_drag(uid):
                self.refused.emit(uid)
                return
            self.drag_uid = uid
            self._pos = pos
            self.setCursor(Qt.ClosedHandCursor)
            self._scroll.start()
            self._set_target(self.target_at(pos))
            return
        if e.buttons() & Qt.LeftButton:
            return   # pressed but not dragging: don't let Qt drag-select
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.drag_uid:
            uid, target = self.drag_uid, self._target
            self._stop()
            cur = self.index_of(uid)
            if target is not None and cur >= 0:
                dest = self.final_index(cur, target)
                if dest != cur:
                    self.moved.emit(uid, dest)
            e.accept()
            return
        self._press = None
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if self.drag_uid and e.key() == Qt.Key_Escape:
            self._stop()
            return
        super().keyPressEvent(e)

    def _stop(self):
        self.drag_uid = None
        self._target = None
        self._press = None
        self._scroll.stop()
        self.unsetCursor()
        self.viewport().update()

    def _set_target(self, target: int):
        if target != self._target:
            self._target = target
            self.viewport().update()

    def _auto_scroll(self):
        if not self.drag_uid:
            self._scroll.stop()
            return
        margin = theme.px(60)
        h = self.viewport().height()
        bar = self.verticalScrollBar()
        step = 0
        if self._pos.y() < margin:
            step = -max(4, (margin - self._pos.y()) // 3)
        elif self._pos.y() > h - margin:
            step = max(4, (self._pos.y() - (h - margin)) // 3)
        if step:
            bar.setValue(bar.value() + step)
            self._set_target(self.target_at(self._pos))

    # --------------------------------------------------------------- marker
    def paintEvent(self, e):
        super().paintEvent(e)
        if not self.drag_uid or self._target is None:
            return
        cur = self.index_of(self.drag_uid)
        if self.final_index(cur, self._target) == cur:
            return   # dropping here changes nothing: no marker
        vis = self._visible()
        if not vis:
            return
        after = self._target >= self.count() or self.item(self._target).isHidden()
        anchor = vis[-1][1] if after else self.item(self._target)
        r = QRectF(self.visualItemRect(anchor))
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing)
        color = QColor(theme.ACCENT)
        p.setPen(QPen(color, theme.px(3), Qt.SolidLine, Qt.RoundCap))
        p.setBrush(color)
        dot = theme.px(4)
        if self._wrapped():
            x = (r.right() - 1) if after else (r.left() + 1)
            a, b = QPointF(x, r.top() + theme.px(8)), QPointF(x, r.bottom() - theme.px(8))
        else:
            y = (r.bottom() - 1) if after else (r.top() + 1)
            a, b = QPointF(r.left() + theme.px(10), y), QPointF(r.right() - theme.px(10), y)
        p.drawLine(a, b)
        p.drawEllipse(a, dot, dot)
        p.drawEllipse(b, dot, dot)
        p.end()
