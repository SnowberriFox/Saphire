"""Browse page: live GameBanana catalogue with proper filtering."""

from __future__ import annotations

import datetime as dt
import re

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPainterPath, QPen
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QListView, QPushButton, QScrollArea,
                               QSizePolicy, QStyle, QStyledItemDelegate, QTextBrowser, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from sapphire.gamebanana import SORTS, Category, Details, GBFile, Submission, newest_file, parse_url
from sapphire.ui import theme
from sapphire.ui.dialogs import human_size
from sapphire.ui.workers import run

ROLE_SUB = Qt.UserRole + 1


def fmt_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return str(n)


def fmt_date(ts: int) -> str:
    if not ts:
        return "unknown date"
    d = dt.datetime.fromtimestamp(ts)
    days = (dt.datetime.now() - d).days
    if days < 1:
        return "today"
    if days < 2:
        return "yesterday"
    if days < 30:
        return f"{days} days ago"
    return d.strftime("%-d %b %Y")


class ElidedLabel(QLabel):
    """A label that never widens its parent: long text is elided in the middle."""

    def __init__(self, text: str = "", bold: bool = False):
        super().__init__()
        self._full = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        if bold:
            self.setStyleSheet("background: transparent; font-weight: 600;")
        else:
            self.setStyleSheet("background: transparent;")
        self.setToolTip(text)
        self.setMinimumWidth(40)

    def setText(self, text: str):  # noqa: N802 - Qt naming
        self._full = text
        self.setToolTip(text)
        self._apply()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply()

    def _apply(self):
        fm = self.fontMetrics()
        super().setText(fm.elidedText(self._full, Qt.ElideMiddle, max(20, self.width() - 4)))


# ---------------------------------------------------------------- grid model

class SubmissionModel(QAbstractListModel):
    def __init__(self):
        super().__init__()
        self.items: list[Submission] = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        sub = self.items[index.row()]
        if role == ROLE_SUB:
            return sub
        if role == Qt.DisplayRole:
            return sub.name
        if role == Qt.ToolTipRole:
            return f"{sub.name}\nby {sub.author or 'unknown'}\n{sub.category_label}"
        return None

    def clear(self):
        self.beginResetModel()
        self.items = []
        self.endResetModel()

    def extend(self, subs: list[Submission]):
        known = {s.key for s in self.items}
        subs = [s for s in subs if s.key not in known]
        if not subs:
            return
        self.beginInsertRows(QModelIndex(), len(self.items), len(self.items) + len(subs) - 1)
        self.items.extend(subs)
        self.endInsertRows()

    def refresh_all(self):
        if self.items:
            self.dataChanged.emit(self.index(0), self.index(len(self.items) - 1))


