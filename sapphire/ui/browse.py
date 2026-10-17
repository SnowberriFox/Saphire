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
        self.card_size = QSize(232, 210)

    def sizeHint(self, option, index):
        return self.card_size

    def paint(self, p: QPainter, option, index):
        sub: Submission = index.data(ROLE_SUB)
        if sub is None:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect).adjusted(6, 6, -6, -6)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        path = QPainterPath()
        path.addRoundedRect(r, 8, 8)
        p.fillPath(path, QColor(theme.PANEL))
        if selected or hovered:
            p.setPen(QPen(QColor(theme.ACCENT if selected else theme.ACCENT_LO), 1.5))
            p.drawPath(path)

        img_h = r.width() * 9 / 16
        img_rect = QRectF(r.left(), r.top(), r.width(), img_h)
        p.save()
        clip = QPainterPath()
        clip.setFillRule(Qt.WindingFill)
        clip.addRoundedRect(img_rect, 8, 8)
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

        # badges on the image
        state = self.installed_fn(sub)
        bx = img_rect.left() + 8
        for text, bg, fg in (
            ("Update ready", theme.ACCENT, "#0B1426") if state == "update" else
            ("Installed", "#1E3A2F", theme.VERDIGRIS) if state == "installed" else (None, None, None),
            ("18+", theme.OXBLOOD, "#FFF2EE") if sub.nsfw else (None, None, None),
            ("Outdated", "#2E3545", theme.MUTED) if sub.obsolete else (None, None, None),
        ):
            if not text:
                continue
            f = QFont(p.font())
            f.setPixelSize(11)
            f.setBold(True)
            p.setFont(f)
            w = p.fontMetrics().horizontalAdvance(text) + 14
            badge = QRectF(bx, img_rect.top() + 8, w, 20)
            bp = QPainterPath()
            bp.addRoundedRect(badge, 10, 10)
            p.fillPath(bp, QColor(bg))
            p.setPen(QColor(fg))
            p.drawText(badge, Qt.AlignCenter, text)
            bx += w + 6

        # text
        text_rect = QRectF(r.left() + 10, img_rect.bottom() + 8, r.width() - 20, 38)
        f = QFont(p.font())
        f.setPixelSize(13)
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
        for i, line in enumerate(lines):
            p.drawText(QRectF(text_rect.left(), text_rect.top() + i * 18, text_rect.width(), 18),
                       Qt.AlignLeft | Qt.AlignVCenter, line)

        f.setBold(False)
        f.setPixelSize(12)
        p.setFont(f)
        p.setPen(QColor(theme.MUTED))
        meta_rect = QRectF(r.left() + 10, r.bottom() - 24, r.width() - 20, 18)
        likes = f"♥ {fmt_count(sub.likes)}"
        lw = p.fontMetrics().horizontalAdvance(likes)
        p.drawText(meta_rect.adjusted(0, 0, -(lw + 10), 0), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(sub.author or "unknown", Qt.ElideRight,
                                              int(meta_rect.width() - lw - 10)))
        p.drawText(meta_rect, Qt.AlignRight | Qt.AlignVCenter, likes)
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

    def resizeEvent(self, e):
        super().resizeEvent(e)
        delegate = self.itemDelegate()
        if isinstance(delegate, CardDelegate):
            avail = self.viewport().width() - 4
            cols = max(1, avail // 228)
            w = avail // cols
            delegate.card_size = QSize(w, int((w - 12) * 9 / 16) + 96)
            self.setGridSize(delegate.card_size)


# ---------------------------------------------------------------- detail pane

class FileRow(QFrame):
    install = Signal(object)

    def __init__(self, f: GBFile, state: str, primary: bool):
        super().__init__()
        self.setObjectName("Panel")
        self.setStyleSheet(f"#Panel {{ background: {theme.RAISED}; border-radius: 6px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(4)
        top = QHBoxLayout()
        name = QLabel(f.filename)
        name.setStyleSheet("background: transparent; font-weight: 600;")
        name.setWordWrap(True)
        top.addWidget(name, 1)
        btn = QPushButton({"current": "Reinstall", "update": "Update to this",
                           "older": "Install this version"}.get(state, "Install"))
        if primary and state != "current":
            btn.setProperty("kind", "primary")
        btn.clicked.connect(lambda: self.install.emit(f))
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
    install_requested = Signal(str, int, object)  # model, id, GBFile
    author_clicked = Signal(int, str)

    def __init__(self, client, images, installed_lookup):
        super().__init__()
        self.client = client
        self.images = images
        self.installed_lookup = installed_lookup  # (model, id) -> InstalledMod|None
        self.setObjectName("DetailPanel")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setFixedWidth(384)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body.setObjectName("DetailPanel")
        self.setWidget(self.body)
        self.lay = QVBoxLayout(self.body)
        self.lay.setContentsMargins(16, 16, 16, 16)
        self.lay.setSpacing(10)
        self.sub: Submission | None = None
        self.details: Details | None = None
        self.image_index = 0
        self._token = 0
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
        img.setStyleSheet(f"background: {theme.RAISED}; border-radius: 6px;")
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
        self.lay.addWidget(meta)
        open_btn = QPushButton("Open on GameBanana")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(sub.url or f"https://gamebanana.com/mods/{sub.id}")))
        self.lay.addWidget(open_btn)

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
            installed = self.installed_lookup(sub.model, sub.id)
            files = self.details.files
            newest = newest_file(files)
            live = [f for f in files if not f.archived]
            if not files:
                none = QLabel("This mod has no downloadable files.")
                none.setObjectName("Muted")
                self.lay.addWidget(none)
            for f in live + [f for f in files if f.archived][:3]:
                if installed and installed.file_id == f.id:
                    state = "current"
                elif installed and newest and f.id == newest.id:
                    state = "update"
                elif installed:
                    state = "older"
                else:
                    state = "new"
                row = FileRow(f, state, primary=(newest is not None and f.id == newest.id))
                row.install.connect(lambda file, s=sub: self.install_requested.emit(s.model, s.id, file))
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
        self.setFixedWidth(250)
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
            radius = "border-top-left-radius:5px;border-bottom-left-radius:5px;" if i == 0 else \
                "border-top-right-radius:5px;border-bottom-right-radius:5px;"
            b.setStyleSheet(f"QPushButton {{ border-radius: 0; {radius} }}"
                            f"QPushButton:checked {{ background: {theme.ACCENT_LO}; color: {theme.TEXT}; border-color: {theme.ACCENT_LO}; }}")
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
        self.hide_nsfw = QCheckBox("Hide 18+ mods")
        self.hide_nsfw.setChecked(settings.hide_nsfw)
        self.hide_installed = QCheckBox("Hide mods I have")
        self.hide_installed.setChecked(settings.hide_installed)
        self.hide_obsolete = QCheckBox("Hide outdated mods")
        self.hide_obsolete.setChecked(settings.hide_obsolete)
        for cb in (self.hide_nsfw, self.hide_installed, self.hide_obsolete):
            cb.toggled.connect(self.changed)
            lay.addWidget(cb)

        link_title = QLabel("Install from a link")
        link_title.setObjectName("SideTitle")
        lay.addWidget(link_title)
        link_row = QHBoxLayout()
        self.link = QLineEdit()
        self.link.setPlaceholderText("gamebanana.com/mods/…")
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


