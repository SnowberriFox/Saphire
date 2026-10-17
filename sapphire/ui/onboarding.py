"""First-run setup wizard.

Four steps, each one screen:
  1. Welcome and the third-party content notice (must acknowledge)
  2. Find Deadlock (auto-detect, with a manual fallback)
  3. Existing mods (adopt hand-installed VPKs and other managers' edits)
  4. GameBanana connection check
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from sapphire import APP_NAME, deploy, gameinfo, steam
from sapphire.ui import theme
from sapphire.ui.workers import run

STEPS = ("Welcome", "Find Deadlock", "Existing mods", "GameBanana")


class Stepper(QWidget):
    """Row of step names with the current one lit, like DMM's stepper."""

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.labels: list[QLabel] = []
        for i, name in enumerate(STEPS):
            if i:
                line = QFrame()
                line.setFixedHeight(1)
                line.setStyleSheet(f"background: {theme.LINE};")
                lay.addWidget(line, 1)
            lbl = QLabel(f"{i + 1}  {name}")
            lbl.setStyleSheet(f"background: transparent; color: {theme.MUTED}; padding: 0 10px;")
            lay.addWidget(lbl)
            self.labels.append(lbl)

    def set_current(self, index: int):
        for i, lbl in enumerate(self.labels):
            if i < index:
                color, weight = theme.VERDIGRIS, "normal"
            elif i == index:
                color, weight = theme.ACCENT_HI, "600"
            else:
                color, weight = theme.MUTED, "normal"
            lbl.setStyleSheet(f"background: transparent; color: {color}; font-weight: {weight}; padding: 0 10px;")


class Step(QWidget):
    ready_changed = Signal(bool)

    def __init__(self, title: str, blurb: str):
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(12)
        t = QLabel(title)
        t.setObjectName("PageTitle")
        b = QLabel(blurb)
        b.setObjectName("Muted")
        b.setWordWrap(True)
        self.lay.addWidget(t)
        self.lay.addWidget(b)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("Muted")
        self._ready = False

    def set_status(self, text: str, tone: str = "muted"):
        color = {"ok": theme.VERDIGRIS, "bad": "#E8A598", "muted": theme.MUTED}[tone]
        self.status.setStyleSheet(f"background: transparent; color: {color};")
        self.status.setText(text)

    def set_ready(self, ready: bool):
        self._ready = ready
        self.ready_changed.emit(ready)

    @property
    def ready(self) -> bool:
        return self._ready

    def enter(self):
        """Called each time the step is shown."""


class WelcomeStep(Step):
    def __init__(self):
        super().__init__(f"Welcome to {APP_NAME}",
                         f"{APP_NAME} browses GameBanana, installs Deadlock mods, keeps them in the order you "
                         "want and fixes the game's config after updates. This takes about a minute.")
        notice = QLabel("Mods are third-party content made by community members. They aren't made, "
                        f"checked or endorsed by {APP_NAME}. Only use cosmetic mods: Valve allows client-side "
                        "visual and audio mods, but anything that gives a gameplay advantage can get you banned.")
        notice.setWordWrap(True)
        notice.setObjectName("Banner")
        self.lay.addWidget(notice)
        self.ack = QCheckBox("I understand that mods are third-party content")
        self.ack.toggled.connect(self.set_ready)
        self.lay.addWidget(self.ack)
        self.lay.addStretch(1)


class GameStep(Step):
    def __init__(self, manager):
        super().__init__("Find Deadlock",
                         "Mods go into Deadlock's game folder, so Sapphire needs to know where it is. "
                         "It checks native, Flatpak and Snap Steam and every library drive.")
        self.mgr = manager
        self.path = QLabel()
        self.path.setWordWrap(True)
        self.path.setStyleSheet(f"background: {theme.RAISED}; border-radius: 5px; padding: 8px 10px;")
        self.lay.addWidget(self.path)
        self.lay.addWidget(self.status)
        row = QHBoxLayout()
        self.retry = QPushButton("Look again")
        self.retry.clicked.connect(self.detect)
        self.browse = QPushButton("Choose folder…")
        self.browse.clicked.connect(self.choose)
        row.addWidget(self.retry)
        row.addWidget(self.browse)
        row.addStretch(1)
        self.lay.addLayout(row)
        self.lay.addStretch(1)

    def enter(self):
        self.detect()

    def detect(self):
        found = self.mgr.game_dir
        if found:
            self.path.setText(str(found))
            self.set_status("Found it. Mods will go into game/citadel/addons.", "ok")
            self.set_ready(True)
        else:
            self.path.setText("Not found")
            self.set_status("Couldn't find Deadlock in any Steam library. If it's installed, choose its folder: "
                            "Steam › Deadlock › Manage › Browse local files shows where it is.", "bad")
            self.set_ready(False)

    def choose(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose the Deadlock folder",
                                                  str(self.mgr.game_dir or Path.home()))
        if not folder:
            return
        try:
            self.mgr.set_game_dir(folder)
        except Exception as exc:  # noqa: BLE001
            self.set_status(str(exc), "bad")
            return
        self.detect()