class CardDelegate(QStyledItemDelegate):
    """Paints a mod card: cover image, name, author, likes, installed badge."""

    def __init__(self, view, images, installed_fn):
        super().__init__(view)
        self.view = view
        self.images = images
        self.installed_fn = installed_fn  # sub -> "installed" | "update" | None
        self.fav_fn = lambda sub: False   # BrowsePage replaces: is this a favourite?
        self.card_size = QSize(theme.px(232), theme.px(210))
        self.mode = "grid"   # or "list"

    def sizeHint(self, option, index):
        return self.card_size

    def paint(self, p: QPainter, option, index):
        sub: Submission = index.data(ROLE_SUB)
        if sub is None:
            return
        if self.mode == "list":
            return self._paint_row(p, option, sub)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect).adjusted(6, 6, -6, -6)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        path = QPainterPath()
        path.addRoundedRect(r, theme.rad(8), theme.rad(8))
        p.fillPath(path, QColor(theme.PANEL))
        if selected or hovered:
            p.setPen(QPen(QColor(theme.ACCENT if selected else theme.ACCENT_LO), 1.5))
            p.drawPath(path)

        img_h = r.width() * 9 / 16
        img_rect = QRectF(r.left(), r.top(), r.width(), img_h)
        p.save()
        clip = QPainterPath()
        clip.setFillRule(Qt.WindingFill)
        clip.addRoundedRect(img_rect, theme.rad(8), theme.rad(8))
        clip.addRect(QRectF(img_rect.left(), img_rect.top() + 10, img_rect.width(), img_h - 10))
        p.setClipPath(clip.simplified())
        pix = self.images.get(sub.thumb_url)
        if pix is not None and not pix.isNull():
            scaled = pix.scaled(int(img_rect.width()), int(img_rect.height()),
                                Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            sx = (scaled.width() - img_rect.width()) / 2
            sy = (scaled.height() - img_rect.height()) / 2
            p.drawPixmap(img_rect.toRect(), scaled,
                         QRect(int(sx), int(sy), int(img_rect.width()), int(img_rect.height())))
        else:
            p.fillRect(img_rect, QColor(theme.RAISED))
            p.setPen(QColor(theme.LINE))
            f = theme.display_font(34)
            p.setFont(f)
            p.drawText(img_rect, Qt.AlignCenter, (sub.name[:1] or "?").upper())
        p.restore()

        self._badges(p, sub, img_rect.left() + theme.px(8), img_rect.top() + theme.px(8), img_rect.right() - theme.px(8))

        # text (the soul sits before a selected card's name in the pixel themes)
        soul = theme.soul_space(selected)
        text_rect = QRectF(r.left() + theme.px(10) + soul, img_rect.bottom() + theme.px(8),
                           r.width() - theme.px(20) - soul, theme.px(38))
        if soul:
            theme.soul_at(p, r.left() + theme.px(9), text_rect.top() + theme.px(9))
        f = QFont(p.font())
        f.setPixelSize(theme.fpx(13))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.TEXT))
        fm = p.fontMetrics()
        words, lines, cur = sub.name.split(), [], ""
        for w in words:
            trial = f"{cur} {w}".strip()
            if fm.horizontalAdvance(trial) <= text_rect.width() or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
            if len(lines) == 2:
                break
        if cur and len(lines) < 2:
            lines.append(cur)
        if len(lines) == 2 and " ".join(lines) != sub.name:
            lines[1] = fm.elidedText(lines[1] + " …", Qt.ElideRight, int(text_rect.width()))
        lines = [fm.elidedText(l, Qt.ElideRight, int(text_rect.width())) for l in lines[:2]]
        lh = theme.px(18)
        for i, line in enumerate(lines):
            p.drawText(QRectF(text_rect.left(), text_rect.top() + i * lh, text_rect.width(), lh),
                       Qt.AlignLeft | Qt.AlignVCenter, line)

        f.setBold(False)
        f.setPixelSize(theme.fpx(12))
        p.setFont(f)
        p.setPen(QColor(theme.MUTED))
        meta_rect = QRectF(r.left() + theme.px(10), r.bottom() - theme.px(24), r.width() - theme.px(20), theme.px(18))
        likes = f"♥ {fmt_count(sub.likes)}"
        lw = p.fontMetrics().horizontalAdvance(likes)
        p.drawText(meta_rect.adjusted(0, 0, -(lw + 10), 0), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(sub.author or "unknown", Qt.ElideRight,
                                              int(meta_rect.width() - lw - 10)))
        p.drawText(meta_rect, Qt.AlignRight | Qt.AlignVCenter, likes)
        theme.pixel_frame(p, r, selected, hovered)
        p.restore()

    def _badges(self, p: QPainter, sub: Submission, bx: float, by: float, limit: float | None = None) -> float:
        """Draw the status badges starting at (bx, by), skipping any that would
        run past `limit`; returns the x after the last one."""
        state = self.installed_fn(sub)
        for text, bg, fg in (
            ("Update ready", theme.ACCENT, theme.ON_ACCENT) if state == "update" else
            ("Installed", theme.OK_BG, theme.VERDIGRIS) if state == "installed" else (None, None, None),
            ("18+", theme.OXBLOOD, "#FFF2EE") if sub.nsfw else (None, None, None),
            ("Outdated", theme.RAISED, theme.MUTED) if sub.obsolete else (None, None, None),
            ("★", theme.ACCENT_LO, theme.ACCENT_HI) if self.fav_fn(sub) else (None, None, None),
            ("♪ preview", theme.RAISED, theme.TEXT) if sub.audio_url else (None, None, None),
        ):
            if not text:
                continue
            f = QFont(p.font())
            f.setPixelSize(theme.fpx(11))
            f.setBold(True)
            p.setFont(f)
            w = p.fontMetrics().horizontalAdvance(text) + theme.px(14)
            if limit is not None and bx + w > limit:
                continue
            badge = QRectF(bx, by, w, theme.px(20))
            bp = QPainterPath()
            bp.addRoundedRect(badge, theme.rad(theme.px(10)), theme.rad(theme.px(10)))
            p.fillPath(bp, QColor(bg))
            p.setPen(QColor(fg))
            p.drawText(badge, Qt.AlignCenter, text)
            bx += w + theme.px(6)
        return bx

    def _paint_row(self, p: QPainter, option, sub: Submission):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect).adjusted(4, 3, -4, -3)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        path = QPainterPath()
        path.addRoundedRect(r, theme.rad(7), theme.rad(7))
        p.fillPath(path, QColor(theme.RAISED if selected else theme.PANEL))
        if selected or hovered:
            p.setPen(QPen(QColor(theme.ACCENT_LO if selected else theme.LINE), 1.2))
            p.drawPath(path)
        thumb = QRectF(r.left() + theme.px(8), r.top() + theme.px(6), theme.px(96), r.height() - theme.px(12))
        tp = QPainterPath()
        tp.addRoundedRect(thumb, theme.rad(5), theme.rad(5))
        pix = self.images.get(sub.thumb_url)
        p.save()
        p.setClipPath(tp)
        if pix is not None and not pix.isNull():
            scaled = pix.scaled(int(thumb.width()), int(thumb.height()), Qt.KeepAspectRatioByExpanding,
                                Qt.SmoothTransformation)
            sx = (scaled.width() - thumb.width()) / 2
            sy = (scaled.height() - thumb.height()) / 2
            p.drawPixmap(thumb.toRect(), scaled, QRect(int(sx), int(sy), int(thumb.width()), int(thumb.height())))
        else:
            p.fillPath(tp, QColor(theme.BG))
            p.setPen(QColor(theme.LINE))
            p.setFont(theme.display_font(20))
            p.drawText(thumb, Qt.AlignCenter, (sub.name[:1] or "?").upper())
        p.restore()
        x = thumb.right() + theme.px(12)
        f = QFont(p.font())
        f.setPixelSize(theme.fpx(12))
        p.setFont(f)
        p.setPen(QColor(theme.MUTED))
        right = f"♥ {fmt_count(sub.likes)}    {fmt_count(sub.views)} views    {fmt_date(sub.date_modified)}"
        rw = p.fontMetrics().horizontalAdvance(right)
        p.drawText(QRectF(r.right() - rw - theme.px(12), r.top(), rw, r.height()), Qt.AlignVCenter | Qt.AlignRight, right)
        soul = theme.soul_space(selected)
        if soul:
            theme.soul_at(p, x, r.top() + theme.px(18))
            x += soul
        text_w = r.right() - rw - theme.px(24) - x
        f.setPixelSize(theme.fpx(14))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(x, r.top() + theme.px(8), text_w, theme.px(20)), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(sub.name, Qt.ElideRight, int(text_w)))
        f.setBold(False)
        f.setPixelSize(theme.fpx(12))
        p.setFont(f)
        p.setPen(QColor(theme.MUTED))
        meta = f"by {sub.author or 'unknown'}    {sub.category_label}" if sub.category_label else f"by {sub.author or 'unknown'}"
        meta = p.fontMetrics().elidedText(meta, Qt.ElideRight, int(text_w * 0.6))
        mw = p.fontMetrics().horizontalAdvance(meta)
        p.drawText(QRectF(x, r.top() + theme.px(30), text_w, theme.px(18)), Qt.AlignLeft | Qt.AlignVCenter, meta)
        self._badges(p, sub, x + mw + theme.px(14), r.top() + theme.px(29))
        theme.pixel_frame(p, r, selected, hovered)
        p.restore()