# ---------------------------------------------------------------- page

class BrowsePage(QWidget):
    install_requested = Signal(str, int, object)  # model, id, GBFile|None
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
        self.author_chip.setStyleSheet(f"QPushButton {{ background: {theme.ACCENT_LO}; border: none; border-radius: 11px; padding: 3px 10px; }}")
        self.author_chip.hide()
        self.author_chip.clicked.connect(self.clear_author)
        top.addWidget(self.author_chip)
        top.addStretch(1)
        cl.addLayout(top)

        self.grid = CardGrid()
        self.model = SubmissionModel()
        self.grid.setModel(self.model)
        self.delegate = CardDelegate(self.grid, images, self._install_state)
        self.grid.setItemDelegate(self.delegate)
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

        self.detail = DetailPane(self.client, images, lambda m, i: self.mgr.lib.by_gb(m, i))
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

    # --------------------------------------------------------------- state
    def _install_state(self, sub: Submission):
        mod = self.mgr.lib.by_gb(sub.model, sub.id)
        if not mod:
            return None
        return "update" if mod.update else "installed"

    def library_changed(self):
        self.model.refresh_all()
        self.detail.refresh()
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
        s.hide_nsfw = self.filters.hide_nsfw.isChecked()
        s.hide_installed = self.filters.hide_installed.isChecked()
        s.hide_obsolete = self.filters.hide_obsolete.isChecked()
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
        run(self.client.browse, self.filters.model, page, self.per_page,
            self.filters.search.text(), cat, self.filters.sort.currentData(),
            self.submitter[0] if self.submitter else None,
            on_done=lambda pg, t=token: self._got_page(pg, t),
            on_error=lambda e, t=token: self._page_failed(e, t))

    def _got_page(self, page, token):
        if token != self._token:
            return
        self._loading = False
        self._page = page.page
        self._total = page.total
        raw_count = len(page.items)
        items = page.items
        if self.filters.hide_nsfw.isChecked():
            items = [s for s in items if not s.nsfw]
        if self.filters.hide_obsolete.isChecked():
            items = [s for s in items if not s.obsolete]
        if self.filters.hide_installed.isChecked():
            items = [s for s in items if not self.mgr.lib.by_gb(s.model, s.id)]
        self.model.extend(items)
        self._shown = len(self.model.items)
        self._complete = page.complete or raw_count == 0 or page.page * self.per_page >= page.total
        noun = "sounds" if self.filters.model == "Sound" else "mods"
        if self._shown == 0 and self._complete:
            self.grid.hide()
            self.message_label.setText(f"No {noun} match these filters. Try a broader search or another category.")
            self.retry.hide()
            self.message.show()
            self.result_label.setText("")
            return
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

    def _install_link(self, text: str):
        parsed = parse_url(text)
        if not parsed:
            self.status.emit("That doesn't look like a GameBanana mod link.")
            return
        model, mid = parsed
        self.install_requested.emit(model, mid, None)
