"""Profiles and Settings pages."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from sapphire import __version__, paths, steam
from sapphire.ui import theme
from sapphire.ui.dialogs import ask_text, confirm, error


def _section(title: str) -> QLabel:
    lbl = QLabel(title)
    lbl.setObjectName("SideTitle")
    return lbl


class ProfilesPage(QWidget):
    changed = Signal()
    import_requested = Signal(object)   # path of a shared profile file

    def __init__(self, manager):
        super().__init__()
        self.mgr = manager
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(10)
        title = QLabel("Profiles")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        hint = QLabel("Each profile is its own setup: its own mods, order and on/off. Installed only shows the "
                      "profile you're on, and changes save into it as you make them. Mods are downloaded once and "
                      "shared, so switching is instant and nothing downloads twice.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        row = QHBoxLayout()
        self.new_btn = QPushButton("New profile…")
        self.new_btn.setProperty("kind", "primary")
        self.new_btn.clicked.connect(self.new_profile)
        row.addWidget(self.new_btn)
        row.addStretch(1)
        self.import_btn = QPushButton("Import a profile file…")
        self.import_btn.setToolTip("Open a profile someone shared with you. Mods you don't have are downloaded.")
        self.import_btn.clicked.connect(self._import)
        row.addWidget(self.import_btn)
        root.addLayout(row)

        self.list = QListWidget()
        self.list.setStyleSheet(f"QListWidget::item {{ padding: 10px; border-bottom: 1px solid {theme.LINE}; }}")
        self.list.itemDoubleClicked.connect(lambda _i: self.load())
        self.list.currentItemChanged.connect(lambda *_: self._sync())
        root.addWidget(self.list, 1)

        self.empty = QLabel("No profiles yet.")
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignCenter)
        root.addWidget(self.empty, 1)

        actions = QHBoxLayout()
        self.load_btn = QPushButton("Switch to this profile")
        self.load_btn.setProperty("kind", "primary")
        self.load_btn.clicked.connect(self.load)
        self.dup_btn = QPushButton("Duplicate")
        self.dup_btn.setToolTip("A new profile with the same mods, order and on/off")
        self.dup_btn.clicked.connect(self.duplicate)
        self.rename_btn = QPushButton("Rename")
        self.rename_btn.clicked.connect(self.rename)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setProperty("kind", "danger")
        self.delete_btn.clicked.connect(self.delete)
        self.export_btn = QPushButton("Share as a file…")
        self.export_btn.setToolTip("Save this profile to a file you can send. Whoever opens it gets the same "
                                   "mods, order and variants; GameBanana mods download automatically.")
        self.export_btn.clicked.connect(self._export)
        for b in (self.load_btn, self.dup_btn, self.rename_btn, self.export_btn):
            actions.addWidget(b)
        actions.addStretch(1)
        actions.addWidget(self.delete_btn)
        root.addLayout(actions)
        self.reload()

    def reload(self):
        cur = self._current()
        self.list.clear()
        lib = self.mgr.lib
        profs = sorted(lib.profiles.values(), key=lambda p: p.name.lower())
        for prof in profs:
            if prof.name == lib.active_profile:
                mods = lib.visible()
                total, on = len(mods), sum(1 for m in mods if m.enabled)
            else:
                total, on = len(prof.entries), sum(1 for _, e in prof.entries if e)
            active = "   (in use)" if prof.name == lib.active_profile else ""
            item = QListWidgetItem(f"{prof.name}{active}\n{total} mod{'s' if total != 1 else ''}, {on} on")
            item.setData(Qt.UserRole, prof.name)
            self.list.addItem(item)
            if prof.name == cur:
                self.list.setCurrentItem(item)
        self.list.setVisible(bool(profs))
        self.empty.setVisible(not profs)
        self._sync()

    def _current(self) -> str | None:
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _sync(self):
        cur = self._current()
        has = cur is not None
        active = cur == self.mgr.lib.active_profile
        for b in (self.dup_btn, self.rename_btn, self.export_btn):
            b.setEnabled(has)
        self.load_btn.setEnabled(has and not active)
        self.delete_btn.setEnabled(has and not active)
        self.delete_btn.setToolTip("You're using this profile: switch to another one to delete it." if active
                                   else "Delete the profile. Its mods stay downloaded for other profiles.")

    def _export(self):
        from pathlib import Path
        from sapphire.ui.dialogs import error
        name = self._current()
        if not name:
            return
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip() or "profile"
        dest, _ = QFileDialog.getSaveFileName(self, "Share profile", str(Path.home() / f"{safe}.sapphire-profile"),
                                              "Sapphire profiles (*.sapphire-profile);;All files (*)")
        if not dest:
            return
        try:
            n = self.mgr.export_profile(name, dest)
        except Exception as exc:  # noqa: BLE001
            error(self, "Couldn't save the profile", str(exc))
            return
        local = sum(1 for uid, _ in self.mgr.lib.profiles[name].entries
                    if uid in self.mgr.lib.mods and self.mgr.lib.mods[uid].source != "gamebanana")
        note = (f" {local} of them were added from files, so whoever opens it needs those files too."
                if local else "")
        QMessageBox.information(self, "Profile saved",
                                f"Saved “{name}” ({n} mod{'s' if n != 1 else ''}) to {dest}.{note}")

    def _import(self):
        from pathlib import Path
        path, _ = QFileDialog.getOpenFileName(self, "Import a profile", str(Path.home() / "Downloads"),
                                              "Sapphire profiles (*.sapphire-profile *.json);;All files (*)")
        if path:
            self.import_requested.emit(Path(path))

    def new_profile(self):
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QRadioButton
        lib = self.mgr.lib
        dlg = QDialog(self)
        dlg.setWindowTitle("New profile")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Name:"))
        name = QLineEdit()
        lay.addWidget(name)
        empty = QRadioButton("Start empty (add mods from Browse, or ones you already have)")
        copy = QRadioButton(f"Start as a copy of “{lib.active_profile}”")
        empty.setChecked(True)
        lay.addWidget(empty)
        lay.addWidget(copy)
        switch = QCheckBox("Switch to it now")
        switch.setChecked(True)
        lay.addWidget(switch)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        lay.addWidget(box)
        if not dlg.exec() or not name.text().strip():
            return
        try:
            self.mgr.new_profile(name.text(), copy=copy.isChecked())
        except Exception as exc:  # noqa: BLE001
            error(self, "Couldn't make the profile", str(exc))
            return
        self._select(name.text().strip())
        if switch.isChecked():
            self.load()
        else:
            self.reload()

    def duplicate(self):
        name = self._current()
        if not name:
            return
        new = ask_text(self, "Duplicate profile", "Name for the copy:", f"{name} copy")
        if not new:
            return
        try:
            self.mgr.duplicate_profile(name, new)
        except Exception as exc:  # noqa: BLE001
            error(self, "Couldn't copy the profile", str(exc))
            return
        self._select(new.strip())
        self.reload()

    def _select(self, name: str):
        self.reload()
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == name:
                self.list.setCurrentRow(i)

    def load(self):
        name = self._current()
        if not name:
            return
        missing = self.mgr.load_profile(name)
        self.reload()
        self.changed.emit()
        if missing:
            error(self, "Some mods are gone",
                  f"{len(missing)} mod(s) in this profile were uninstalled, so they were skipped.")

    def rename(self):
        name = self._current()
        new = ask_text(self, "Rename profile", "New name:", name or "")
        if name and new and new != name:
            try:
                self.mgr.rename_profile(name, new)
            except Exception as exc:  # noqa: BLE001
                error(self, "Couldn't rename", str(exc))
            self.reload()

    def delete(self):
        name = self._current()
        if name and confirm(self, "Delete profile", f"Delete the profile “{name}”? Its mods stay downloaded "
                            "(other profiles keep theirs, and “Add downloaded mods…” can bring any back).",
                            "Delete", danger=True):
            try:
                self.mgr.delete_profile(name)
            except Exception as exc:  # noqa: BLE001
                error(self, "Couldn't delete it", str(exc))
            self.reload()


class SettingsPage(QWidget):
    game_dir_changed = Signal()
    apply_now = Signal()
    reset_requested = Signal()
    fix_gameinfo = Signal()
    setup_requested = Signal()
    import_requested = Signal(str)
    app_update_requested = Signal()
    patch_notes_requested = Signal()
    appearance_changed = Signal()
    clear_requested = Signal()
    discord_changed = Signal()

    def __init__(self, manager):
        super().__init__()
        self.mgr = manager
        # Everything lives in a scroll area so a short window scrolls instead of squashing
        # the sections into each other.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        root = QVBoxLayout(body)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(10)
        title = QLabel("Settings")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        root.addWidget(_section("Deadlock folder"))
        row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setReadOnly(True)
        row.addWidget(self.path, 1)
        browse = QPushButton("Choose…")
        browse.clicked.connect(self._choose)
        detect = QPushButton("Find automatically")
        detect.clicked.connect(self._detect)
        row.addWidget(browse)
        row.addWidget(detect)
        root.addLayout(row)
        self.path_hint = QLabel()
        self.path_hint.setObjectName("Muted")
        self.path_hint.setWordWrap(True)
        root.addWidget(self.path_hint)

        root.addWidget(_section("Behaviour"))
        self.auto_apply = QCheckBox("Apply changes to the game straight away")
        self.auto_apply.setChecked(manager.lib.settings.auto_apply)
        self.auto_apply.toggled.connect(self._auto_apply)
        root.addWidget(self.auto_apply)
        auto_hint = QLabel("When off, use “Apply changes” (or Launch) to push your changes into the game.")
        auto_hint.setObjectName("Muted")
        auto_hint.setWordWrap(True)
        root.addWidget(auto_hint)
        self.fix_camera = QCheckBox("Fix the first-person camera on skins made before the camera update")
        self.fix_camera.setChecked(manager.lib.settings.fix_camera)
        self.fix_camera.toggled.connect(self._fix_camera)
        root.addWidget(self.fix_camera)
        cam_hint = QLabel("A Deadlock update moved where the camera sits on every hero. Older skins still use "
                          "the old spot, so first person looks wrong. Sapphire corrects their camera points "
                          "into a separate file loaded in front of your mods; the mods themselves aren't changed.")
        cam_hint.setObjectName("Muted")
        cam_hint.setWordWrap(True)
        root.addWidget(cam_hint)
        self.auto_update = QCheckBox("Install mod updates automatically")
        self.auto_update.setToolTip("When Sapphire finds updates (at start and every few hours), it installs them "
                                    "straight away. You can still roll any of them back.")
        self.auto_update.setChecked(manager.lib.settings.auto_update)
        self.auto_update.toggled.connect(lambda on: self._flag("auto_update", on))
        root.addWidget(self.auto_update)
        self.one_skin = QCheckBox("One skin per hero")
        self.one_skin.setToolTip("Turning a skin on turns that hero's other skins off, so they never fight over "
                                 "the same model. Skins are matched to heroes by the models they replace.")
        self.one_skin.setChecked(manager.lib.settings.one_skin_per_hero)
        self.one_skin.toggled.connect(lambda on: self._flag("one_skin_per_hero", on))
        root.addWidget(self.one_skin)
        self.helper_box = QCheckBox("Keep mods working after game updates, even when Sapphire is closed")
        self.helper_box.setToolTip("Starts a tiny background helper when you log in. When a Deadlock update "
                                   "resets gameinfo.gi, it puts the mod folders back, so launching from Steam "
                                   "still loads your mods.")
        self.helper_box.setChecked(manager.lib.settings.helper)
        self.helper_box.toggled.connect(self._helper_toggled)
        root.addWidget(self.helper_box)

        root.addWidget(_section("Appearance"))
        ap = QHBoxLayout()
        ap.addWidget(QLabel("Size"))
        self.scale_box = QComboBox()
        for name in theme.SCALES:
            self.scale_box.addItem(name, name)
        self.scale_box.setCurrentText(manager.lib.settings.ui_scale if manager.lib.settings.ui_scale in theme.SCALES else "Normal")
        self.scale_box.currentTextChanged.connect(self._scale_changed)
        ap.addWidget(self.scale_box)
        ap.addSpacing(18)
        ap.addWidget(QLabel("Theme"))
        self.preset_box = QComboBox()
        for name in theme.PRESETS:
            self.preset_box.addItem(name, name)
        self.preset_box.setCurrentText(manager.lib.settings.theme_preset if manager.lib.settings.theme_preset in theme.PRESETS else theme.DEFAULT_PRESET)
        self.preset_box.currentTextChanged.connect(self._preset_changed)
        ap.addWidget(self.preset_box)
        self.reset_colors = QPushButton("Reset colours")
        self.reset_colors.setToolTip("Drop your custom colours and go back to the theme's own")
        self.reset_colors.clicked.connect(self._reset_colors)
        ap.addWidget(self.reset_colors)
        ap.addStretch(1)
        root.addLayout(ap)
        fonts = QHBoxLayout()
        self.font_boxes: dict[str, QComboBox] = {}
        for kind, label in (("text", "Text font"), ("titles", "Title font")):
            fonts.addWidget(QLabel(label))
            box = QComboBox()
            box.setMaxVisibleItems(18)
            box.setMinimumWidth(240)
            box.currentIndexChanged.connect(lambda _i, k=kind: self._font_changed(k))
            self.font_boxes[kind] = box
            fonts.addWidget(box)
            fonts.addSpacing(18)
        fonts.addStretch(1)
        root.addLayout(fonts)
        font_hint = QLabel("Each theme suggests fonts that suit it; any font that comes with Sapphire works with any theme.")
        font_hint.setObjectName("Muted")
        root.addWidget(font_hint)
        self._fill_font_boxes()
        swatch_hint = QLabel("Click a colour to change it. Changes apply straight away.")
        swatch_hint.setObjectName("Muted")
        root.addWidget(swatch_hint)
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        self.swatches: dict[str, QPushButton] = {}
        for i, (token, (label, what)) in enumerate(theme.TOKENS.items()):
            row, col = divmod(i, 4)
            btn = QPushButton()
            btn.setObjectName("Swatch")
            btn.setFixedSize(44, 24)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(f"{label}: {what}")
            btn.clicked.connect(lambda _c=False, t=token: self._pick_color(t))
            self.swatches[token] = btn
            cell = QHBoxLayout()
            cell.setSpacing(10)
            cell.addWidget(btn)
            lbl = QLabel(label)
            lbl.setObjectName("Muted")
            cell.addWidget(lbl)
            cell.addStretch(1)
            grid.addLayout(cell, row, col)
        root.addLayout(grid)
        self._refresh_swatches()

        root.addWidget(_section("Discord"))
        self.discord_on = QCheckBox("Show what I'm doing in Sapphire on my Discord profile")
        self.discord_on.setChecked(manager.lib.settings.discord_presence)
        self.discord_on.toggled.connect(self._discord_toggled)
        root.addWidget(self.discord_on)
        drow = QHBoxLayout()
        drow.addWidget(QLabel("Application ID"))
        self.discord_id = QLineEdit(manager.lib.settings.discord_app_id)
        self.discord_id.setPlaceholderText("e.g. 1234567890123456789")
        self.discord_id.setFixedWidth(260)
        self.discord_id.editingFinished.connect(self._discord_id_changed)
        drow.addWidget(self.discord_id)
        drow.addStretch(1)
        root.addLayout(drow)
        dhint = QLabel("Talks only to the Discord app on this computer; nothing is sent anywhere else. It needs a "
                       "Discord Application ID: at discord.com/developers/applications click New Application, call it "
                       "Sapphire, and copy its Application ID here. One ID can be shared by everyone who uses it.")
        dhint.setObjectName("Muted")
        dhint.setWordWrap(True)
        root.addWidget(dhint)

        root.addWidget(_section("Game files"))
        g = QHBoxLayout()
        fix = QPushButton("Re-check gameinfo.gi")
        fix.setToolTip("Re-adds the mod folders line if a game update removed it")
        fix.clicked.connect(self.fix_gameinfo)
        addons = QPushButton("Open addons folder")
        addons.clicked.connect(self._open_addons)
        reset = QPushButton("Turn everything off and restore the game")
        reset.setProperty("kind", "danger")
        reset.clicked.connect(self.reset_requested)
        clear = QPushButton("Clear all data")
        clear.setProperty("kind", "danger")
        clear.setToolTip("Delete every installed mod and profile from Sapphire and the game, for a fresh start. "
                         "Settings and the Deadlock folder are kept.")
        clear.clicked.connect(self.clear_requested)
        g.addWidget(fix)
        g.addWidget(addons)
        g.addStretch(1)
        root.addLayout(g)
        g2 = QHBoxLayout()
        g2.addWidget(reset)
        g2.addWidget(clear)
        g2.addStretch(1)
        root.addLayout(g2)

        root.addWidget(_section("Switching from another mod manager"))
        imp = QHBoxLayout()
        self.dmm_btn = QPushButton("Import from Deadlock Mod Manager…")
        self.dmm_btn.clicked.connect(lambda: self.import_requested.emit("dmm"))
        self.grim_btn = QPushButton("Import from Grimoire…")
        self.grim_btn.clicked.connect(lambda: self.import_requested.emit("grimoire"))
        imp.addWidget(self.dmm_btn)
        imp.addWidget(self.grim_btn)
        imp.addStretch(1)
        root.addLayout(imp)
        self.import_hint = QLabel()
        self.import_hint.setObjectName("Muted")
        self.import_hint.setWordWrap(True)
        root.addWidget(self.import_hint)

        root.addWidget(_section("Sapphire"))
        u = QHBoxLayout()
        self.version_label = QLabel(f"Version {__version__}")
        self.app_update_btn = QPushButton("Check for updates")
        self.app_update_btn.clicked.connect(self.app_update_requested)
        u.addWidget(self.version_label)
        u.addWidget(self.app_update_btn)
        notes = QPushButton("Patch notes")
        notes.setToolTip("What changed in this version. Choose there whether they open by themselves.")
        notes.clicked.connect(self.patch_notes_requested)
        u.addWidget(notes)
        u.addStretch(1)
        root.addLayout(u)
        self.update_hint = QLabel()
        self.update_hint.setObjectName("Muted")
        self.update_hint.setWordWrap(True)
        root.addWidget(self.update_hint)
        self.set_update_state(None)
        d = QHBoxLayout()
        setup = QPushButton("Run setup again")
        setup.clicked.connect(self.setup_requested)
        d.addWidget(setup)
        lib = QPushButton("Open mod library")
        lib.clicked.connect(lambda: steam.open_path(paths.library_dir()))
        logs = QPushButton("Open log file")
        logs.clicked.connect(lambda: steam.open_path(paths.log_file()))
        d.addWidget(lib)
        d.addWidget(logs)
        d.addStretch(1)
        root.addLayout(d)
        info = QLabel(f"Sapphire {__version__}. Mods are stored in {paths.library_dir()} and "
                      "linked into the game when you apply, so uninstalling the game never loses them.")
        info.setObjectName("Muted")
        info.setWordWrap(True)
        root.addWidget(info)
        root.addStretch(1)
        self.refresh()

    # ------------------------------------------------------------ appearance
    def _refresh_swatches(self):
        for token, btn in self.swatches.items():
            color = theme.current_tokens()[token]
            btn.setStyleSheet(f"#Swatch {{ background: {color}; }}")
        self.reset_colors.setVisible(bool(self.mgr.lib.settings.theme_colors))

    def _scale_changed(self, name):
        self.mgr.lib.settings.ui_scale = name
        self.mgr.lib.save()
        self.appearance_changed.emit()

    def _preset_changed(self, name):
        self.mgr.lib.settings.theme_preset = name
        self.mgr.lib.settings.theme_colors = {}
        self.mgr.lib.save()
        self.appearance_changed.emit()
        self._refresh_swatches()
        self._fill_font_boxes()     # suggestions depend on the theme

    _FONT_ATTR = {"text": "text_font", "titles": "title_font"}

    def _fill_font_boxes(self):
        from PySide6.QtGui import QFont, QStandardItemModel
        st = self.mgr.lib.settings
        preset = st.theme_preset if st.theme_preset in theme.PRESETS else theme.DEFAULT_PRESET
        for kind, box in self.font_boxes.items():
            current = getattr(st, self._FONT_ATTR[kind])
            rec = theme.recommended(kind, preset)
            box.blockSignals(True)
            box.clear()
            model = box.model()

            def header(text):
                box.addItem(text, None)
                if isinstance(model, QStandardItemModel):
                    item = model.item(box.count() - 1)
                    item.setEnabled(False)
                    f = QFont()
                    f.setBold(True)
                    item.setFont(f)

            def add(family, label=None):
                box.addItem(label or family, family)
                box.setItemData(box.count() - 1, QFont(family), Qt.FontRole)   # shown in its own font

            box.addItem(f"Theme's choice ({rec[0]})", "")
            header(f"Suggested for {preset}")
            for fam in rec:
                add(fam)
            others = [f for f in theme.BUNDLED_FONTS if f not in rec]
            header("Also included with Sapphire")
            for fam in others:
                add(fam)
            if current and box.findData(current) < 0:
                add(current)        # picked in 1.9.1 from the computer's fonts: keep showing it
            box.setCurrentIndex(max(0, box.findData(current)))
            box.blockSignals(False)

    def _font_changed(self, kind: str):
        box = self.font_boxes[kind]
        family = box.currentData()
        if family is None:          # a section heading
            return
        setattr(self.mgr.lib.settings, self._FONT_ATTR[kind], family)
        self.mgr.lib.save()
        self.appearance_changed.emit()

    def _reset_colors(self):
        self.mgr.lib.settings.theme_colors = {}
        self.mgr.lib.save()
        self.appearance_changed.emit()
        self._refresh_swatches()

    def _pick_color(self, token: str):
        label = theme.TOKENS[token][0]
        current = QColor(theme.current_tokens()[token])
        dlg = QColorDialog(current, self)
        dlg.setWindowTitle(f"{label} colour")
        dlg.setOption(QColorDialog.DontUseNativeDialog, True)
        preview_origin = dict(self.mgr.lib.settings.theme_colors)

        def live(c: QColor):
            if c.isValid():
                self.mgr.lib.settings.theme_colors = {**preview_origin, token: c.name()}
                self.appearance_changed.emit()
        dlg.currentColorChanged.connect(live)
        if dlg.exec() == QColorDialog.Accepted and dlg.selectedColor().isValid():
            self.mgr.lib.settings.theme_colors = {**preview_origin, token: dlg.selectedColor().name()}
        else:
            self.mgr.lib.settings.theme_colors = preview_origin
        self.mgr.lib.save()
        self.appearance_changed.emit()
        self._refresh_swatches()

    def _discord_toggled(self, on):
        self.mgr.lib.settings.discord_presence = on
        self.mgr.lib.save()
        self.discord_changed.emit()

    def _discord_id_changed(self):
        cid = "".join(ch for ch in self.discord_id.text() if ch.isdigit())
        self.discord_id.setText(cid)
        self.mgr.lib.settings.discord_app_id = cid
        self.mgr.lib.save()
        self.discord_changed.emit()

    def set_update_state(self, rel, installed=None):
        from sapphire.updater import REPO, running_from_source
        if installed:
            self.update_hint.setText(f"Version {installed.version} is installed and will be used after a restart.")
        elif running_from_source():
            self.update_hint.setText("Running from a source checkout, so updates come from git pull. "
                                     f"Source: github.com/{REPO}")
        elif rel:
            self.update_hint.setText(f"Version {rel.version} is available. Use the bar at the top to install it.")
        else:
            self.update_hint.setText(f"Updates are checked on start and every few hours from github.com/{REPO}. "
                                     "Installing one only touches Sapphire's own folder; mods and settings stay.")

    def refresh(self):
        gd = self.mgr.game_dir
        found = self.mgr.detect_other_managers()
        names = [n for k, n in (("dmm", "Deadlock Mod Manager"), ("grimoire", "Grimoire")) if found.get(k)]
        self.import_hint.setText(("Found data from " + " and ".join(names) + ". Importing copies the mods and "
                                  "profiles into Sapphire; nothing is deleted.") if names else
                                 "Brings over installed mods, their order and your profiles. Neither manager's "
                                 "data was found on this computer, but you can still try.")
        self.path.setText(str(gd) if gd else "")
        if gd:
            self.path_hint.setText("Found. Mods go into game/citadel/addons.")
        else:
            self.path_hint.setText("Not found. If Deadlock is installed, choose its folder "
                                   "(the one that contains the “game” folder).")

    def _choose(self):
        start = str(self.mgr.game_dir or Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Choose the Deadlock folder", start)
        if not folder:
            return
        try:
            self.mgr.set_game_dir(folder)
        except Exception as exc:  # noqa: BLE001
            error(self, "Not a Deadlock folder", str(exc))
            return
        self.refresh()
        self.game_dir_changed.emit()

    def _detect(self):
        found = steam.find_deadlock()
        if found:
            self.mgr.set_game_dir(found)
            self.refresh()
            self.game_dir_changed.emit()
        else:
            error(self, "Not found", "Couldn't find Deadlock in any Steam library (native, Flatpak or Snap). "
                  "Use Choose… to point at it.")

    helper_changed = Signal(bool)

    def _flag(self, name, on):
        setattr(self.mgr.lib.settings, name, on)
        self.mgr.lib.save()

    def _helper_toggled(self, on):
        self._flag("helper", on)
        self.helper_changed.emit(on)

    def _fix_camera(self, on):
        self.mgr.lib.settings.fix_camera = on
        self.mgr.lib.save()
        self.apply_now.emit()

    def _auto_apply(self, on):
        self.mgr.lib.settings.auto_apply = on
        self.mgr.lib.save()
        if on:
            self.apply_now.emit()

    def _open_addons(self):
        gd = self.mgr.game_dir
        if gd:
            path = gd / "game" / "citadel" / "addons"
            path.mkdir(exist_ok=True)
            steam.open_path(path)