class CardGrid(QListView):
    near_bottom = Signal()

    def __init__(self):
        super().__init__()
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(24)
        self.setSpacing(0)
        self.setContentsMargins(8, 8, 8, 8)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)

    def _scrolled(self, value):
        bar = self.verticalScrollBar()
        if bar.maximum() - value < 600:
            self.near_bottom.emit()

    def set_mode(self, mode: str):
        delegate = self.itemDelegate()
        if isinstance(delegate, CardDelegate):
            delegate.mode = mode
        if mode == "list":
            self.setViewMode(QListView.ListMode)
            self.setFlow(QListView.TopToBottom)
            self.setWrapping(False)
        else:
            self.setViewMode(QListView.IconMode)
            self.setFlow(QListView.LeftToRight)
            self.setWrapping(True)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.relayout()
        self.viewport().update()

    def relayout(self):
        delegate = self.itemDelegate()
        if not isinstance(delegate, CardDelegate):
            return
        avail = self.viewport().width() - 4
        if delegate.mode == "list":
            delegate.card_size = QSize(avail, theme.px(72))
        else:
            cols = max(1, avail // theme.px(228))
            w = avail // cols
            delegate.card_size = QSize(w, int((w - 12) * 9 / 16) + theme.px(96))
        self.setGridSize(delegate.card_size)
        self.scheduleDelayedItemsLayout()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.relayout()


# ---------------------------------------------------------------- detail pane

class FileRow(QFrame):
    install = Signal(object, bool)   # file, add alongside (True) or replace the main entry (False)

    def __init__(self, f: GBFile, state: str, primary: bool, installed_name: str = ""):
        super().__init__()
        self.setObjectName("Panel")
        self.setStyleSheet(f"#Panel {{ background: {theme.RAISED}; border-radius: {theme.rad(6):g}px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(4)
        top = QHBoxLayout()
        name = ElidedLabel(f.filename, bold=True)
        top.addWidget(name, 1)
        if state in ("update", "older"):
            # The mod is installed with a different file: this one can replace it or sit beside it.
            add = QPushButton("Add")
            add.setToolTip(f"Install this file as well, alongside “{installed_name}”. For optional "
                           "add-on files (extra announcers, icons…) that go with the main download.")
            add.clicked.connect(lambda: self.install.emit(f, True))
            top.addWidget(add)
        btn = QPushButton({"current": "Reinstall", "update": "Update to this",
                           "older": "Replace"}.get(state, "Install"))
        if state == "older":
            btn.setToolTip(f"Install this file instead of “{installed_name}”.")
        if primary and state != "current":
            btn.setProperty("kind", "primary")
        btn.clicked.connect(lambda: self.install.emit(f, False))
        top.addWidget(btn)
        lay.addLayout(top)
        meta = f"{human_size(f.size)}   {fmt_date(f.date_added)}   {fmt_count(f.downloads)} downloads"
        if f.archived:
            meta += "   archived"
        m = QLabel(meta)
        m.setObjectName("Muted")
        lay.addWidget(m)
        if f.description:
            d = QLabel(f.description)
            d.setWordWrap(True)
            d.setObjectName("Muted")
            lay.addWidget(d)


class DetailPane(QScrollArea):
    install_requested = Signal(str, int, object, bool)  # model, id, GBFile, add alongside
    author_clicked = Signal(int, str)

    def __init__(self, client, images, installed_lookup):
        super().__init__()
        self.client = client
        self.images = images
        self.installed_lookup = installed_lookup  # (model, id) -> [InstalledMod], main entry first
        self.setObjectName("DetailPanel")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setFixedWidth(theme.px(384))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body.setObjectName("DetailPanel")
        self.body.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setWidget(self.body)
        self.lay = QVBoxLayout(self.body)
        self.lay.setContentsMargins(16, 16, 16, 16)
        self.lay.setSpacing(10)
        self.sub: Submission | None = None
        self.details: Details | None = None
        self.image_index = 0
        self._token = 0
        self.player = None                      # shared PreviewPlayer, set by the window
        self.is_fav = lambda sub: False          # set by BrowsePage
        self.toggle_fav = lambda sub: False
        images.loaded.connect(self._image_loaded)
        self.show_empty()

    def _clear(self):
        while self.lay.count():
            item = self.lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                self._drop_layout(item.layout())

    def _drop_layout(self, layout):
        while layout.count():
            it = layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                self._drop_layout(it.layout())

    def show_empty(self):
        self._clear()
        lbl = QLabel("Pick a mod to see its files and details.")
        lbl.setObjectName("Muted")
        lbl.setWordWrap(True)
        self.lay.addWidget(lbl)
        self.lay.addStretch(1)

    def show_sub(self, sub: Submission):
        self.sub = sub
        self.details = None
        self.image_index = 0
        self._token += 1
        token = self._token
        self._render()
        run(self.client.details, sub.model, sub.id,
            on_done=lambda d, t=token: self._got(d, t),
            on_error=lambda e, t=token: self._failed(e, t))

    def refresh(self):
        if self.sub:
            self._render()

    def _got(self, details: Details, token: int):
        if token != self._token:
            return
        self.details = details
        self._render()

    def _failed(self, exc, token):
        if token != self._token:
            return
        self._render(error=str(exc))

    def _image_loaded(self, url):
        if self.sub and self._current_image_url() == url:
            self._render()

    def _current_image_url(self) -> str:
        sub = self.details.submission if self.details else self.sub
        urls = sub.image_urls or ([sub.thumb_url] if sub.thumb_url else [])
        if not urls:
            return ""
        return urls[self.image_index % len(urls)]

    def _render(self, error: str = ""):
        self._clear()
        sub = self.details.submission if self.details else self.sub
        if sub is None:
            return self.show_empty()
        # image
        img = QLabel()
        img.setAlignment(Qt.AlignCenter)
        img.setMinimumHeight(170)
        img.setStyleSheet(f"background: {theme.RAISED}; border-radius: {theme.rad(6):g}px;")
        url = self._current_image_url()
        pix = self.images.get(url) if url else None
        if pix is not None:
            w = self.width() - 32 - 14
            scaled = pix.scaledToWidth(w, Qt.SmoothTransformation)
            if scaled.height() > 260:
                scaled = pix.scaledToHeight(260, Qt.SmoothTransformation)
            img.setPixmap(scaled)
        else:
            img.setText("Loading preview…" if url else "No preview")
            img.setObjectName("Muted")
        self.lay.addWidget(img)
        n_imgs = len(sub.image_urls)
        if n_imgs > 1:
            nav = QHBoxLayout()
            prev_b, next_b = QPushButton("Previous"), QPushButton("Next")
            count = QLabel(f"{self.image_index % n_imgs + 1} of {n_imgs}")
            count.setObjectName("Muted")
            count.setAlignment(Qt.AlignCenter)
            prev_b.clicked.connect(lambda: self._step(-1))
            next_b.clicked.connect(lambda: self._step(1))
            nav.addWidget(prev_b)
            nav.addWidget(count, 1)
            nav.addWidget(next_b)
            self.lay.addLayout(nav)

        title = QLabel(sub.name)
        title.setObjectName("DetailTitle")
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lay.addWidget(title)
        author = QPushButton(f"by {sub.author or 'unknown'}")
        author.setToolTip("Show everything by this author")
        author.setCursor(Qt.PointingHandCursor)
        author.setStyleSheet(f"QPushButton {{ background: transparent; border: none; color: {theme.ACCENT_HI};"
                             f" text-align: left; padding: 0; }} QPushButton:hover {{ text-decoration: underline; }}")
        if sub.author_id:
            author.clicked.connect(lambda: self.author_clicked.emit(sub.author_id, sub.author))
        self.lay.addWidget(author)
        meta = QLabel(f"{sub.category_label or sub.model}\n♥ {fmt_count(sub.likes)}    "
                      f"{fmt_count(sub.views)} views    updated {fmt_date(sub.date_modified)}")
        meta.setObjectName("Muted")
        meta.setWordWrap(True)
        self.lay.addWidget(meta)
        actions = QHBoxLayout()
        open_btn = QPushButton("Open on GameBanana")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(sub.url or f"https://gamebanana.com/mods/{sub.id}")))
        fav = self.is_fav(sub)
        star = QPushButton("★  Favourite" if fav else "☆  Favourite")
        star.setToolTip("Remove from favourites" if fav else "Save it to Favourites to find again later")
        if fav:
            star.setProperty("kind", "primary")
        star.clicked.connect(lambda: (self.toggle_fav(sub), self._render()))
        actions.addWidget(star)
        actions.addWidget(open_btn, 1)
        self.lay.addLayout(actions)
        if sub.audio_url and self.player is not None:
            from sapphire.ui.audio import PreviewButton
            prev = PreviewButton(self.player, sub.audio_url)
            prev.setProperty("kind", "primary")
            self.lay.addWidget(prev)

        # files
        head = QLabel("Files")
        head.setObjectName("SideTitle")
        self.lay.addWidget(head)
        if error:
            e = QLabel(f"Couldn't load details: {error}")
            e.setObjectName("Muted")
            e.setWordWrap(True)
            self.lay.addWidget(e)
            retry = QPushButton("Try again")
            retry.clicked.connect(lambda: self.show_sub(self.sub))
            self.lay.addWidget(retry)
        elif self.details is None:
            w = QLabel("Loading files…")
            w.setObjectName("Muted")
            self.lay.addWidget(w)
        else:
            installed = self.installed_lookup(sub.model, sub.id)   # every entry of this mod
            main = installed[0] if installed else None
            have = {m.file_id for m in installed}
            files = self.details.files
            newest = newest_file(files)
            live = [f for f in files if not f.archived]
            if not files:
                none = QLabel("This mod has no downloadable files.")
                none.setObjectName("Muted")
                self.lay.addWidget(none)
            elif len(live) > 1:
                fh = QLabel("Several files: usually one main download plus optional add-ons, or one file "
                            "per colour. Install replaces what you have; Add keeps it and installs this too.")
                fh.setObjectName("Muted")
                fh.setWordWrap(True)
                self.lay.addWidget(fh)
            for f in live + [f for f in files if f.archived][:3]:
                if f.id in have:
                    state = "current"
                elif main and newest and f.id == newest.id:
                    state = "update"
                elif main:
                    state = "older"
                else:
                    state = "new"
                row = FileRow(f, state, primary=(newest is not None and f.id == newest.id),
                              installed_name=main.file_name if main else "")
                row.install.connect(lambda file, add, s=sub: self.install_requested.emit(s.model, s.id, file, add))
                self.lay.addWidget(row)
            if self.details.text_html:
                dhead = QLabel("Description")
                dhead.setObjectName("SideTitle")
                self.lay.addWidget(dhead)
                desc = QTextBrowser()
                desc.setOpenExternalLinks(True)
                desc.setHtml(_clean_html(self.details.text_html))
                desc.setMinimumHeight(220)
                desc.setStyleSheet(f"background: {theme.PANEL}; color: {theme.TEXT};")
                self.lay.addWidget(desc)
        self.lay.addStretch(1)

    def _step(self, d):
        self.image_index += d
        self._render()