class ExistingStep(Step):
    import_requested = Signal(str)

    def __init__(self, manager):
        super().__init__("Existing mods",
                         "If you've installed mods by hand or with another manager, Sapphire can take them "
                         "over so nothing gets lost.")
        self.mgr = manager
        self.found_label = QLabel()
        self.found_label.setWordWrap(True)
        self.lay.addWidget(self.found_label)
        self.lay.addWidget(self.status)
        row = QHBoxLayout()
        self.import_btn = QPushButton("Import them")
        self.import_btn.setProperty("kind", "primary")
        self.import_btn.clicked.connect(self.do_import)
        self.skip_btn = QPushButton("Leave them")
        self.skip_btn.setToolTip("They're adopted automatically the first time you apply mods anyway")
        self.skip_btn.clicked.connect(lambda: self.set_ready(True))
        row.addWidget(self.import_btn)
        row.addWidget(self.skip_btn)
        row.addStretch(1)
        self.lay.addLayout(row)
        self.other_label = QLabel()
        self.other_label.setWordWrap(True)
        self.lay.addWidget(self.other_label)
        orow = QHBoxLayout()
        self.dmm_btn = QPushButton("Import from Deadlock Mod Manager…")
        self.dmm_btn.clicked.connect(lambda: self.import_requested.emit("dmm"))
        self.grim_btn = QPushButton("Import from Grimoire…")
        self.grim_btn.clicked.connect(lambda: self.import_requested.emit("grimoire"))
        orow.addWidget(self.dmm_btn)
        orow.addWidget(self.grim_btn)
        orow.addStretch(1)
        self.lay.addLayout(orow)
        self.lay.addStretch(1)
        self.paks: list[Path] = []

    def enter(self):
        self.set_ready(False)
        self.paks = []
        foreign = False
        try:
            citadel = self.mgr.citadel()
            self.paks = deploy.unmanaged_paks(citadel, self.mgr.lib.deployed)
            foreign = gameinfo.inspect(gameinfo.read(self.mgr.game_dir)).foreign
        except Exception as exc:  # noqa: BLE001
            self.set_status(f"Couldn't scan the game folder: {exc}", "bad")
        lines = []
        if self.paks:
            lines.append(f"Found {len(self.paks)} mod file{'s' if len(self.paks) != 1 else ''} in the addons folder:")
            lines += [f"    {p.parent.name}/{p.name}" for p in self.paks[:12]]
            if len(self.paks) > 12:
                lines.append(f"    … and {len(self.paks) - 12} more")
        if foreign:
            lines.append("gameinfo.gi was edited by another mod manager (or by hand). Sapphire will tidy "
                         "that up when it applies mods; your mods keep working.")
        found = self.mgr.detect_other_managers()
        others = [n for k, n in (("dmm", "Deadlock Mod Manager"), ("grimoire", "Grimoire")) if found.get(k)]
        if others:
            self.other_label.setText("Also found " + " and ".join(others) + " on this computer. You can bring "
                                     "over its mods, load order and profiles now, or later from Settings.")
        else:
            self.other_label.setText("")
        self.dmm_btn.setVisible(bool(found.get("dmm")))
        self.grim_btn.setVisible(bool(found.get("grimoire")))
        if not lines:
            lines.append("No existing mods found. You're starting fresh." if not others else "")
            self.set_ready(True)
        if others and not self.paks:
            self.set_ready(True)
        self.found_label.setText("\n".join(l for l in lines if l))
        has = bool(self.paks)
        self.import_btn.setVisible(has)
        self.skip_btn.setVisible(has)
        self.set_status("")

    def do_import(self):
        self.import_btn.setEnabled(False)
        self.set_status("Importing…")

        def done(mods):
            self.set_status(f"Imported {len(mods)} mod{'s' if len(mods) != 1 else ''}. They show up in Installed "
                            "as “Manual install”; rename them whatever you like.", "ok")
            self.import_btn.hide()
            self.skip_btn.hide()
            self.set_ready(True)

        def failed(exc):
            self.set_status(f"Import failed: {exc}", "bad")
            self.import_btn.setEnabled(True)

        run(self.mgr.import_unmanaged, on_done=done, on_error=failed)


