"""Profiles and Settings pages."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

from sapphire import __version__, paths, steam
from sapphire.ui import theme
from sapphire.ui.dialogs import ask_text, confirm, error


def _section(title: str) -> QLabel:
    lbl = QLabel(title)
    lbl.setObjectName("SideTitle")
    return lbl


class ProfilesPage(QWidget):
    changed = Signal()

    def __init__(self, manager):
        super().__init__()
        self.mgr = manager
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(10)
        title = QLabel("Profiles")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        hint = QLabel("A profile remembers which mods are on and their order. Switch between "
                      "setups (say, yours and your partner's) in one click.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        row = QHBoxLayout()
        self.save_btn = QPushButton("Save current setup as…")
        self.save_btn.setProperty("kind", "primary")
        self.save_btn.clicked.connect(self.save_new)
        row.addWidget(self.save_btn)
        row.addStretch(1)
        root.addLayout(row)

        self.list = QListWidget()
        self.list.setStyleSheet(f"QListWidget::item {{ padding: 10px; border-bottom: 1px solid {theme.LINE}; }}")
        self.list.itemDoubleClicked.connect(lambda _i: self.load())
        self.list.currentItemChanged.connect(lambda *_: self._sync())
        root.addWidget(self.list, 1)

        self.empty = QLabel("No profiles yet. Set up your mods the way you like, then save them here.")
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignCenter)
        root.addWidget(self.empty, 1)

        actions = QHBoxLayout()
        self.load_btn = QPushButton("Switch to this profile")
        self.load_btn.setProperty("kind", "primary")
        self.load_btn.clicked.connect(self.load)
        self.overwrite_btn = QPushButton("Save current setup into it")
        self.overwrite_btn.clicked.connect(self.overwrite)
        self.rename_btn = QPushButton("Rename")
        self.rename_btn.clicked.connect(self.rename)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setProperty("kind", "danger")
        self.delete_btn.clicked.connect(self.delete)
        for b in (self.load_btn, self.overwrite_btn, self.rename_btn):
            actions.addWidget(b)
        actions.addStretch(1)
        actions.addWidget(self.delete_btn)
        root.addLayout(actions)
        self.reload()

    def reload(self):
        cur = self._current()
        self.list.clear()
        profs = sorted(self.mgr.lib.profiles.values(), key=lambda p: p.name.lower())
        for prof in profs:
            on = sum(1 for _, e in prof.entries if e)
            saved = dt.datetime.fromtimestamp(prof.saved_at).strftime("%-d %b %Y, %H:%M") if prof.saved_at else ""
            active = "   (active)" if prof.name == self.mgr.lib.active_profile else ""
            item = QListWidgetItem(f"{prof.name}{active}\n{on} mods on    saved {saved}")
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
        has = self._current() is not None
        for b in (self.load_btn, self.overwrite_btn, self.rename_btn, self.delete_btn):
            b.setEnabled(has)

    def save_new(self):
        name = ask_text(self, "Save profile", "Profile name:")
        if not name:
            return
        if name in self.mgr.lib.profiles and not confirm(
                self, "Replace profile", f"“{name}” already exists. Replace it with the current setup?",
                "Replace"):
            return
        self.mgr.save_profile(name)
        self.reload()

    def overwrite(self):
        name = self._current()
        if name and confirm(self, "Update profile", f"Replace “{name}” with your current setup?", "Replace"):
            self.mgr.save_profile(name)
            self.reload()

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
        if name and confirm(self, "Delete profile", f"Delete the profile “{name}”? Your mods stay installed.",
                            "Delete", danger=True):
            self.mgr.delete_profile(name)
            self.reload()


class SettingsPage(QWidget):
    game_dir_changed = Signal()
    apply_now = Signal()
    reset_requested = Signal()
    fix_gameinfo = Signal()
    setup_requested = Signal()
    import_requested = Signal(str)

    def __init__(self, manager):
        super().__init__()
        self.mgr = manager
        root = QVBoxLayout(self)
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
        root.addWidget(auto_hint)

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
        g.addWidget(fix)
        g.addWidget(addons)
        g.addStretch(1)
        g.addWidget(reset)
        root.addLayout(g)

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
