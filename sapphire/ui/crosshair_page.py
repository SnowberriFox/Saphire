"""The Crosshair page: crosshair editor with a live preview, and an autoexec.cfg editor."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QGuiApplication, QLinearGradient, QPainter,
                           QPainterPath)
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
                               QSlider, QTabWidget, QVBoxLayout, QWidget)

from sapphire import crosshair as ch
from sapphire.ui import theme
from sapphire.ui.dialogs import ask_text, confirm, error

BACKGROUNDS = ("Dusk", "Bright", "Dark", "Grey")


class Preview(QWidget):
    """An approximation of the in-game crosshair, drawn bigger so details are visible."""

    def __init__(self):
        super().__init__()
        self.values = ch.defaults()
        self.background = BACKGROUNDS[0]
        self.zoom = 3.0
        self.setMinimumSize(theme.px(300), theme.px(300))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_values(self, values):
        self.values = dict(values)
        self.update()

    def _bg(self, p: QPainter, r: QRectF):
        if self.background == "Bright":
            g = QLinearGradient(r.topLeft(), r.bottomLeft())
            g.setColorAt(0, QColor("#bcd7f2"))
            g.setColorAt(1, QColor("#e9e2cf"))
            p.fillRect(r, g)
        elif self.background == "Dark":
            p.fillRect(r, QColor("#101216"))
        elif self.background == "Grey":
            p.fillRect(r, QColor("#7d7f84"))
        else:
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0, QColor("#2b3550"))
            g.setColorAt(0.55, QColor("#7a5a4a"))
            g.setColorAt(1, QColor("#c9a46a"))
            p.fillRect(r, g)

    def paintEvent(self, _e):
        v = self.values
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        r = QRectF(self.rect())
        p.save()
        clip = QPainterPath()
        clip.addRoundedRect(r, theme.rad(8), theme.rad(8))
        p.setClipPath(clip)
        self._bg(p, r)
        z = self.zoom
        cx, cy = r.center().x(), r.center().y()
        col = QColor(int(v["crosshair_color_r"]), int(v["crosshair_color_g"]), int(v["crosshair_color_b"]))
        out = QColor(int(v["crosshair_outline_color_r"]), int(v["crosshair_outline_color_g"]),
                     int(v["crosshair_outline_color_b"]))

        def box(x, y, w, h, color, alpha, border, border_alpha, gap=0.0):
            if border > 0 and border_alpha > 0:
                b = (border + gap) * z
                o = QColor(out)
                o.setAlphaF(max(0.0, min(1.0, border_alpha)))
                p.fillRect(QRectF(x - b, y - b, w + 2 * b, h + 2 * b), o)
                if gap > 0:   # the outline floats: show the background between it and the shape
                    self._bg_rect(p, QRectF(x - gap * z, y - gap * z, w + 2 * gap * z, h + 2 * gap * z), r)
            c = QColor(color)
            c.setAlphaF(max(0.0, min(1.0, alpha)))
            p.fillRect(QRectF(x, y, w, h), c)

        # lines
        width = v["crosshair_pip_width"] * z
        length = v["crosshair_pip_height"] * z
        gap = ch.gap_px(v) * z
        pa, ob = v["crosshair_pip_opacity"], v["crosshair_pip_outline_border"]
        oo, og = v["crosshair_pip_outline_opacity"] * pa, v["crosshair_pip_outline_gap"]
        if width > 0 and length > 0 and pa > 0:
            for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                if dx == 0:
                    x, w, h = cx - width / 2, width, length
                    y = cy - gap - length if dy < 0 else cy + gap
                else:
                    y, w, h = cy - width / 2, length, width
                    x = cx - gap - length if dx < 0 else cx + gap
                box(x, y, w, h, col, pa, ob, oo, og)
        # dot
        ds = v["crosshair_dot_size"] * z
        da = v["crosshair_dot_opacity"]
        if ds > 0 and da > 0:
            box(cx - ds / 2, cy - ds / 2, ds, ds, col, da, v["crosshair_dot_outline_border"],
                v["crosshair_dot_outline_opacity"] * da, v["crosshair_dot_outline_gap"])
        p.restore()
        p.setPen(QColor(255, 255, 255, 150))
        f = QFont(p.font())
        f.setPixelSize(theme.fpx(11))
        p.setFont(f)
        p.drawText(r.adjusted(10, 0, -10, -8), Qt.AlignBottom | Qt.AlignRight,
                   f"approximate preview, {self.zoom:g}× size")

    def _bg_rect(self, p: QPainter, rect: QRectF, full: QRectF):
        # repaint the background inside an outline gap
        p.save()
        p.setClipRect(rect)
        self._bg(p, full)
        p.restore()


class _Num(QWidget):
    """Slider + spin box bound to one setting."""
    changed = Signal()

    def __init__(self, s: ch.Setting):
        super().__init__()
        self.s = s
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.scale = 1 if s.kind == "int" else round(1 / s.step)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(int(s.lo * self.scale), int(s.hi * self.scale))
        self.slider.setSingleStep(max(1, int(s.step * self.scale)))
        self.spin = QDoubleSpinBox()   # one widget type for every number, so they all look alike
        self.spin.setDecimals(0 if s.kind == "int" else 2)
        self.spin.setSingleStep(s.step)
        self.spin.setRange(s.lo, s.hi)
        self.spin.setFixedWidth(theme.px(80))
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.spin)
        self.slider.valueChanged.connect(lambda n: self._set(n / self.scale, from_slider=True))
        self.spin.valueChanged.connect(lambda n: self._set(n, from_slider=False))
        self._busy = False

    def _set(self, val, from_slider):
        if self._busy:
            return
        self._busy = True
        if from_slider:
            self.spin.setValue(round(val) if self.s.kind == "int" else val)
        else:
            self.slider.setValue(int(round(val * self.scale)))
        self._busy = False
        self.changed.emit()

    def value(self) -> float:
        return float(self.spin.value())

    def set_value(self, v):
        self._busy = True
        self.spin.setValue(float(v))
        self.slider.setValue(int(round(float(v) * self.scale)))
        self._busy = False


class CrosshairTab(QWidget):
    status = Signal(str)

    def __init__(self, manager):
        super().__init__()
        self.mgr = manager
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(18)

        # controls (scrolls on small windows)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        scroll.setWidget(body)
        scroll.setMinimumWidth(theme.px(420))
        form = QVBoxLayout(body)
        form.setContentsMargins(0, 0, 8, 0)
        form.setSpacing(6)
        self.widgets: dict[str, object] = {}

        def section(name):
            lbl = QLabel(name)
            lbl.setObjectName("SideTitle")
            form.addWidget(lbl)
            g = QGridLayout()
            g.setHorizontalSpacing(12)
            g.setVerticalSpacing(4)
            form.addLayout(g)
            return g

        # colours
        g = section("Colour")
        self.color_btn = QPushButton("Crosshair colour…")
        self.color_btn.clicked.connect(lambda: self._pick("crosshair_color"))
        self.outline_btn = QPushButton("Outline colour…")
        self.outline_btn.clicked.connect(lambda: self._pick("crosshair_outline_color"))
        g.addWidget(self.color_btn, 0, 0)
        g.addWidget(self.outline_btn, 0, 1)
        for group in ("Lines", "Outline", "Dot"):
            g = section(group)
            row = 0
            for s in ch.SETTINGS:
                if s.group != group or "color" in s.key:
                    continue
                if s.kind == "bool":
                    w = QCheckBox(s.label)
                    w.toggled.connect(self._changed)
                    g.addWidget(w, row, 0, 1, 2)
                else:
                    lbl = QLabel(s.label)
                    w = _Num(s)
                    w.changed.connect(self._changed)
                    g.addWidget(lbl, row, 0)
                    g.addWidget(w, row, 1)
                self.widgets[s.key] = w
                row += 1
            g.setColumnStretch(1, 1)
        form.addStretch(1)
        root.addWidget(scroll, 4)

        # preview + actions
        right = QVBoxLayout()
        right.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(QLabel("Background"))
        self.bg = QComboBox()
        self.bg.addItems(BACKGROUNDS)
        self.bg.currentTextChanged.connect(self._bg_changed)
        top.addWidget(self.bg)
        top.addWidget(QLabel("Zoom"))
        self.zoom = QComboBox()
        for z in ("1×", "2×", "3×", "5×"):
            self.zoom.addItem(z, float(z[:-1]))
        self.zoom.setCurrentIndex(2)
        self.zoom.currentIndexChanged.connect(self._zoom_changed)
        top.addWidget(self.zoom)
        top.addStretch(1)
        right.addLayout(top)
        self.preview = Preview()
        right.addWidget(self.preview, 1)

        presets = QHBoxLayout()
        presets.addWidget(QLabel("Saved"))
        self.preset_box = QComboBox()
        self.preset_box.setMinimumWidth(theme.px(160))
        self.preset_box.activated.connect(self._use_preset)
        presets.addWidget(self.preset_box, 1)
        save_p = QPushButton("Save as…")
        save_p.clicked.connect(self._save_preset)
        self.del_p = QPushButton("Delete")
        self.del_p.clicked.connect(self._delete_preset)
        presets.addWidget(save_p)
        presets.addWidget(self.del_p)
        right.addLayout(presets)

        share = QHBoxLayout()
        copy = QPushButton("Copy as console commands")
        copy.setToolTip("Copies citadel_crosshair_… commands: paste them in Deadlock's console, "
                        "send them to a friend, or use them in another mod manager")
        copy.clicked.connect(self._copy)
        paste = QPushButton("Paste")
        paste.setToolTip("Fill the editor from crosshair commands on the clipboard "
                         "(console commands or a Deadlock Mod Manager share code)")
        paste.clicked.connect(self._paste)
        share.addWidget(copy)
        share.addWidget(paste)
        share.addStretch(1)
        right.addLayout(share)

        acts = QHBoxLayout()
        self.apply_btn = QPushButton("Use in Deadlock")
        self.apply_btn.setProperty("kind", "primary")
        self.apply_btn.setToolTip("Writes this crosshair into Deadlock's settings (and the Steam Cloud copy). "
                                  "Deadlock needs to be closed.")
        self.apply_btn.clicked.connect(self._apply)
        self.reload_btn = QPushButton("Load from game")
        self.reload_btn.setToolTip("Throw away edits and show the crosshair Deadlock has now")
        self.reload_btn.clicked.connect(self.load)
        self.restore_btn = QPushButton("Restore my old crosshair")
        self.restore_btn.setToolTip("Put back the crosshair you had before Sapphire changed it")
        self.restore_btn.clicked.connect(self._restore)
        acts.addWidget(self.apply_btn)
        acts.addWidget(self.reload_btn)
        acts.addStretch(1)
        acts.addWidget(self.restore_btn)
        right.addLayout(acts)
        self.note = QLabel()
        self.note.setObjectName("Muted")
        self.note.setWordWrap(True)
        right.addWidget(self.note)
        root.addLayout(right, 5)
        self._loading = False
        self.load()

    # -- values
    def values(self) -> dict[str, float]:
        out = dict(self._colors)
        for key, w in self.widgets.items():
            out[key] = (1.0 if w.isChecked() else 0.0) if isinstance(w, QCheckBox) else w.value()
        return out

    def set_values(self, vals: dict[str, float]):
        self._loading = True
        full = ch.defaults()
        full.update(vals)
        self._colors = {k: full[k] for k in full if "color" in k}
        for key, w in self.widgets.items():
            if isinstance(w, QCheckBox):
                w.setChecked(bool(full[key]))
            else:
                w.set_value(full[key])
        self._loading = False
        self._changed()

    def _changed(self, *_):
        if self._loading:
            return
        v = self.values()
        self.preview.set_values(v)
        for btn, prefix in ((self.color_btn, "crosshair_color"), (self.outline_btn, "crosshair_outline_color")):
            c = QColor(int(v[f"{prefix}_r"]), int(v[f"{prefix}_g"]), int(v[f"{prefix}_b"]))
            fg = "#000" if c.lightness() > 140 else "#fff"
            btn.setStyleSheet(f"QPushButton {{ background: {c.name()}; color: {fg}; }}")

    def _pick(self, prefix: str):
        v = self.values()
        cur = QColor(int(v[f"{prefix}_r"]), int(v[f"{prefix}_g"]), int(v[f"{prefix}_b"]))
        c = QColorDialog.getColor(cur, self, "Crosshair colour" if prefix == "crosshair_color" else "Outline colour")
        if c.isValid():
            self._colors.update({f"{prefix}_r": c.red(), f"{prefix}_g": c.green(), f"{prefix}_b": c.blue()})
            self._changed()

    def _bg_changed(self, name):
        self.preview.background = name
        self.preview.update()

    def _zoom_changed(self, _i):
        self.preview.zoom = self.zoom.currentData()
        self.preview.update()

    # -- game files
    def load(self):
        gd = self.mgr.game_dir
        self._colors = {}
        if not gd:
            self.set_values(ch.defaults())
            self.note.setText("Set your Deadlock folder in Settings to edit its crosshair.")
            self._sync_buttons()
            return
        try:
            vals, themed = ch.current(gd)
        except ch.CrosshairError as exc:
            self.set_values(ch.defaults())
            self.note.setText(f"Couldn't read Deadlock's crosshair settings ({exc}).")
            self._sync_buttons()
            return
        self.set_values(vals)
        n = len(ch.settings_paths(gd))
        where = ("Deadlock's crosshair settings" if n == 1 else
                 "both copies of Deadlock's crosshair settings (the game's and Steam Cloud's)" if n == 2 else
                 f"all {n} copies of Deadlock's crosshair settings (the game's and Steam Cloud's)")
        self.note.setText(
            ("Deadlock is using each hero's themed crosshair right now; using this one switches that off. " if themed else "")
            + f"“Use in Deadlock” writes {where} and keeps your current crosshair so you can restore it. "
            "Close Deadlock first.")
        self._sync_buttons()

    def _sync_buttons(self):
        self.restore_btn.setEnabled(ch.has_backup())
        names = sorted(ch.presets())
        self.preset_box.clear()
        self.preset_box.addItem("Choose a saved crosshair…" if names else "Nothing saved yet", None)
        for n in names:
            self.preset_box.addItem(n, n)
        self.del_p.setEnabled(bool(names))
        self.apply_btn.setEnabled(bool(self.mgr.game_dir))

    def _apply(self):
        gd = self.mgr.game_dir
        if not gd:
            return
        try:
            changed = ch.apply(gd, self.values())
        except (ch.CrosshairError, OSError) as exc:
            error(self, "Couldn't change the crosshair", str(exc))
            return
        self.status.emit("Crosshair saved. Start Deadlock to see it." if changed else "That's already the crosshair.")
        self._sync_buttons()

    def _restore(self):
        gd = self.mgr.game_dir
        if not gd or not confirm(self, "Restore crosshair", "Put back the crosshair you had before Sapphire "
                                                            "changed it?", "Restore"):
            return
        try:
            ch.restore(gd)
        except (ch.CrosshairError, OSError) as exc:
            error(self, "Couldn't restore", str(exc))
            return
        self.load()
        self.status.emit("Your old crosshair is back.")

    def _copy(self):
        QGuiApplication.clipboard().setText(ch.to_commands(self.values()))
        self.status.emit("Crosshair copied as console commands.")

    def _paste(self):
        got = ch.from_commands(QGuiApplication.clipboard().text())
        if not got:
            self.status.emit("No crosshair commands on the clipboard.")
            return
        v = self.values()
        v.update(got)
        self.set_values(v)
        self.status.emit(f"Pasted {len(got)} crosshair setting{'s' if len(got) != 1 else ''}. "
                         "Press “Use in Deadlock” to save them.")

    def _use_preset(self, _i):
        name = self.preset_box.currentData()
        if name:
            v = self.values()
            v.update(ch.presets().get(name, {}))
            self.set_values(v)

    def _save_preset(self):
        name = ask_text(self, "Save crosshair", "Name:", self.preset_box.currentData() or "")
        if name:
            ch.save_preset(name, self.values())
            self._sync_buttons()
            self.preset_box.setCurrentIndex(self.preset_box.findData(name))

    def _delete_preset(self):
        name = self.preset_box.currentData()
        if name and confirm(self, "Delete", f"Delete the saved crosshair “{name}”?", "Delete", danger=True):
            ch.delete_preset(name)
            self._sync_buttons()


class AutoexecTab(QWidget):
    status = Signal(str)

    def __init__(self, manager):
        super().__init__()
        self.mgr = manager
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(8)
        hint = QLabel("autoexec.cfg is a list of console commands Deadlock runs when it starts, one per line "
                      "(fps_max 240, for example). The game only reads it when its Steam launch options include "
                      "+exec autoexec: right-click Deadlock in Steam → Properties → Launch options. "
                      "Sapphire never saves it empty, because an empty file can crash the game with that option set.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.edit = QPlainTextEdit()
        f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        f.setPointSize(max(9, f.pointSize()))
        self.edit.setFont(f)
        # the app stylesheet sets one font for every widget; code wants a fixed-width one
        self.edit.setStyleSheet(f"QPlainTextEdit {{ font-family: '{f.family()}', 'DejaVu Sans Mono', "
                                "'Noto Sans Mono', monospace; }")
        self.edit.setPlaceholderText("// one command per line, e.g.\nfps_max 240")
        self.edit.textChanged.connect(self._dirty)
        lay.addWidget(self.edit, 1)
        row = QHBoxLayout()
        self.save_btn = QPushButton("Save")
        self.save_btn.setProperty("kind", "primary")
        self.save_btn.clicked.connect(self.save)
        rel = QPushButton("Reload")
        rel.clicked.connect(self.load)
        launch = QPushButton("Copy launch option")
        launch.setToolTip("Copies +exec autoexec to paste into Deadlock's Steam launch options")
        launch.clicked.connect(lambda: (QGuiApplication.clipboard().setText("+exec autoexec"),
                                        self.status.emit("Copied +exec autoexec.")))
        self.state = QLabel()
        self.state.setObjectName("Muted")
        row.addWidget(self.save_btn)
        row.addWidget(rel)
        row.addWidget(launch)
        row.addStretch(1)
        row.addWidget(self.state)
        lay.addLayout(row)
        self.load()

    def load(self):
        gd = self.mgr.game_dir
        self.edit.blockSignals(True)
        self.edit.setPlainText(ch.read_autoexec(gd) if gd else "")
        self.edit.blockSignals(False)
        self.edit.setEnabled(bool(gd))
        self.save_btn.setEnabled(False)
        self.state.setText(str(ch.autoexec_path(gd)) if gd else "Set your Deadlock folder in Settings first.")

    def _dirty(self):
        self.save_btn.setEnabled(True)
        self.state.setText("Unsaved changes")

    def save(self):
        gd = self.mgr.game_dir
        if not gd:
            return
        try:
            saved = ch.write_autoexec(gd, self.edit.toPlainText())
        except OSError as exc:
            error(self, "Couldn't save autoexec.cfg", str(exc))
            return
        if saved != self.edit.toPlainText():
            self.edit.blockSignals(True)
            self.edit.setPlainText(saved)
            self.edit.blockSignals(False)
        self.save_btn.setEnabled(False)
        self.state.setText("Saved")
        self.status.emit("autoexec.cfg saved. It applies the next time Deadlock starts.")


class CrosshairPage(QWidget):
    status = Signal(str)

    def __init__(self, manager):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(6)
        title = QLabel("Crosshair & config")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        self.tabs = QTabWidget()
        self.crosshair = CrosshairTab(manager)
        self.autoexec = AutoexecTab(manager)
        self.tabs.addTab(self.crosshair, "Crosshair")
        self.tabs.addTab(self.autoexec, "Autoexec")
        root.addWidget(self.tabs, 1)
        self.crosshair.status.connect(self.status)
        self.autoexec.status.connect(self.status)

    def refresh(self):
        self.crosshair.load()
        if not self.autoexec.save_btn.isEnabled():
            self.autoexec.load()
