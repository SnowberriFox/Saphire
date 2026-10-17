"""Installed page: load order, enable/disable, conflicts, updates."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMenu, QPushButton, QScrollArea,
                               QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from sapphire import steam
from sapphire.conflicts import ModConflicts
from sapphire.library import InstalledMod
from sapphire.ui import theme
from sapphire.ui.browse import fmt_date

ROLE_UID = Qt.UserRole + 1


class RowDelegate(QStyledItemDelegate):
    def __init__(self, page):
        super().__init__(page.list)
        self.page = page

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), theme.px(66))

    def paint(self, p: QPainter, option, index):
        uid = index.data(ROLE_UID)
        mod: InstalledMod | None = self.page.mgr.lib.mods.get(uid)
        if mod is None:
            return
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
        # grip
        p.setPen(QColor(theme.LINE))
        f = QFont(p.font())
        f.setPixelSize(theme.px(14))
        p.setFont(f)
        p.drawText(QRectF(r.left() + 4, r.top(), 14, r.height()), Qt.AlignCenter, "⠿")

        # check toggle where the style expects it (so clicks land on it)
        check = style.subElementRect(QStyle.SE_ItemViewItemCheckIndicator, opt, opt.widget)
        cr = QRectF(check).adjusted(-1, -1, 1, 1)
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

        x = cr.right() + 12
        # priority number (only meaningful for enabled mods)
        rank = self.page.rank.get(uid)
        f.setPixelSize(theme.px(13))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.ACCENT if rank and not dim else theme.LINE))
        p.drawText(QRectF(x, r.top(), 30, r.height()), Qt.AlignVCenter | Qt.AlignRight,
                   f"{rank}" if rank else "–")
        x += 40

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


class ModList(QListWidget):
    reordered = Signal()

    def __init__(self):
        super().__init__()
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setSpacing(0)
        # Scroll while dragging near the top or bottom edge (a row's height, not Qt's 16px).
        self.setAutoScroll(True)
        self.setAutoScrollMargin(theme.px(70))

    def dropEvent(self, e):
        super().dropEvent(e)
        self.reordered.emit()


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
        self.setWidget(self.body)
        self.lay = QVBoxLayout(self.body)
        self.lay.setContentsMargins(16, 16, 16, 16)
        self.lay.setSpacing(10)
        self.uid = None
        self.show_mod(None)

    def _clear(self):
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                while it.layout().count():
                    sub = it.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()

    def show_mod(self, uid):
        self.uid = uid
        self._clear()
        mod = self.page.mgr.lib.mods.get(uid) if uid else None
        if mod is None:
            lbl = QLabel("Select a mod to see what it changes and what it clashes with.\n\n"
                         "Drag mods to reorder. When two mods change the same file, the one "
                         "higher in the list wins.")
            lbl.setObjectName("Muted")
            lbl.setWordWrap(True)
            self.lay.addWidget(lbl)
            self.lay.addStretch(1)
            return
        title = QLabel(mod.name)
        title.setObjectName("DetailTitle")
        title.setWordWrap(True)
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
        self.lay.addWidget(meta)

        row = QHBoxLayout()
        toggle = QPushButton("Turn off" if mod.enabled else "Turn on")
        toggle.clicked.connect(lambda: self.page.toggle(mod.uid))
        row.addWidget(toggle)
        if mod.update:
            upd = QPushButton("Update")
            upd.setProperty("kind", "primary")
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
        if mod.update:
            u = QLabel(f"New file: {mod.update.file_name} ({fmt_date(mod.update.date)})")
            u.setObjectName("Muted")
            u.setWordWrap(True)
            self.lay.addWidget(u)

        if len(mod.vpks) > 1 or (mod.vpks and "/" in mod.vpks[0].label):
            h = QLabel("Installed parts")
            h.setObjectName("SideTitle")
            self.lay.addWidget(h)
            parts = QLabel("\n".join(v.label for v in mod.vpks))
            parts.setObjectName("Muted")
            parts.setWordWrap(True)
            self.lay.addWidget(parts)

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
    removed = Signal(str)
    status = Signal(str)

    def __init__(self, manager, images):
        super().__init__()
        self.mgr = manager
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

        hint = QLabel("Drag to reorder. Higher in the list wins when two mods change the same file.")
        hint.setObjectName("Muted")
        cl.addWidget(hint)

        self.list = ModList()
        self.delegate = RowDelegate(self)
        self.list.setItemDelegate(self.delegate)
        self.list.reordered.connect(self._reordered)
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

    def rescale(self):
        self.detail.setFixedWidth(theme.px(360))
        self.list.setAutoScrollMargin(theme.px(70))
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
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled | Qt.ItemIsUserCheckable)
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
        self.rank = {m.uid: i + 1 for i, m in enumerate(on)}
        n_upd = sum(1 for m in mods if m.update)
        self.count.setText(f"{len(on)} on, {len(mods) - len(on)} off" if mods else "")
        self.update_all_btn.setText(f"Update all ({n_upd})" if n_upd else "Update all")
        self.update_all_btn.setVisible(n_upd > 0)
        self.identify_btn.setVisible(any(m.source == "local" for m in mods))
        self.empty.setVisible(not mods)
        self.list.setVisible(bool(mods))
        self.list.viewport().update()

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
        self.list.setDragDropMode(QAbstractItemView.NoDragDrop if text else QAbstractItemView.InternalMove)

    def _uids(self) -> list[str]:
        return [self.list.item(i).data(ROLE_UID) for i in range(self.list.count())]

    # ------------------------------------------------------------ actions
    def _reordered(self):
        self.mgr.set_order(self._uids())
        self._recount()
        self.changed.emit()

    def _item_changed(self, item):
        if self._building:
            return
        uid = item.data(ROLE_UID)
        mod = self.mgr.lib.mods.get(uid)
        enabled = item.checkState() == Qt.Checked
        if mod and mod.enabled != enabled:
            self.mgr.set_enabled(uid, enabled)
            self._recount()
            if self.detail.uid == uid:
                self.detail.show_mod(uid)
            self.changed.emit()

    def toggle(self, uid):
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(ROLE_UID) == uid:
                item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
                return

    def set_all(self, on: bool):
        self._building = True
        for i in range(self.list.count()):
            item = self.list.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.Checked if on else Qt.Unchecked)
                self.mgr.lib.mods[item.data(ROLE_UID)].enabled = on
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
        uids.pop(i)
        target = {"top": 0, "bottom": len(uids), "up": max(0, i - 1), "down": min(len(uids), i + 1)}[where]
        uids.insert(target, uid)
        self.mgr.set_order(uids)
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
        menu.addAction("Move to top", lambda: self.move(uid, "top"))
        menu.addAction("Move up", lambda: self.move(uid, "up"))
        menu.addAction("Move down", lambda: self.move(uid, "down"))
        menu.addAction("Move to bottom", lambda: self.move(uid, "bottom"))
        menu.addSeparator()
        if mod.update:
            menu.addAction("Update", lambda: self.update_requested.emit(uid))
        if mod.url:
            menu.addAction("Open on GameBanana", lambda: QDesktopServices.openUrl(QUrl(mod.url)))
        menu.addAction("Rename…", lambda: self.rename(uid))
        menu.addAction("Uninstall…", lambda: self.remove(uid))
        menu.exec(self.list.viewport().mapToGlobal(pos))