def _clean_html(html_text: str) -> str:
    text = re.sub(r"<(script|style|iframe)[^>]*>.*?</\1>", "", html_text, flags=re.S | re.I)
    text = re.sub(r"<img[^>]*>", "", text, flags=re.I)
    return f"<div style='color:{theme.TEXT}; line-height:140%'>{text}</div>"


# ---------------------------------------------------------------- filter panel

class FilterPanel(QWidget):
    changed = Signal()
    install_link = Signal(str)

    def __init__(self, settings):
        super().__init__()
        self.setObjectName("FilterPanel")
        self.setFixedWidth(theme.px(250))
        self.settings = settings
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search GameBanana")
        self.search.setClearButtonEnabled(True)
        self._debounce = QTimer(self, singleShot=True, interval=350)
        self._debounce.timeout.connect(self.changed)
        self.search.textChanged.connect(lambda: self._debounce.start())
        self.search.returnPressed.connect(lambda: (self._debounce.stop(), self.changed.emit()))
        lay.addWidget(self.search)

        type_row = QHBoxLayout()
        type_row.setSpacing(0)
        self.type_group = QButtonGroup(self)
        for i, (label, model) in enumerate((("Mods", "Mod"), ("Sounds", "Sound"))):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setProperty("model", model)
            radius = "" if theme.PIXEL else "border-top-left-radius:5px;border-bottom-left-radius:5px;" if i == 0 else \
                "border-top-right-radius:5px;border-bottom-right-radius:5px;"
            b.setProperty("kind", "toggle")     # coloured by the theme's stylesheet, so it follows theme changes
            b.setStyleSheet(f"QPushButton {{ border-radius: 0; {radius} }}")
            self.type_group.addButton(b, i)
            type_row.addWidget(b)
        self.type_group.button(0).setChecked(True)
        self.type_group.idToggled.connect(lambda _i, on: on and self.changed.emit())
        lay.addLayout(type_row)

        self.sort = QComboBox()
        for key, (label, _tok) in SORTS.items():
            self.sort.addItem(label, key)
        self.sort.currentIndexChanged.connect(self.changed)
        lay.addWidget(self.sort)

        cat_title = QLabel("Category")
        cat_title.setObjectName("SideTitle")
        lay.addWidget(cat_title)
        self.cat_filter = QLineEdit()
        self.cat_filter.setPlaceholderText("Find a category or hero")
        self.cat_filter.setClearButtonEnabled(True)
        self.cat_filter.textChanged.connect(self._filter_tree)
        lay.addWidget(self.cat_filter)
        self.tree = QTreeWidget()
        self.tree.setObjectName("CategoryTree")
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setColumnCount(2)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, self.tree.header().ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, self.tree.header().ResizeMode.ResizeToContents)
        self.tree.currentItemChanged.connect(lambda *_: self.changed.emit())
        lay.addWidget(self.tree, 1)

        show_title = QLabel("Show")
        show_title.setObjectName("SideTitle")
        lay.addWidget(show_title)
        nsfw_row = QHBoxLayout()
        nsfw_row.addWidget(QLabel("18+ mods"))
        self.nsfw = QComboBox()
        for label, key in (("Hide them", "hide"), ("Show them too", "show"), ("Only 18+", "only")):
            self.nsfw.addItem(label, key)
        self.nsfw.setToolTip("Mods GameBanana marks as mature (any content rating). "
                             "\"Only 18+\" looks through more pages to find them, so it can take a moment.")
        self.nsfw.setCurrentIndex(max(0, self.nsfw.findData(settings.nsfw)))
        self.nsfw.currentIndexChanged.connect(self.changed)
        nsfw_row.addWidget(self.nsfw, 1)
        self.hide_installed = QCheckBox("Hide mods I have")
        self.hide_installed.setChecked(settings.hide_installed)
        self.hide_obsolete = QCheckBox("Hide outdated mods")
        self.hide_obsolete.setChecked(settings.hide_obsolete)
        self.favourites_only = QCheckBox("Only my favourites ★")
        self.favourites_only.setToolTip("Show the mods you starred (works offline)")
        self.favourites_only.setChecked(settings.favourites_only)
        lay.addLayout(nsfw_row)
        for cb in (self.favourites_only, self.hide_installed, self.hide_obsolete):
            cb.toggled.connect(self.changed)
            lay.addWidget(cb)

        link_title = QLabel("Install from a link")
        link_title.setObjectName("SideTitle")
        lay.addWidget(link_title)
        link_row = QHBoxLayout()
        self.link = QLineEdit()
        self.link.setPlaceholderText("A mod or collection link")
        self.link.setToolTip("Paste a GameBanana mod, sound or collection link")
        go = QPushButton("Install")
        go.clicked.connect(self._link)
        self.link.returnPressed.connect(self._link)
        link_row.addWidget(self.link, 1)
        link_row.addWidget(go)
        lay.addLayout(link_row)
        self._loading_cats = None

    def _link(self):
        text = self.link.text().strip()
        if text:
            self.install_link.emit(text)
            self.link.clear()

    @property
    def model(self) -> str:
        return self.type_group.checkedButton().property("model")

    @property
    def category_id(self) -> int | None:
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if it else None

    def hero_categories(self) -> list[tuple[str, QTreeWidgetItem]]:
        """Skins › <hero> categories, alphabetically (the hero tour walks these)."""
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top.text(0).lower() == "skins":
                kids = [(top.child(j).text(0), top.child(j)) for j in range(top.childCount())]
                return sorted(kids, key=lambda x: hero_key(x[0]))
        return []

    def select_category(self, item: QTreeWidgetItem):
        if self.cat_filter.text():
            self.cat_filter.clear()         # the item might be hidden by the tree's search
        self.tree.setCurrentItem(item)     # emits changed -> Browse reloads
        self.tree.scrollToItem(item)

    def category_matches(self, sub: Submission) -> bool:
        """Whether a submission sits in the chosen category (used for favourites,
        which are filtered here rather than by GameBanana)."""
        it = self.tree.currentItem()
        if not it or it.data(0, Qt.UserRole) is None:
            return True
        parent = it.parent()
        if parent is None:
            return sub.root_category == it.text(0)
        return sub.root_category == parent.text(0) and sub.sub_category == it.text(0)

    def set_categories(self, cats: list[Category]):
        self.tree.blockSignals(True)
        self.tree.clear()
        everything = QTreeWidgetItem(["Everything", ""])
        everything.setData(0, Qt.UserRole, None)
        self.tree.addTopLevelItem(everything)

        def add(parent, cat: Category):
            item = QTreeWidgetItem([cat.name, fmt_count(cat.count) if cat.count else ""])
            item.setData(0, Qt.UserRole, cat.id)
            item.setForeground(1, QColor(theme.MUTED))
            parent.addChild(item) if isinstance(parent, QTreeWidgetItem) else self.tree.addTopLevelItem(item)
            for child in sorted(cat.children, key=lambda c: c.name.lower()):
                add(item, child)

        for cat in sorted(cats, key=lambda c: -c.count):
            add(self.tree, cat)
        self.tree.setCurrentItem(everything)
        self.tree.blockSignals(False)
        self._filter_tree(self.cat_filter.text())

    def _filter_tree(self, text: str):
        text = text.strip().lower()

        def visit(item: QTreeWidgetItem) -> bool:
            match = not text or text in item.text(0).lower()
            child_match = False
            for i in range(item.childCount()):
                child_match = visit(item.child(i)) or child_match
            item.setHidden(not (match or child_match))
            if text and child_match:
                item.setExpanded(True)
            return match or child_match

        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))