class ConnectionStep(Step):
    def __init__(self, manager):
        super().__init__("GameBanana",
                         "Mods come straight from gamebanana.com, no account needed. Checking it's reachable.")
        self.mgr = manager
        self.lay.addWidget(self.status)
        self.retry = QPushButton("Try again")
        self.retry.clicked.connect(self.check)
        self.retry.hide()
        self.lay.addWidget(self.retry, 0, Qt.AlignLeft)
        self.lay.addStretch(1)
        self._checking = False

    def enter(self):
        if not self.ready:
            self.check()

    def check(self):
        if self._checking:
            return
        self._checking = True
        self.retry.hide()
        self.set_status("Connecting…")

        def done(cats):
            self._checking = False
            n = sum(c.count for c in cats)
            self.set_status(f"Connected. {n:,} Deadlock mods in {len(cats)} categories are ready to browse.", "ok")
            self.set_ready(True)

        def failed(exc):
            self._checking = False
            self.set_status(f"Couldn't reach GameBanana: {exc}\nYou can finish setup anyway and browse once "
                            "you're online.", "bad")
            self.retry.show()
            self.set_ready(True)  # don't trap people offline

        run(self.mgr.gb.categories, "Mod", on_done=done, on_error=failed)


class OnboardingDialog(QDialog):
    import_requested = Signal(str)

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self.setWindowTitle(f"Set up {APP_NAME}")
        self.setModal(True)
        self.setMinimumSize(680, 520)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(18)

        head = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(QPixmap(str(theme.ASSETS / "sapphire.svg")).scaled(40, 40, Qt.KeepAspectRatio,
                                                                           Qt.SmoothTransformation))
        mark = QLabel(APP_NAME)
        mark.setObjectName("Wordmark")
        head.addWidget(icon)
        head.addSpacing(8)
        head.addWidget(mark)
        head.addStretch(1)
        self.counter = QLabel()
        self.counter.setObjectName("Muted")
        head.addWidget(self.counter)
        root.addLayout(head)
        self.stepper = Stepper()
        root.addWidget(self.stepper)

        self.stack = QStackedWidget()
        self.steps: list[Step] = [WelcomeStep(), GameStep(manager), ExistingStep(manager), ConnectionStep(manager)]
        for s in self.steps:
            self.stack.addWidget(s)
            s.ready_changed.connect(lambda _r: self._sync())
        self.steps[2].import_requested.connect(self._import)
        root.addWidget(self.stack, 1)

        nav = QHBoxLayout()
        self.skip = QPushButton("Skip setup")
        self.skip.setToolTip("You can run this again from Settings")
        self.skip.clicked.connect(self.reject)
        self.back = QPushButton("Back")
        self.back.clicked.connect(lambda: self.goto(self.index - 1))
        self.next = QPushButton("Next")
        self.next.setProperty("kind", "primary")
        self.next.clicked.connect(self._next)
        nav.addWidget(self.skip)
        nav.addStretch(1)
        nav.addWidget(self.back)
        nav.addWidget(self.next)
        root.addLayout(nav)
        self.index = 0
        self.goto(0)

    def goto(self, i: int):
        self.index = max(0, min(i, len(self.steps) - 1))
        self.stack.setCurrentIndex(self.index)
        self.stepper.set_current(self.index)
        self.counter.setText(f"Step {self.index + 1} of {len(self.steps)}")
        self.steps[self.index].enter()
        self._sync()

    def _sync(self):
        last = self.index == len(self.steps) - 1
        self.back.setEnabled(self.index > 0)
        self.next.setText("Finish" if last else "Next")
        self.next.setEnabled(self.steps[self.index].ready)
        self.skip.setVisible(not last)

    def _import(self, which: str):
        # The main window runs the import (it owns the job queue); come back to this step after.
        self.import_requested.emit(which)
        self.steps[2].set_ready(True)

    def _next(self):
        if self.index == len(self.steps) - 1:
            self.accept()
        else:
            self.goto(self.index + 1)
