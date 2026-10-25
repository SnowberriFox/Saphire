"""Installed page: load order, enable/disable, conflicts, updates."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMenu, QPushButton, QScrollArea, QSizePolicy,
                               QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from sapphire import steam
from sapphire.conflicts import ModConflicts
from sapphire.library import InstalledMod
from sapphire.ui import theme
from sapphire.ui.browse import fmt_date
from sapphire.ui.reorder import ROLE_UID, ReorderList, draw_lock


class RowDelegate(QStyledItemDelegate):
    def __init__(self, page):
        super().__init__(page.list)
        self.page = page
        self.mode = "list"
        self.card = QSize(theme.px(200), theme.px(196))

    def sizeHint(self, option, index):
        if self.mode == "grid":
            return self.card
        return QSize(option.rect.width(), theme.px(66))

    def _toggle_rect(self, rect) -> QRectF:
        r = QRectF(rect).adjusted(6, 6, -6, -6)
        return QRectF(r.right() - theme.px(30), r.top() + theme.px(8), theme.px(22), theme.px(22))

    def editorEvent(self, event, model, option, index):
        if self.mode == "grid" and event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            if self._toggle_rect(option.rect).contains(QPointF(event.position())):
                state = index.data(Qt.CheckStateRole)
                new = Qt.Unchecked if state in (Qt.Checked, Qt.Checked.value) else Qt.Checked
                model.setData(index, new, Qt.CheckStateRole)
                return True
        return super().editorEvent(event, model, option, index)

    def paint(self, p: QPainter, option, index):
        uid = index.data(ROLE_UID)
        mod: InstalledMod | None = self.page.mgr.lib.mods.get(uid)
        if mod is None:
            return
        if self.mode == "grid":
            return self._paint_card(p, option, mod, uid)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style()
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect).adjusted(4, 3, -4, -3)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        path = QPainterPath()
        path.addRoundedRect(r, 7, 7)
        p.fillPath(path, QColor(theme.RAISED if selected else theme.PANEL))
        if selected:
            p.setPen(QPen(QColor(theme.ACCENT_LO), 1.2))
            p.drawPath(path)
        elif hovered:
            p.setPen(QPen(QColor(theme.LINE), 1))
            p.drawPath(path)

        dim = not mod.enabled
        if self.page.list.drag_uid == uid:
            p.setOpacity(0.45)
        # check toggle where the style expects it (so clicks land on it). Styles
        # differ: some put it a little way in, some (KDE's Breeze) right at the edge.
        check = style.subElementRect(QStyle.SE_ItemViewItemCheckIndicator, opt, opt.widget)
        cr = QRectF(check).adjusted(-1, -1, 1, 1)
        f = QFont(p.font())
        f.setPixelSize(theme.px(14))
        p.setFont(f)
        if cr.left() - r.left() >= 18:
            # room for the drag grip before the box
            p.setPen(QColor(theme.LINE))
            p.drawText(QRectF(r.left() + 4, r.top(), 14, r.height()), Qt.AlignCenter, "⠿")
        cp = QPainterPath()
        cp.addRoundedRect(cr, 4, 4)
        if mod.enabled:
            p.fillPath(cp, QColor(theme.ACCENT))
            p.setPen(QPen(QColor(theme.ON_ACCENT), 2))
            tl = cr.topLeft()
            p.drawPolyline(QPolygonF([tl + QPointF(cr.width() * .25, cr.height() * .52),
                                      tl + QPointF(cr.width() * .43, cr.height() * .70),
                                      tl + QPointF(cr.width() * .76, cr.height() * .32)]))
        else:
            p.fillPath(cp, QColor(theme.BG))
            p.setPen(QPen(QColor(theme.LINE), 1.2))
            p.drawPath(cp)

        # padlock (locked mods) in its own slot after the box, then the load-order
        # position (#1 wins clashes), dimmed for mods that are off
        x = cr.right() + theme.px(8)
        lock_w = theme.px(14)
        if mod.locked:
            s = theme.px(12)
            draw_lock(p, QRectF(x + 1, r.center().y() - s / 2, s, s), theme.MUTED if dim else theme.ACCENT)
        x += lock_w
        rank = self.page.rank.get(uid)
        f.setPixelSize(theme.px(13))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.MUTED if dim else theme.ACCENT))
        num_w = theme.px(28)
        p.drawText(QRectF(x, r.top(), num_w, r.height()), Qt.AlignVCenter | Qt.AlignRight,
                   f"{rank}" if rank else "–")
        x += num_w + theme.px(12)

        # thumbnail
        thumb = QRectF(x, r.top() + 7, theme.px(80), r.height() - 14)
        tp = QPainterPath()
        tp.addRoundedRect(thumb, 5, 5)
        pix = self.page.images.get(mod.thumb_url) if mod.thumb_url else None
        p.save()
        p.setClipPath(tp)
        if pix is not None and not pix.isNull():
            scaled = pix.scaled(int(thumb.width()), int(thumb.height()), Qt.KeepAspectRatioByExpanding,
                                Qt.SmoothTransformation)
            sx = (scaled.width() - thumb.width()) / 2
            sy = (scaled.height() - thumb.height()) / 2
            if dim:
                p.setOpacity(0.35)
            p.drawPixmap(thumb.toRect(), scaled, QRect(int(sx), int(sy), int(thumb.width()), int(thumb.height())))
            p.setOpacity(1)
        else:
            p.fillPath(tp, QColor(theme.BG))
            p.setPen(QColor(theme.LINE))
            p.setFont(theme.display_font(20))
            p.drawText(thumb, Qt.AlignCenter, (mod.name[:1] or "?").upper())
        p.restore()
        x = thumb.right() + 12

        # badges (right side)
        badges = []
        if mod.update:
            badges.append(("Update ready", theme.ACCENT, theme.ON_ACCENT))
        c: ModConflicts | None = self.page.conflicts.get(uid)
        if mod.enabled and c:
            if c.losing:
                badges.append((f"Overridden: {c.losing} file{'s' if c.losing != 1 else ''}", theme.DANGER_BG, theme.DANGER_TEXT))
            if c.winning:
                badges.append((f"Wins: {c.winning} file{'s' if c.winning != 1 else ''}", theme.OK_BG, theme.VERDIGRIS))
        cam = self.page.camera_status(uid)
        if mod.enabled and cam == "fixed":
            badges.append(("Camera fixed", theme.OK_BG, theme.VERDIGRIS))
        elif mod.enabled and cam == "warning":
            badges.append(("Camera: check", theme.DANGER_BG, theme.DANGER_TEXT))
        bf = QFont(p.font())
        bf.setPixelSize(theme.px(11))
        bf.setBold(True)
        p.setFont(bf)
        bx = r.right() - 10
        for text, bg, fg in reversed(badges):
            w = p.fontMetrics().horizontalAdvance(text) + 16
            br = QRectF(bx - w, r.center().y() - 11, w, 22)
            bp = QPainterPath()
            bp.addRoundedRect(br, 11, 11)
            p.fillPath(bp, QColor(bg))
            p.setPen(QColor(fg))
            p.drawText(br, Qt.AlignCenter, text)
            bx -= w + 6

        text_w = bx - x - 10
        f = QFont(p.font())
        f.setPixelSize(theme.px(14))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.MUTED if dim else theme.TEXT))
        p.drawText(QRectF(x, r.top() + 12, text_w, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(mod.name, Qt.ElideRight, int(text_w)))
        f.setBold(False)
        f.setPixelSize(theme.px(12))
        p.setFont(f)
        p.setPen(QColor(theme.MUTED))
        bits = []
        if mod.source == "gamebanana":
            bits.append(f"by {mod.author}" if mod.author else "GameBanana")
            if mod.category:
                bits.append(mod.category)
        else:
            bits.append("Local file")
        if len(mod.vpks) > 1:
            bits.append(f"{len(mod.vpks)} VPKs")
        if dim:
            bits.append("off")
        sub = "    ".join(bits)
        p.drawText(QRectF(x, r.top() + 33, text_w, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(sub, Qt.ElideRight, int(text_w)))
        p.restore()


    def _paint_card(self, p: QPainter, option, mod: InstalledMod, uid: str):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect).adjusted(6, 6, -6, -6)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        dim = not mod.enabled
        if self.page.list.drag_uid == uid:
            p.setOpacity(0.45)
        path = QPainterPath()
        path.addRoundedRect(r, 8, 8)
        p.fillPath(path, QColor(theme.PANEL))
        if selected or hovered:
            p.setPen(QPen(QColor(theme.ACCENT if selected else theme.ACCENT_LO), 1.5))
            p.drawPath(path)
        img_h = r.width() * 9 / 16
        img = QRectF(r.left(), r.top(), r.width(), img_h)
        p.save()
        clip = QPainterPath()
        clip.setFillRule(Qt.WindingFill)
        clip.addRoundedRect(img, 8, 8)
        clip.addRect(QRectF(img.left(), img.top() + 10, img.width(), img_h - 10))
        p.setClipPath(clip.simplified())
        pix = self.page.images.get(mod.thumb_url) if mod.thumb_url else None
        if pix is not None and not pix.isNull():
            scaled = pix.scaled(int(img.width()), int(img.height()), Qt.KeepAspectRatioByExpanding,
                                Qt.SmoothTransformation)
            sx = (scaled.width() - img.width()) / 2
            sy = (scaled.height() - img.height()) / 2
            if dim:
                p.setOpacity(0.35)
            p.drawPixmap(img.toRect(), scaled, QRect(int(sx), int(sy), int(img.width()), int(img.height())))
            p.setOpacity(1)
        else:
            p.fillRect(img, QColor(theme.RAISED if not dim else theme.BG))
            p.setPen(QColor(theme.LINE))
            p.setFont(theme.display_font(30))
            p.drawText(img, Qt.AlignCenter, (mod.name[:1] or "?").upper())
        p.restore()
        # rank badge (top-left) and toggle (top-right)
        rank = self.page.rank.get(uid)
        bf = QFont(p.font())
        bf.setPixelSize(theme.px(11))
        bf.setBold(True)
        p.setFont(bf)
        if rank:
            text = f"#{rank}"
            lock_w = theme.px(14) if mod.locked else 0
            w = p.fontMetrics().horizontalAdvance(text) + theme.px(12) + lock_w
            br = QRectF(r.left() + theme.px(8), r.top() + theme.px(8), w, theme.px(20))
            bp = QPainterPath()
            bp.addRoundedRect(br, theme.px(10), theme.px(10))
            fg = theme.ON_ACCENT if not dim else theme.MUTED
            p.fillPath(bp, QColor(theme.ACCENT if not dim else theme.BG))
            p.setPen(QColor(fg))
            p.drawText(br.adjusted(lock_w, 0, 0, 0), Qt.AlignCenter, text)
            if mod.locked:
                s = theme.px(11)
                draw_lock(p, QRectF(br.left() + theme.px(7), br.center().y() - s / 2 - 0.5, s, s), fg)
        tr = self._toggle_rect(option.rect)
        tp = QPainterPath()
        tp.addRoundedRect(tr, 5, 5)
        if mod.enabled:
            p.fillPath(tp, QColor(theme.ACCENT))
            p.setPen(QPen(QColor(theme.ON_ACCENT), 2))
            tl = tr.topLeft()
            p.drawPolyline(QPolygonF([tl + QPointF(tr.width() * .25, tr.height() * .52),
                                      tl + QPointF(tr.width() * .43, tr.height() * .70),
                                      tl + QPointF(tr.width() * .76, tr.height() * .32)]))
        else:
            p.fillPath(tp, QColor(theme.BG))
            p.setPen(QPen(QColor(theme.MUTED), 1.4))
            p.drawPath(tp)
        # status badges along the bottom of the image
        badges = []
        if mod.update:
            badges.append(("Update", theme.ACCENT, theme.ON_ACCENT))
        c = self.page.conflicts.get(uid)
        if mod.enabled and c:
            if c.losing:
                badges.append((f"Overridden ×{c.losing}", theme.DANGER_BG, theme.DANGER_TEXT))
            elif c.winning:
                badges.append((f"Wins ×{c.winning}", theme.OK_BG, theme.VERDIGRIS))
        cam = self.page.camera_status(uid)
        if mod.enabled and cam == "fixed":
            badges.append(("Cam fixed", theme.OK_BG, theme.VERDIGRIS))
        elif mod.enabled and cam == "warning":
            badges.append(("Cam ?", theme.DANGER_BG, theme.DANGER_TEXT))
        bx = r.left() + theme.px(8)
        for text, bg, fg in badges:
            w = p.fontMetrics().horizontalAdvance(text) + theme.px(12)
            br = QRectF(bx, img.bottom() - theme.px(26), w, theme.px(20))
            bp = QPainterPath()
            bp.addRoundedRect(br, theme.px(10), theme.px(10))
            p.fillPath(bp, QColor(bg))
            p.setPen(QColor(fg))
            p.drawText(br, Qt.AlignCenter, text)
            bx += w + theme.px(6)
        # name + author
        f = QFont(p.font())
        f.setPixelSize(theme.px(13))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.MUTED if dim else theme.TEXT))
        tw = r.width() - theme.px(20)
        p.drawText(QRectF(r.left() + theme.px(10), img.bottom() + theme.px(6), tw, theme.px(20)),
                   Qt.AlignLeft | Qt.AlignVCenter, p.fontMetrics().elidedText(mod.name, Qt.ElideRight, int(tw)))
        f.setBold(False)
        f.setPixelSize(theme.px(12))
        p.setFont(f)
        p.setPen(QColor(theme.MUTED))
        sub = (f"by {mod.author}" if mod.author else ("Local file" if mod.source == "local" else "GameBanana"))
        if dim:
            sub += "    off"
        p.drawText(QRectF(r.left() + theme.px(10), img.bottom() + theme.px(26), tw, theme.px(18)),
                   Qt.AlignLeft | Qt.AlignVCenter, p.fontMetrics().elidedText(sub, Qt.ElideRight, int(tw)))
        p.restore()


class ModList(ReorderList):
    def __init__(self):
        super().__init__()
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setSpacing(0)
        # Scroll while dragging near the top or bottom edge (a row's height, not Qt's 16px).
        self.setAutoScroll(True)
        self.setAutoScrollMargin(theme.px(70))

    def set_mode(self, mode: str):
        delegate = self.itemDelegate()
        if isinstance(delegate, RowDelegate):
            delegate.mode = mode
        if mode == "grid":
            self.setViewMode(QListWidget.IconMode)
            self.setFlow(QListWidget.LeftToRight)
            self.setWrapping(True)
        else:
            self.setViewMode(QListWidget.ListMode)
            self.setFlow(QListWidget.TopToBottom)
            self.setWrapping(False)
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setDragEnabled(False)   # ReorderList does the dragging (see reorder.py)
        self.relayout()

    def relayout(self):
        delegate = self.itemDelegate()
        if not isinstance(delegate, RowDelegate):
            return
        avail = self.viewport().width() - 4
        if delegate.mode == "grid":
            cols = max(1, avail // theme.px(200))
            w = avail // cols
            delegate.card = QSize(w, int((w - 12) * 9 / 16) + theme.px(60))
            self.setGridSize(delegate.card)
        else:
            self.setGridSize(QSize())
        self.scheduleDelayedItemsLayout()
        self.viewport().update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.relayout()


class DetailPanel(QScrollArea):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setObjectName("DetailPanel")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setFixedWidth(theme.px(360))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body.setObjectName("DetailPanel")
        self.body.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setWidget(self.body)
        self.lay = QVBoxLayout(self.body)
        self.lay.setContentsMargins(16, 16, 16, 16)
        self.lay.setSpacing(10)
        self.uid = None
        page.images.loaded.connect(self._image_loaded)
        self.show_mod(None)

    def _load_order(self, mod: InstalledMod):
        h = QLabel("Load order")
        h.setObjectName("SideTitle")
        self.lay.addWidget(h)
        pos, total = self.page.rank.get(mod.uid), len(self.page.mgr.lib.order)
        row = QHBoxLayout()
        where = QLabel(f"#{pos} of {total}" + (", locked" if mod.locked else ""))
        where.setStyleSheet("background: transparent;")
        row.addWidget(where, 1)
        lock = QPushButton("Unlock" if mod.locked else f"Lock at #{pos}")
        lock.setToolTip("A locked mod keeps its number while you drag, install or remove other mods")
        lock.clicked.connect(lambda: self.page.set_locked(mod.uid, not mod.locked))
        row.addWidget(lock)
        edit = QPushButton("Priority…")
        edit.clicked.connect(self.page.priority_requested)
        row.addWidget(edit)
        self.lay.addLayout(row)
        if mod.locked:
            note = QLabel("Stays at this number while you reorder, install or remove other mods.")
            note.setObjectName("Muted")
            note.setWordWrap(True)
            self.lay.addWidget(note)

    def _variants_changed(self, uid: str):
        from sapphire.ui.dialogs import error
        labels = [label for label, cb in self._variant_boxes if cb.isChecked()]
        try:
            self.page.mgr.set_variants(uid, labels)
        except Exception as exc:  # noqa: BLE001
            error(self, "Keep one on", str(exc))
            self.show_mod(uid)
            return
        self.page.changed.emit()

    def _image_loaded(self, url: str):
        mod = self.page.mgr.lib.mods.get(self.uid) if self.uid else None
        if mod and mod.thumb_url == url:
            self.show_mod(self.uid)

    def _clear(self):
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().hide()          # gone now, not just when the deferred delete runs
                it.widget().deleteLater()
            elif it.layout():
                while it.layout().count():
                    sub = it.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().hide()
                        sub.widget().deleteLater()

    def show_mod(self, uid):
        self.uid = uid
        self._clear()
        mod = self.page.mgr.lib.mods.get(uid) if uid else None
        if mod is None:
            lbl = QLabel("Select a mod to see what it changes and what it clashes with.\n\n"
                         "Drag mods to reorder. When two mods change the same file, the one "
                         "higher in the list wins. Right-click a mod to lock it in place.")
            lbl.setObjectName("Muted")
            lbl.setWordWrap(True)
            self.lay.addWidget(lbl)
            self.lay.addStretch(1)
            return
        if mod.thumb_url:
            img = QLabel()
            img.setAlignment(Qt.AlignCenter)
            img.setStyleSheet(f"background: {theme.RAISED}; border-radius: 6px;")
            img.setMinimumHeight(theme.px(150))
            pix = self.page.images.get(mod.thumb_url)
            if pix is not None and not pix.isNull():
                w = self.width() - 32 - 14
                scaled = pix.scaledToWidth(max(200, w), Qt.SmoothTransformation)
                if scaled.height() > theme.px(240):
                    scaled = pix.scaledToHeight(theme.px(240), Qt.SmoothTransformation)
                img.setPixmap(scaled)
                img.setMinimumHeight(0)
            else:
                img.setText("Loading preview…")
                img.setObjectName("Muted")
            self.lay.addWidget(img)
        title = QLabel(mod.name)
        title.setObjectName("DetailTitle")
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lay.addWidget(title)
        info = []
        if mod.source == "gamebanana":
            info.append(f"by {mod.author or 'unknown'}")
            if mod.category:
                info.append(mod.category)
            info.append(f"File: {mod.file_name} ({fmt_date(mod.file_date)})")
        else:
            info.append(f"Imported from {mod.file_name}")
        info.append(f"Installed {fmt_date(mod.installed_at)}")
        if mod.note:
            info.append(mod.note)
        meta = QLabel("\n".join(info))
        meta.setObjectName("Muted")
        meta.setWordWrap(True)
        meta.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lay.addWidget(meta)

        row = QHBoxLayout()
        toggle = QPushButton("Turn off" if mod.enabled else "Turn on")
        toggle.clicked.connect(lambda: self.page.toggle(mod.uid))
        row.addWidget(toggle)
        busy = self.page.busy(mod.uid)
        self._shown_busy = busy
        if mod.update:
            upd = QPushButton("Updating…" if busy else "Update")
            upd.setProperty("kind", "primary")
            upd.setEnabled(not busy)
            upd.clicked.connect(lambda: self.page.update_requested.emit(mod.uid))
            row.addWidget(upd)
        if mod.url:
            gb = QPushButton("GameBanana")
            gb.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(mod.url)))
            row.addWidget(gb)
        if mod.source == "local":
            ident = QPushButton("Identify")
            ident.setToolTip("Find this mod's GameBanana page so it gets a name, thumbnail and updates")
            ident.clicked.connect(lambda: self.page.identify_requested.emit([mod.uid]))
            row.addWidget(ident)
        self.lay.addLayout(row)
        if (mod.model == "Sound" and mod.gb_id and not mod.audio_url
                and mod.uid not in self.page._audio_checked):
            # Installed before Sapphire kept preview links: look it up once.
            self.page._audio_checked.add(mod.uid)
            from sapphire.ui.workers import run

            def got(details, uid=mod.uid):
                m = self.page.mgr.lib.mods.get(uid)
                if m and details.submission.audio_url:
                    m.audio_url = details.submission.audio_url
                    self.page.mgr.lib.save()
                    if self.uid == uid:
                        self.show_mod(uid)
            run(self.page.mgr.gb.details, mod.model, mod.gb_id, on_done=got, on_error=lambda e: None)
        extra = QHBoxLayout()
        if mod.audio_url and self.page.player is not None:
            from sapphire.ui.audio import PreviewButton
            extra.addWidget(PreviewButton(self.page.player, mod.audio_url))
        if self.page.mgr.can_roll_back(mod.uid):
            prev = mod.previous or {}
            back = QPushButton("Roll back")
            back.setToolTip(f"Go back to {prev.get('file_name') or 'the previous version'} "
                            f"({fmt_date(int(prev.get('file_date') or 0))}). The current version is kept, "
                            "so you can roll forward again.")
            back.clicked.connect(lambda: self.page.rollback_requested.emit(mod.uid))
            extra.addWidget(back)
        if extra.count():
            extra.addStretch(1)
            self.lay.addLayout(extra)
        if mod.skip_file_id and mod.update and mod.update.file_id == mod.skip_file_id:
            sk = QLabel("You rolled back from the newest file, so automatic updates leave this mod alone.")
            sk.setObjectName("Muted")
            sk.setWordWrap(True)
            self.lay.addWidget(sk)
        if mod.update:
            u = QLabel(f"New file: {mod.update.file_name} ({fmt_date(mod.update.date)})")
            u.setObjectName("Muted")
            u.setWordWrap(True)
            self.lay.addWidget(u)

        self._load_order(mod)

        if len(mod.vpks) > 1 or (mod.source == "gamebanana" and mod.gb_id):
            h = QLabel("Variants")
            h.setObjectName("SideTitle")
            self.lay.addWidget(h)
        if len(mod.vpks) > 1:
            vhint = QLabel("Everything this file shipped is kept. Tick the parts you want in the game; "
                           "switching needs no download.")
            vhint.setObjectName("Muted")
            vhint.setWordWrap(True)
            self.lay.addWidget(vhint)
            self._variant_boxes = []
            for v in mod.vpks:
                label = v.label.rsplit("/", 1)[0] if "/" in v.label else v.label
                cb = QCheckBox(label)
                cb.setToolTip(v.label)
                cb.setChecked(v.active)
                cb.toggled.connect(lambda _on, u=mod.uid: self._variants_changed(u))
                self.lay.addWidget(cb)
                self._variant_boxes.append((v.label, cb))
        if mod.source == "gamebanana" and mod.gb_id:
            fetch = QPushButton("Other files on GameBanana…" if len(mod.vpks) > 1 else "Other variants…")
            fetch.setToolTip("Lists every file this mod has on GameBanana (colour and style options are "
                             "usually separate files) so you can switch to another one")
            fetch.clicked.connect(lambda: self.page.refetch_requested.emit(mod.uid))
            self.lay.addWidget(fetch, 0, Qt.AlignLeft)

        hero = self.page.mgr.hero_of(mod)
        if hero:
            others = [m for m in self.page.mgr.skins_for(hero) if m.uid != mod.uid]
            if others:
                h = QLabel("Other skins for this hero")
                h.setObjectName("SideTitle")
                self.lay.addWidget(h)
                for o in others[:8]:
                    r = QHBoxLayout()
                    lbl = QLabel(("● " if o.enabled else "○ ") + o.name)
                    if o.enabled:
                        lbl.setStyleSheet("background: transparent;")
                    else:
                        lbl.setObjectName("Muted")
                    lbl.setToolTip("On" if o.enabled else "Off")
                    lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
                    r.addWidget(lbl, 1)
                    use = QPushButton("Use this one")
                    use.setToolTip(f"Turn {o.name} on and the other skins for this hero off")
                    use.clicked.connect(lambda _c=False, u=o.uid: self.page.use_skin(u))
                    r.addWidget(use)
                    self.lay.addLayout(r)

        cam = self.page.mgr.camera_report.get(mod.uid) if mod.enabled else None
        if cam:
            h = QLabel("Camera")
            h.setObjectName("SideTitle")
            self.lay.addWidget(h)
            lines = []
            for r in cam:
                model = r.path.rsplit("/", 1)[-1]
                if r.status == "fixed":
                    lines.append(f"✓ {model}: made before Deadlock's camera update, so Sapphire moved its "
                                 f"{len(r.attachments)} camera and aim points to the current layout. "
                                 "Your mod file isn't changed; the fix sits in its own file in front of it.")
                else:
                    lines.append(f"! {model}: looks like it's from before the camera update but couldn't "
                                 f"be fixed automatically ({r.detail}). If first person looks off, check "
                                 "GameBanana for an update.")
            msg = QLabel("\n\n".join(lines))
            msg.setObjectName("Muted")
            msg.setWordWrap(True)
            msg.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            self.lay.addWidget(msg)

        h = QLabel("Conflicts")
        h.setObjectName("SideTitle")
        self.lay.addWidget(h)
        c = self.page.conflicts.get(mod.uid)
        if not mod.enabled:
            msg = QLabel("Turned off, so it doesn't clash with anything.")
            msg.setObjectName("Muted")
            self.lay.addWidget(msg)
        elif not c or not c.clashes:
            msg = QLabel("None. Nothing else you have changes the same files.")
            msg.setObjectName("Muted")
            msg.setWordWrap(True)
            self.lay.addWidget(msg)
        else:
            tree = QTreeWidget()
            tree.setHeaderHidden(True)
            tree.setStyleSheet(f"background: {theme.PANEL};")
            for clash in sorted(c.clashes, key=lambda x: (x.wins, -len(x.files))):
                other = self.page.mgr.lib.mods.get(clash.other_uid)
                oname = other.name if other else clash.other_uid
                verb = "Beats" if clash.wins else "Loses to"
                top = QTreeWidgetItem([f"{verb} {oname} on {len(clash.files)} file{'s' if len(clash.files) != 1 else ''}"])
                top.setForeground(0, QColor(theme.VERDIGRIS if clash.wins else theme.DANGER_TEXT))
                for f in clash.files[:200]:
                    top.addChild(QTreeWidgetItem([f]))
                tree.addTopLevelItem(top)
            tree.setMinimumHeight(min(320, 40 + 26 * len(c.clashes)))
            self.lay.addWidget(tree)
            hint = QLabel("Want the other one to win? Drag it above this mod.")
            hint.setObjectName("Muted")
            hint.setWordWrap(True)
            self.lay.addWidget(hint)

        self.lay.addStretch(1)
        bottom = QHBoxLayout()
        folder = QPushButton("Show files")
        folder.clicked.connect(lambda: steam.open_path(mod.folder))
        rename = QPushButton("Rename")
        rename.clicked.connect(lambda: self.page.rename(mod.uid))
        remove = QPushButton("Uninstall")
        remove.setProperty("kind", "danger")
        remove.clicked.connect(lambda: self.page.remove(mod.uid))
        bottom.addWidget(folder)
        bottom.addWidget(rename)
        bottom.addStretch(1)
        bottom.addWidget(remove)
        self.lay.addLayout(bottom)


class InstalledPage(QWidget):
    changed = Signal()                 # order/enabled changed -> apply
    update_requested = Signal(str)     # uid
    update_all_requested = Signal()
    check_updates_requested = Signal()
    add_file_requested = Signal()
    identify_requested = Signal(object)   # list of uids, or None for all unknown
    reapply_requested = Signal()
    refetch_requested = Signal(str)   # uid
    rollback_requested = Signal(str)  # uid
    removed = Signal(str)
    status = Signal(str)
    priority_requested = Signal()

    def __init__(self, manager, images):
        super().__init__()
        self.mgr = manager
        self.busy = lambda uid: False   # MainWindow replaces this: is a download running for the mod?
        self.player = None              # shared sound-preview player, set by MainWindow
        self._audio_checked: set[str] = set()
        self.images = images
        self.conflicts: dict[str, ModConflicts] = {}
        self.rank: dict[str, int] = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(16, 14, 10, 8)
        cl.setSpacing(8)

        top = QHBoxLayout()
        self.title = QLabel("Installed")
        self.title.setObjectName("PageTitle")
        top.addWidget(self.title)
        self.count = QLabel()
        self.count.setObjectName("Muted")
        top.addWidget(self.count)
        top.addStretch(1)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter installed mods")
        self.filter.setClearButtonEnabled(True)
        self.filter.setFixedWidth(220)
        self.filter.textChanged.connect(self._apply_filter)
        top.addWidget(self.filter)
        top.addSpacing(8)
        self.view_group = QButtonGroup(self)
        for i, (label, mode) in enumerate((("Grid", "grid"), ("List", "list"))):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setProperty("kind", "toggle")
            b.setProperty("mode", mode)
            radius = "border-top-left-radius:5px;border-bottom-left-radius:5px;" if i == 0 else \
                "border-top-right-radius:5px;border-bottom-right-radius:5px;"
            b.setStyleSheet(f"QPushButton {{ {radius} padding: 4px 12px; }}")
            self.view_group.addButton(b, i)
            top.addWidget(b)
            if mode == manager.lib.settings.installed_view:
                b.setChecked(True)
        if not self.view_group.checkedButton():
            self.view_group.button(0).setChecked(True)
        self.view_group.idToggled.connect(lambda i, on: on and self._view_changed(self.view_group.button(i).property("mode")))
        cl.addLayout(top)

        actions = QHBoxLayout()
        self.check_btn = QPushButton("Check for updates")
        self.check_btn.clicked.connect(self.check_updates_requested)
        self.update_all_btn = QPushButton("Update all")
        self.update_all_btn.setProperty("kind", "primary")
        self.update_all_btn.clicked.connect(self.update_all_requested)
        self.add_btn = QPushButton("Add a file…")
        self.add_btn.setToolTip("Install a .zip, .7z, .rar or .vpk from your computer")
        self.add_btn.clicked.connect(self.add_file_requested)
        self.identify_btn = QPushButton("Identify unknown")
        self.identify_btn.setToolTip("Match mods that were added by hand to their GameBanana page")
        self.identify_btn.clicked.connect(lambda: self.identify_requested.emit(None))
        self.reapply_btn = QPushButton("Reapply")
        self.reapply_btn.setToolTip("Turn every mod off and back on: rewrites all files in the game's addons folder "
                                    "and re-checks gameinfo.gi. Use it if something looks wrong in game.")
        self.reapply_btn.clicked.connect(self.reapply_requested)
        self.priority_btn = QPushButton("Priority…")
        self.priority_btn.setToolTip("A compact list of every mod in load order: drag, type a position, "
                                     "or lock mods in place")
        self.priority_btn.clicked.connect(self.priority_requested)
        actions.addWidget(self.priority_btn)
        all_on = QPushButton("All on")
        all_on.clicked.connect(lambda: self.set_all(True))
        all_off = QPushButton("All off")
        all_off.clicked.connect(lambda: self.set_all(False))
        for b in (self.check_btn, self.update_all_btn, self.add_btn, self.identify_btn):
            actions.addWidget(b)
        actions.addStretch(1)
        actions.addWidget(self.reapply_btn)
        actions.addWidget(all_on)
        actions.addWidget(all_off)
        cl.addLayout(actions)

        self.hint = QLabel()
        self.hint.setObjectName("Muted")
        cl.addWidget(self.hint)

        self.list = ModList()
        self.delegate = RowDelegate(self)
        self.list.setItemDelegate(self.delegate)
        self.list.set_mode(manager.lib.settings.installed_view if manager.lib.settings.installed_view in ("grid", "list") else "grid")
        self._set_hint()
        self.list.moved.connect(self._moved)
        self.list.refused.connect(self._drag_refused)
        self.list.can_drag = lambda uid: not (self.mgr.lib.mods.get(uid) and self.mgr.lib.mods[uid].locked)
        self.list.itemChanged.connect(self._item_changed)
        self.list.currentItemChanged.connect(self._current_changed)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        cl.addWidget(self.list, 1)

        self.empty = QLabel("No mods yet. Find some in Browse, or add a file you already downloaded.")
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        cl.addWidget(self.empty, 1)
        root.addWidget(center, 1)

        self.detail = DetailPanel(self)
        root.addWidget(self.detail)
        images.loaded.connect(lambda _u: self.list.viewport().update())
        self._building = False

    def _set_hint(self):
        if self.delegate.mode == "grid":
            self.hint.setText("Drag cards to reorder: #1 wins when two mods change the same file. "
                              "Click the box on a card to turn it off or on. Right-click to lock a mod in place.")
        else:
            self.hint.setText("Drag to reorder: higher in the list wins when two mods change the same file. "
                              "Right-click to lock a mod in place.")

    def _view_changed(self, mode: str):
        self.mgr.lib.settings.installed_view = mode
        self.mgr.lib.save()
        self.list.set_mode(mode)
        self._set_hint()
        self.reload()

    def rescale(self):
        self.detail.setFixedWidth(theme.px(360))
        self.list.setAutoScrollMargin(theme.px(70))
        self.list.relayout()
        self.list.reset()
        self.reload()

    # ---------------------------------------------------------------- data
    def reload(self):
        self._building = True
        current = self.detail.uid
        self.list.clear()
        for mod in self.mgr.lib.ordered():
            item = QListWidgetItem()
            item.setData(ROLE_UID, mod.uid)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if mod.enabled else Qt.Unchecked)
            item.setToolTip(mod.name)
            self.list.addItem(item)
            if mod.uid == current:
                self.list.setCurrentItem(item)
        self._building = False
        self._recount()
        self._apply_filter(self.filter.text())
        self.detail.show_mod(current if current in self.mgr.lib.mods else None)

    def _recount(self):
        mods = self.mgr.lib.ordered()
        on = [m for m in mods if m.enabled]
        self.rank = {m.uid: i + 1 for i, m in enumerate(mods)}
        self.count.setText(f"{len(on)} on, {len(mods) - len(on)} off" if mods else "")
        self._update_button()
        self.identify_btn.setVisible(any(m.source == "local" for m in mods))
        self.empty.setVisible(not mods)
        self.list.setVisible(bool(mods))
        self.list.viewport().update()

    def camera_status(self, uid: str) -> str | None:
        """'fixed' if the camera fix repaired this mod's model(s), 'warning' if it couldn't."""
        rep = self.mgr.camera_report.get(uid)
        if not rep:
            return None
        return "fixed" if any(r.status == "fixed" for r in rep) else "warning"

    def _update_button(self):
        pending = [m for m in self.mgr.lib.ordered() if m.update]
        busy = [m for m in pending if self.busy(m.uid)]
        waiting = len(pending) - len(busy)
        if waiting:
            self.update_all_btn.setText(f"Update all ({waiting})")
            self.update_all_btn.setEnabled(True)
        elif busy:
            self.update_all_btn.setText(f"Updating {len(busy)}…")
            self.update_all_btn.setEnabled(False)
        self.update_all_btn.setVisible(bool(pending))

    def jobs_changed(self):
        """Downloads started or finished: refresh the Update all button and the open panel."""
        self._update_button()
        if self.detail.uid and self.busy(self.detail.uid) != getattr(self.detail, "_shown_busy", None):
            self.detail.show_mod(self.detail.uid)

    def set_conflicts(self, conflicts):
        self.conflicts = conflicts
        self.list.viewport().update()
        self.detail.show_mod(self.detail.uid)

    def _apply_filter(self, text):
        text = text.strip().lower()
        for i in range(self.list.count()):
            item = self.list.item(i)
            mod = self.mgr.lib.mods.get(item.data(ROLE_UID))
            hay = f"{mod.name} {mod.author} {mod.category}".lower() if mod else ""
            item.setHidden(bool(text) and text not in hay)
        # reordering a filtered list would be confusing
        self.list.reorderable = not text

    def _uids(self) -> list[str]:
        return [self.list.item(i).data(ROLE_UID) for i in range(self.list.count())]

    # ------------------------------------------------------------ actions
    def _moved(self, uid: str, index: int):
        self.mgr.move_to(uid, index)
        self.reload()
        self.changed.emit()

    def _drag_refused(self, uid: str):
        mod = self.mgr.lib.mods.get(uid)
        if mod and mod.locked:
            self.status.emit(f"{mod.name} is locked at #{self.rank.get(uid)}. Unlock it to move it.")

    def set_locked(self, uid: str, on: bool):
        mod = self.mgr.lib.mods.get(uid)
        if not mod:
            return
        self.mgr.set_locked(uid, on)
        self.reload()
        pos = self.rank.get(uid)
        self.status.emit(f"{mod.name} is locked at #{pos}: it stays there when you move, add or remove "
                         "other mods." if on else f"{mod.name} is unlocked.")

    def _item_changed(self, item):
        if self._building:
            return
        uid = item.data(ROLE_UID)
        mod = self.mgr.lib.mods.get(uid)
        enabled = item.checkState() == Qt.Checked
        if mod and mod.enabled != enabled:
            off = self.mgr.set_enabled(uid, enabled)
            if off:
                # one skin per hero switched others off: refresh their boxes
                QTimer.singleShot(0, self.reload)
                self.status.emit(f"Turned off {', '.join(m.name for m in off)} (one skin per hero).")
            self._recount()
            if self.detail.uid == uid:
                self.detail.show_mod(uid)
            self.changed.emit()

    def use_skin(self, uid: str):
        """Turn this skin on and the hero's other skins off, whatever the setting says."""
        mod = self.mgr.lib.mods.get(uid)
        hero = self.mgr.hero_of(mod) if mod else None
        if not hero:
            return
        for m in self.mgr.skins_for(hero):
            m.enabled = m.uid == uid
        self.mgr.lib.save()
        self.mgr._dirty = True
        self.reload()
        self.status.emit(f"Using {mod.name} for this hero.")
        self.changed.emit()

    def toggle(self, uid):
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(ROLE_UID) == uid:
                item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
                return

    def set_all(self, on: bool):
        self._building = True
        heroes_on: set[str] = set()
        one = on and self.mgr.lib.settings.one_skin_per_hero
        for i in range(self.list.count()):
            item = self.list.item(i)
            if not item.isHidden():
                mod = self.mgr.lib.mods[item.data(ROLE_UID)]
                want = on
                if one:
                    hero = self.mgr.hero_of(mod)
                    if hero:
                        want = hero not in heroes_on   # first (highest) skin per hero wins
                        heroes_on.add(hero)
                item.setCheckState(Qt.Checked if want else Qt.Unchecked)
                mod.enabled = want
        self._building = False
        self.mgr.lib.save()
        self.mgr._dirty = True
        self._recount()
        self.detail.show_mod(self.detail.uid)
        self.changed.emit()

    def move(self, uid, where: str):
        uids = self._uids()
        if uid not in uids:
            return
        i = uids.index(uid)
        target = {"top": 0, "bottom": len(uids) - 1, "up": i - 1, "down": i + 1}[where]
        self.mgr.move_to(uid, max(0, target))
        self.reload()
        self.changed.emit()

    def _current_changed(self, current, _prev):
        self.detail.show_mod(current.data(ROLE_UID) if current else None)

    def rename(self, uid):
        from sapphire.ui.dialogs import ask_text
        mod = self.mgr.lib.mods.get(uid)
        if not mod:
            return
        name = ask_text(self, "Rename mod", "Name shown in Sapphire:", mod.name)
        if name:
            self.mgr.rename(uid, name)
            self.reload()

    def remove(self, uid):
        from sapphire.ui.dialogs import confirm
        mod = self.mgr.lib.mods.get(uid)
        if not mod:
            return
        if confirm(self, "Uninstall mod", f"Uninstall “{mod.name}”? Its files are deleted from "
                   "Sapphire's library and the game.", "Uninstall", danger=True):
            self.mgr.remove(uid)
            self.reload()
            self.removed.emit(uid)
            self.changed.emit()

    def _menu(self, pos):
        item = self.list.itemAt(pos)
        if not item:
            return
        uid = item.data(ROLE_UID)
        mod = self.mgr.lib.mods.get(uid)
        menu = QMenu(self)
        menu.addAction("Turn off" if mod.enabled else "Turn on", lambda: self.toggle(uid))
        menu.addSeparator()
        if mod.locked:
            menu.addAction(f"Unlock from #{self.rank.get(uid)}", lambda: self.set_locked(uid, False))
        else:
            menu.addAction("Move to top", lambda: self.move(uid, "top"))
            menu.addAction("Move up", lambda: self.move(uid, "up"))
            menu.addAction("Move down", lambda: self.move(uid, "down"))
            menu.addAction("Move to bottom", lambda: self.move(uid, "bottom"))
            menu.addAction(f"Lock at #{self.rank.get(uid)}", lambda: self.set_locked(uid, True))
        menu.addAction("Edit priority list…", lambda: self.priority_requested.emit())
        menu.addSeparator()
        if mod.update:
            menu.addAction("Update", lambda: self.update_requested.emit(uid))
        if mod.url:
            menu.addAction("Open on GameBanana", lambda: QDesktopServices.openUrl(QUrl(mod.url)))
        if self.mgr.can_roll_back(uid):
            menu.addAction("Roll back to the previous version", lambda: self.rollback_requested.emit(uid))
        menu.addAction("Rename…", lambda: self.rename(uid))
        menu.addAction("Uninstall…", lambda: self.remove(uid))
        menu.exec(self.list.viewport().mapToGlobal(pos))