def hero_key(name: str) -> str:
    """Compare hero names loosely: "The Doorman" = "Doorman", "Mo & Krill" = "mo and krill"."""
    n = name.lower().replace("&", "and").strip()
    n = n[4:] if n.startswith("the ") else n
    return "".join(c for c in n if c.isalnum())

# ---------------------------------------------------------------- page

class BrowsePage(QWidget):
    install_requested = Signal(str, int, object, bool)  # model, id, GBFile|None, add alongside
    status = Signal(str)

    def __init__(self, manager, images):
        super().__init__()
        self.mgr = manager
        self.client = manager.gb
        self.images = images
        self.per_page = manager.lib.settings.per_page
        self.submitter: tuple[int, str] | None = None

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.filters = FilterPanel(manager.lib.settings)
        root.addWidget(self.filters)

        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(12, 12, 6, 0)
        cl.setSpacing(6)
        top = QHBoxLayout()
        self.result_label = QLabel("")
        self.result_label.setObjectName("Muted")
        top.addWidget(self.result_label)
        self.author_chip = QPushButton()
        self.author_chip.setToolTip("Stop filtering by this author")
        self.author_chip.setStyleSheet(f"QPushButton {{ background: {theme.ACCENT_LO}; border: none; border-radius: {theme.rad(11):g}px; padding: 3px 10px; }}")
        self.author_chip.hide()
        self.author_chip.clicked.connect(self.clear_author)
        top.addWidget(self.author_chip)
        top.addStretch(1)
        self.tour_btn = QPushButton("Hero tour")
        self.tour_btn.setToolTip("Go through every hero one at a time: see the skin you're using for them "
                                 "and browse their skins")
        self.tour_btn.clicked.connect(self.start_tour)
        top.addWidget(self.tour_btn)
        top.addSpacing(8)
        self.view_group = QButtonGroup(self)
        for i, (label, mode, tip) in enumerate((("Grid", "grid", "Big cards with previews"),
                                                 ("List", "list", "Compact rows, more mods on screen"))):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setProperty("kind", "toggle")
            b.setProperty("mode", mode)
            b.setToolTip(tip)
            radius = "" if theme.PIXEL else "border-top-left-radius:5px;border-bottom-left-radius:5px;" if i == 0 else \
                "border-top-right-radius:5px;border-bottom-right-radius:5px;"
            b.setStyleSheet(f"QPushButton {{ {radius} padding: 4px 12px; }}")
            self.view_group.addButton(b, i)
            top.addWidget(b)
            if mode == manager.lib.settings.view_mode:
                b.setChecked(True)
        if not self.view_group.checkedButton():
            self.view_group.button(0).setChecked(True)
        self.view_group.idToggled.connect(lambda i, on: on and self._view_changed(self.view_group.button(i).property("mode")))
        cl.addLayout(top)

        # the hero tour's bar: who you're on, what you're using, back / next
        self.tour_bar = QFrame()
        self.tour_bar.setObjectName("Banner")
        tb = QHBoxLayout(self.tour_bar)
        tb.setContentsMargins(12, 8, 8, 8)
        self.tour_info = QLabel()
        self.tour_info.setWordWrap(True)
        self.tour_info.setTextFormat(Qt.RichText)
        self.tour_info.setStyleSheet("background: transparent;")
        tb.addWidget(self.tour_info, 1)
        self.tour_back = QPushButton("◀ Back")
        self.tour_back.clicked.connect(lambda: self._tour_go(self._tour_i - 1))
        self.tour_next = QPushButton("Next ▶")
        self.tour_next.setProperty("kind", "primary")
        self.tour_next.clicked.connect(self._tour_forward)
        tour_end = QPushButton("End tour")
        tour_end.clicked.connect(self.end_tour)
        for b in (self.tour_back, self.tour_next, tour_end):
            tb.addWidget(b, 0, Qt.AlignVCenter)
        self.tour_bar.hide()
        cl.addWidget(self.tour_bar)
        self._tour: list[str] = []          # hero names, alphabetically
        self._tour_i = 0
        self._tour_tries = 0

        self.grid = CardGrid()
        self.model = SubmissionModel()
        self.grid.setModel(self.model)
        self.delegate = CardDelegate(self.grid, images, self._install_state)
        self.grid.setItemDelegate(self.delegate)
        self.grid.set_mode(manager.lib.settings.view_mode if manager.lib.settings.view_mode in ("grid", "list") else "grid")
        self.grid.near_bottom.connect(self.load_more)
        self.grid.selectionModel().currentChanged.connect(self._selected)
        cl.addWidget(self.grid, 1)

        self.message = QWidget()
        ml = QVBoxLayout(self.message)
        self.message_label = QLabel()
        self.message_label.setObjectName("Muted")
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setWordWrap(True)
        self.retry = QPushButton("Try again")
        self.retry.clicked.connect(self.reload)
        ml.addStretch(1)
        ml.addWidget(self.message_label)
        ml.addWidget(self.retry, 0, Qt.AlignCenter)
        ml.addStretch(1)
        self.message.hide()
        cl.addWidget(self.message, 1)
        root.addWidget(center, 1)

        self.detail = DetailPane(self.client, images, lambda m, i: self.mgr.lib.by_gb_all(m, i))
        self.detail.is_fav = lambda sub: self.mgr.lib.is_favourite(sub.model, sub.id)
        self.detail.toggle_fav = self._toggle_fav
        self.delegate.fav_fn = self.detail.is_fav
        self.detail.install_requested.connect(self.install_requested)
        self.detail.author_clicked.connect(self.filter_author)
        root.addWidget(self.detail)

        images.loaded.connect(lambda _u: self.grid.viewport().update())
        self.filters.changed.connect(self._filters_changed)
        self.filters.install_link.connect(self._install_link)

        self._token = 0
        self._page = 0
        self._complete = False
        self._loading = False
        self._total = 0
        self._shown = 0
        self._cats_loaded_for = None
        self._tour_label()

    # ------------------------------------------------------------ hero tour
    def _tour_label(self):
        at = self.mgr.lib.settings.hero_tour
        self.tour_btn.setText(f"Continue hero tour ({at})" if at else "Hero tour")

    def start_tour(self):
        """Walk through every hero's skins, alphabetically (Ham's idea)."""
        f = self.filters
        if f.model != "Mod":
            f.type_group.button(0).setChecked(True)   # skins are mods, not sounds (reloads the categories)
        heroes = [name for name, _item in f.hero_categories()]
        if not heroes:
            # categories load in the background: try again shortly
            self._tour_tries += 1
            if self._tour_tries <= 20:
                QTimer.singleShot(250, self.start_tour)
            else:
                self.status.emit("Couldn't load the hero list from GameBanana. Try again in a moment.")
                self._tour_tries = 0
            return
        self._tour_tries = 0
        self._tour = heroes
        at = self.mgr.lib.settings.hero_tour
        start = heroes.index(at) if at in heroes else 0
        self.tour_bar.show()
        self.tour_btn.hide()
        self._tour_go(start)

    def _tour_forward(self):
        if self._tour_i + 1 >= len(self._tour):
            self.end_tour(finished=True)
        else:
            self._tour_go(self._tour_i + 1)

    def _tour_go(self, i: int):
        if not self._tour:
            return
        self._tour_i = max(0, min(i, len(self._tour) - 1))
        hero = self._tour[self._tour_i]
        f = self.filters
        # look the category up each time: the tree is rebuilt whenever categories reload
        item = dict(f.hero_categories()).get(hero)
        if item is None:
            self.status.emit(f"GameBanana has no skins category for {hero} right now.")
            return
        # a clean view of this hero's skins: no search, author or favourites filter
        for w, clear in ((f.search, lambda: f.search.clear()),
                         (f.favourites_only, lambda: f.favourites_only.setChecked(False))):
            w.blockSignals(True)
            clear()
            w.blockSignals(False)
        if self.submitter:
            self.submitter = None
            self.author_chip.hide()
        if f.tree.currentItem() is item:
            self._filters_changed()
        else:
            f.select_category(item)
        self.mgr.lib.settings.hero_tour = hero
        self.mgr.lib.save()
        self._tour_refresh()

    def _tour_refresh(self):
        if not self._tour or not self.tour_bar.isVisible():
            return
        import html
        hero = self._tour[self._tour_i]
        n, total = self._tour_i + 1, len(self._tour)
        on, off = self.mods_for_hero(hero)
        if on:
            names = ", ".join(f"<b>{html.escape(m.name)}</b>" for m in on)
            using = f"Using {names}" + (" (the first one wins where they clash)" if len(on) > 1 else "")
        else:
            using = "Using the default look (no skin on)"
        extra = (f"<br>Installed but off: {html.escape(', '.join(m.name for m in off))}" if off else "")
        self.tour_info.setText(f"<span style='font-size:{theme.fpx(15)}px'><b>{html.escape(hero)}</b></span>"
                               f"&nbsp;&nbsp;hero {n} of {total}<br>{using}{extra}")
        self.tour_back.setEnabled(self._tour_i > 0)
        self.tour_next.setText(f"Next: {self._tour[self._tour_i + 1]} ▶" if n < total else "Finish ✓")

    def mods_for_hero(self, hero: str):
        """(on, off) installed mods that change this hero's look, in load order."""
        want = hero_key(hero)
        on, off = [], []
        for m in self.mgr.lib.ordered():
            hit = False
            cat = m.category.split(" › ")
            if len(cat) == 2 and cat[0].lower() == "skins" and hero_key(cat[1]) == want:
                hit = True
            else:
                try:
                    hit = any(hero_key(h) == want for h in self.mgr.hero_changes(m).reskinned)
                except Exception:  # noqa: BLE001 - a hint, never worth breaking Browse
                    hit = False
            if hit:
                (on if m.enabled else off).append(m)
        return on, off

    def end_tour(self, finished: bool = False):
        self.tour_bar.hide()
        self.tour_btn.show()
        if finished:
            self.mgr.lib.settings.hero_tour = ""
            self.mgr.lib.save()
            self.status.emit("That's every hero. Hero tour finished.")
        self._tour_label()

    # --------------------------------------------------------------- state
    def _install_state(self, sub: Submission):
        mod = self.mgr.lib.by_gb(sub.model, sub.id)
        if not mod:
            return None
        return "update" if mod.update else "installed"

    def _toggle_fav(self, sub) -> bool:
        on = self.mgr.lib.toggle_favourite(sub)
        self.mgr.lib.save()
        self.status.emit(f"Added {sub.name} to favourites." if on else f"Removed {sub.name} from favourites.")
        self.grid.viewport().update()
        if not on and self.filters.favourites_only.isChecked():
            self.reload()
        return on

    def _view_changed(self, mode: str):
        self.mgr.lib.settings.view_mode = mode
        self.mgr.lib.save()
        self.grid.set_mode(mode)
        QTimer.singleShot(0, self._maybe_fill)

    def rescale(self):
        self.filters.setFixedWidth(theme.px(250))
        self.detail.setFixedWidth(theme.px(384))
        self.grid.relayout()
        self.detail.refresh()

    def library_changed(self):
        self.model.refresh_all()
        self.detail.refresh()
        self._tour_refresh()      # e.g. you just installed this hero's skin
        if self.filters.hide_installed.isChecked():
            self.reload()

    def start(self):
        if self._cats_loaded_for is None:
            self._load_categories()
            self.reload()

    def _load_categories(self):
        model = self.filters.model
        self._cats_loaded_for = model
        run(self.client.categories, model,
            on_done=lambda cats, m=model: self.filters.set_categories(cats) if m == self.filters.model else None,
            on_error=lambda e: self.status.emit(f"Couldn't load categories: {e}"))

    def _filters_changed(self):
        s = self.mgr.lib.settings
        s.nsfw = self.filters.nsfw.currentData()
        s.hide_installed = self.filters.hide_installed.isChecked()
        s.hide_obsolete = self.filters.hide_obsolete.isChecked()
        s.favourites_only = self.filters.favourites_only.isChecked()
        self.mgr.lib.save()
        if self._cats_loaded_for != self.filters.model:
            self._load_categories()
        self.reload()

    def filter_author(self, author_id: int, name: str):
        self.submitter = (author_id, name)
        self.author_chip.setText(f"By {name}   ✕")
        self.author_chip.show()
        self.reload()

    def clear_author(self):
        self.submitter = None
        self.author_chip.hide()
        self.reload()

    # --------------------------------------------------------------- loading
    def reload(self):
        self._token += 1
        self._page = 0
        self._complete = False
        self._loading = False
        self._total = 0
        self._shown = 0
        self.model.clear()
        self.message.hide()
        self.grid.show()
        self.result_label.setText("Loading…")
        self.load_more()

    def load_more(self):
        if self._loading or self._complete:
            return
        self._loading = True
        token = self._token
        page = self._page + 1
        cat = self.filters.category_id
        if self.filters.favourites_only.isChecked():
            # Favourites come from the library, not GameBanana: filter them here.
            from sapphire.gamebanana import Page
            text = self.filters.search.text().strip().lower()
            subs = [x for x in self.mgr.lib.favourite_submissions() if x.model == self.filters.model
                    and (not text or text in x.name.lower() or text in x.author.lower())
                    and self.filters.category_matches(x)]
            key = self.filters.sort.currentData()
            order = {"popular": lambda s: -s.likes, "views": lambda s: -s.views,
                     "downloads": lambda s: -(s.downloads or s.likes),
                     "newest": lambda s: -s.date_added, "updated": lambda s: -s.date_modified}.get(key)
            if order:
                subs.sort(key=order)
            if self.submitter:
                subs = [x for x in subs if x.author_id == self.submitter[0]]
            QTimer.singleShot(0, lambda t=token, n=len(subs): self._got_page(
                Page(items=subs, total=n, complete=True, page=1), t, favourites=True))
            return
        # Only about one mod in ten is 18+, so "Only 18+" asks for the biggest pages
        # GameBanana allows and keeps going until the view fills (_maybe_fill).
        per_page = 50 if self.filters.nsfw.currentData() == "only" else self.per_page
        self._page_size = per_page
        run(self.client.browse, self.filters.model, page, per_page,
            self.filters.search.text(), cat, self.filters.sort.currentData(),
            self.submitter[0] if self.submitter else None,
            on_done=lambda pg, t=token: self._got_page(pg, t),
            on_error=lambda e, t=token: self._page_failed(e, t))

    def _got_page(self, page, token, favourites: bool = False):
        if token != self._token:
            return
        self._loading = False
        self._page = page.page
        self._total = page.total
        raw_count = len(page.items)
        items = page.items
        nsfw = self.filters.nsfw.currentData()
        if nsfw == "hide":
            items = [s for s in items if not s.nsfw]
        elif nsfw == "only":
            items = [s for s in items if s.nsfw]
        if self.filters.hide_obsolete.isChecked():
            items = [s for s in items if not s.obsolete]
        if self.filters.hide_installed.isChecked():
            items = [s for s in items if not self.mgr.lib.by_gb(s.model, s.id)]
        self.model.extend(items)
        self._shown = len(self.model.items)
        size = self.per_page if favourites else getattr(self, "_page_size", self.per_page)
        self._complete = page.complete or raw_count == 0 or page.page * size >= page.total
        noun = "sounds" if self.filters.model == "Sound" else "mods"
        if self._shown == 0 and self._complete:
            self.grid.hide()
            self.message_label.setText(
                f"No favourite {noun} yet. Open one and press ☆ Favourite to keep it here." if favourites else
                f"No {noun} match these filters. Try a broader search or another category.")
            self.retry.hide()
            self.message.show()
            self.result_label.setText("")
            return
        if favourites:
            self.result_label.setText(f"{page.total:,} favourite {noun}")
        elif nsfw == "only":
            # GameBanana can't count these for us: say how far the search has got
            checked = min(page.total, page.page * size)
            one = noun[:-1] if self._shown == 1 else noun
            self.result_label.setText(f"{self._shown:,} 18+ {one}" if self._complete else
                                      f"{self._shown:,} 18+ {one} so far (looked through {checked:,} of {page.total:,})")
        else:
            self.result_label.setText(f"{page.total:,} {noun} on GameBanana")
        # Keep pulling pages until the view can scroll (filters may hide a lot).
        QTimer.singleShot(0, self._maybe_fill)

    def _maybe_fill(self):
        bar = self.grid.verticalScrollBar()
        if not self._complete and (bar.maximum() == 0 or bar.maximum() - bar.value() < 600):
            self.load_more()

    def _page_failed(self, exc, token):
        if token != self._token:
            return
        self._loading = False
        if self.model.items:
            self.status.emit(f"Couldn't load more: {exc}")
            return
        self.grid.hide()
        self.message_label.setText(f"Couldn't reach GameBanana.\n{exc}")
        self.retry.show()
        self.message.show()
        self.result_label.setText("")

    def _selected(self, current, _prev):
        sub = current.data(ROLE_SUB) if current.isValid() else None
        if sub:
            self.detail.show_sub(sub)

    collection_requested = Signal(int)

    def _install_link(self, text: str):
        from sapphire.gamebanana import parse_collection_url
        cid = parse_collection_url(text)
        if cid:
            self.collection_requested.emit(cid)
            return
        parsed = parse_url(text)
        if not parsed:
            self.status.emit("That doesn't look like a GameBanana mod, sound or collection link.")
            return
        model, mid = parsed
        self.install_requested.emit(model, mid, None, False)
