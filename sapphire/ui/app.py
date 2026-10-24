"""Main window and app start-up."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, Qt, QTimer
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QFileDialog, QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QProgressBar, QPushButton, QStackedWidget, QStatusBar,
                               QVBoxLayout, QWidget)

from sapphire import APP_ID, APP_NAME, __version__, paths, steam
from sapphire.core import GameRunning, Manager, NoGame
from sapphire.gamebanana import Cancelled
from sapphire.ui import theme
from sapphire.ui.browse import BrowsePage
from sapphire.ui.audio import PreviewPlayer
from sapphire.ui.dialogs import ask_text, choose_file, choose_variants, confirm, error
from sapphire.ui.downloads import DownloadsPage, Job, JobList
from sapphire.ui.images import ImageCache
from sapphire.ui.importing import ImportDialog
from sapphire.ui.installed import InstalledPage
from sapphire.discord import Presence
from sapphire.ui.onboarding import OnboardingDialog
from sapphire.ui.pages import ProfilesPage, SettingsPage
from sapphire.updater import Updater, UpdateError, restart, running_from_source
from sapphire.ui.workers import JOB_POOL, NET_POOL, MainThreadCaller, run

log = logging.getLogger("sapphire")
MOD_FILE_TYPES = (".zip", ".7z", ".rar", ".vpk")
PRESENCE_IMAGE = "https://raw.githubusercontent.com/SnowberriFox/Saphire/main/sapphire/assets/sapphire-512.png"
PRESENCE_URL = "https://github.com/SnowberriFox/Saphire"


class MainWindow(QMainWindow):
    def __init__(self, manager: Manager):
        super().__init__()
        self.mgr = manager
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 860)
        self.setMinimumSize(1020, 640)
        self.setAcceptDrops(True)
        self.caller = MainThreadCaller()
        self.images = ImageCache(manager.gb.session)
        self.updater = Updater(manager.gb.session)
        self.jobs = JobList()
        self.jobs.changed.connect(self._jobs_ui)
        self.presence = Presence(manager.lib.settings.discord_app_id if manager.lib.settings.discord_presence else "")
        self.running = False
        self._applying = False
        self._apply_again = False

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._header())

        self.banner = QLabel()
        self.banner.setObjectName("Banner")
        self.banner.setWordWrap(True)
        self.banner.hide()
        banner_wrap = QWidget()
        bl = QVBoxLayout(banner_wrap)
        bl.setContentsMargins(16, 8, 16, 0)
        bl.addWidget(self.banner)
        self.banner_wrap = banner_wrap
        banner_wrap.hide()
        outer.addWidget(banner_wrap)

        self.update_bar = QWidget()
        self.update_bar.setObjectName("UpdateBar")
        ub = QHBoxLayout(self.update_bar)
        ub.setContentsMargins(16, 8, 16, 0)
        self.update_frame = QWidget()
        self.update_frame.setObjectName("Banner")
        uf = QHBoxLayout(self.update_frame)
        uf.setContentsMargins(12, 6, 8, 6)
        self.update_label = QLabel()
        self.update_label.setStyleSheet("background: transparent;")
        self.update_notes = QPushButton("What's new")
        self.update_notes.setFlat(True)
        self.update_notes.setStyleSheet("QPushButton { background: transparent; border: none; text-decoration: underline; padding: 2px 6px; }")
        self.update_go = QPushButton("Update now")
        self.update_go.setProperty("kind", "primary")
        self.update_go.clicked.connect(self.install_app_update)
        self.update_later = QPushButton("Later")
        self.update_later.clicked.connect(self.update_bar.hide)
        uf.addWidget(self.update_label, 1)
        uf.addWidget(self.update_notes)
        uf.addWidget(self.update_go)
        uf.addWidget(self.update_later)
        ub.addWidget(self.update_frame)
        self.update_bar.hide()
        outer.addWidget(self.update_bar)

        self.stack = QStackedWidget()
        self.browse = BrowsePage(manager, self.images)
        self.installed = InstalledPage(manager, self.images)
        self.installed.busy = lambda uid: self.jobs.active_for(f"mod:{uid}") is not None
        self.profiles = ProfilesPage(manager)
        self.downloads = DownloadsPage(self.jobs)
        self.settings = SettingsPage(manager)
        for page in (self.browse, self.installed, self.profiles, self.downloads, self.settings):
            self.stack.addWidget(page)
        outer.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self._status_bar()

        # wiring
        self.browse.install_requested.connect(self.install_gb)
        self.browse.status.connect(self.say)
        self.installed.changed.connect(self.request_apply)
        self.installed.update_requested.connect(self.update_mod)
        self.installed.update_all_requested.connect(self.update_all)
        self.installed.check_updates_requested.connect(lambda: self.check_updates(manual=True))
        self.installed.add_file_requested.connect(self.add_files)
        self.installed.identify_requested.connect(self.identify)
        self.installed.removed.connect(lambda _u: self._library_changed())
        self.profiles.changed.connect(self._profile_switched)
        self.settings.game_dir_changed.connect(self._game_dir_changed)
        self.settings.apply_now.connect(self.request_apply)
        self.settings.fix_gameinfo.connect(lambda: self.check_gameinfo(manual=True))
        self.settings.reset_requested.connect(self.reset_vanilla)
        self.settings.clear_requested.connect(self.clear_all)
        self.settings.setup_requested.connect(self.run_setup)
        self.settings.import_requested.connect(self.import_from)
        self.settings.app_update_requested.connect(lambda: self.check_app_update(manual=True))
        self.settings.appearance_changed.connect(self.apply_appearance)
        self.settings.discord_changed.connect(self.update_presence)
        self.installed.reapply_requested.connect(self.reapply)
        self.installed.refetch_requested.connect(self.refetch_mod)
        self.installed.rollback_requested.connect(self.roll_back)
        self.installed.status.connect(self.say)
        self.browse.collection_requested.connect(self.open_collection)
        self.profiles.import_requested.connect(self.import_profile_file)
        self.settings.helper_changed.connect(self.set_helper)
        self.player = PreviewPlayer(manager.gb.session)
        self.browse.detail.player = self.player
        self.installed.player = self.player

        self._apply_timer = QTimer(self, singleShot=True, interval=600)
        self._apply_timer.timeout.connect(self.apply_now)
        self._poll = QTimer(self, interval=3000)
        self._poll.timeout.connect(self._tick)
        self._poll.start()
        self._ticks = 0
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(lambda _p: QTimer.singleShot(3000, self.check_gameinfo))
        self._watch_gameinfo()

        self.installed.reload()
        self._refresh_nav()
        QTimer.singleShot(0, self._startup)

    # -------------------------------------------------------------- layout
    def _header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("Header")
        lay = QHBoxLayout(header)
        lay.setContentsMargins(18, 10, 18, 10)
        lay.setSpacing(6)
        mark = QLabel("Sapphire")
        mark.setObjectName("Wordmark")
        lay.addWidget(mark)
        lay.addSpacing(18)
        self.nav = QButtonGroup(self)
        self.nav_buttons = []
        for i, label in enumerate(("Browse", "Installed", "Profiles", "Downloads", "Settings")):
            b = QPushButton(label)
            b.setObjectName("NavButton")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.nav.addButton(b, i)
            self.nav_buttons.append(b)
            lay.addWidget(b)
        self.nav.idClicked.connect(self.go)
        lay.addStretch(1)
        self.pill = QLabel()
        self.pill.setObjectName("StatusPill")
        lay.addWidget(self.pill)
        lay.addSpacing(6)
        self.apply_btn = QPushButton("Apply changes")
        self.apply_btn.clicked.connect(self.apply_now)
        self.apply_btn.hide()
        lay.addWidget(self.apply_btn)
        self.launch_btn = QPushButton("Launch Deadlock")
        self.launch_btn.setObjectName("LaunchButton")
        self.launch_btn.setCursor(Qt.PointingHandCursor)
        self.launch_btn.setToolTip("Applies your mods, re-checks gameinfo.gi, then starts Deadlock through Steam")
        self.launch_btn.clicked.connect(self.launch)
        lay.addWidget(self.launch_btn)
        return header

    def _status_bar(self):
        bar = QStatusBar()
        self.setStatusBar(bar)
        self.msg = QLabel("")
        bar.addWidget(self.msg, 1)
        self.job_label = QLabel()
        self.job_bar = QProgressBar()
        self.job_bar.setFixedWidth(180)
        self.job_bar.setFixedHeight(6)
        self.job_cancel = QPushButton("Cancel")
        self.job_cancel.clicked.connect(self._cancel_jobs)
        for w in (self.job_label, self.job_bar, self.job_cancel):
            bar.addPermanentWidget(w)
            w.hide()

    def go(self, index: int):
        self.stack.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
        if index == 0:
            self.browse.start()
        elif index == 2:
            self.profiles.reload()
        elif index == 4:
            self.settings.refresh()
        self.update_presence()

    def say(self, text: str, ms: int = 8000):
        self.msg.setText(text)
        if ms:
            QTimer.singleShot(ms, lambda t=text: self.msg.text() == t and self.msg.setText(""))

    def _show_banner(self, text: str | None, bad: bool = False):
        if not text:
            self.banner_wrap.hide()
            return
        self.banner.setObjectName("BannerBad" if bad else "Banner")
        self.banner.style().unpolish(self.banner)
        self.banner.style().polish(self.banner)
        self.banner.setText(text)
        self.banner_wrap.show()

    # -------------------------------------------------------------- state
    def _refresh_nav(self):
        mods = self.mgr.lib.ordered()
        on = sum(1 for m in mods if m.enabled)
        updates = sum(1 for m in mods if m.update)
        self.nav_buttons[1].setText(f"Installed  {len(mods)}" + (f"  ({updates} updates)" if updates else ""))
        active = len(self.jobs.active())
        self.nav_buttons[3].setText(f"Downloads  {active}" if active else "Downloads")
        gd = self.mgr.lib.game_dir and steam.is_valid_game_dir(self.mgr.lib.game_dir)
        if not gd:
            state, text = "bad", "Deadlock not found"
        elif self.running:
            state, text = "warn", "Deadlock is running"
        elif self._applying:
            state, text = "warn", "Applying…"
        elif self.mgr.pending:
            state, text = "warn", "Changes not applied yet"
        else:
            state, text = "ok", f"{on} mod{'s' if on != 1 else ''} active" if on else "No mods on"
        self.pill.setText(text)
        self.pill.setProperty("state", state)
        self.pill.style().unpolish(self.pill)
        self.pill.style().polish(self.pill)
        self.apply_btn.setVisible(bool(gd) and self.mgr.pending and not self._applying
                                  and (not self.mgr.lib.settings.auto_apply or self.running))
        self.apply_btn.setEnabled(not self.running)
        self.launch_btn.setEnabled(bool(gd) and not self.running)
        self.launch_btn.setText("Deadlock is running" if self.running else "Launch Deadlock")
        if self.running and self.mgr.pending:
            self._show_banner("Deadlock is running, so your changes will be applied as soon as you close it.")
        elif not gd:
            self._show_banner("Sapphire couldn't find Deadlock. Go to Settings and choose its folder.", bad=True)
        else:
            self._show_banner(None)

    def _library_changed(self):
        self.installed.reload()
        self.browse.library_changed()
        self._refresh_nav()
        self.update_presence()

    def update_presence(self):
        st = self.mgr.lib.settings
        if not st.discord_presence or not st.discord_app_id.strip():
            self.presence.clear()
            self.presence.set_client_id("")
            return
        self.presence.set_client_id(st.discord_app_id)
        self.presence.start()
        mods = self.mgr.lib.ordered()
        on = sum(1 for m in mods if m.enabled)
        page = self.stack.currentIndex()
        if self.running:
            details = "In Deadlock"
        else:
            details = {0: "Browsing mods", 1: "Managing mods", 2: "Switching profiles",
                       3: "Downloading mods", 4: "In settings"}.get(page, "Managing mods")
        state = f"{on} mod{'s' if on != 1 else ''} active" + (f" · {len(mods)} installed" if len(mods) != on else "")
        self.presence.update(details, state, large_image=PRESENCE_IMAGE, large_text="Sapphire for Deadlock",
                             buttons=[{"label": "Get Sapphire", "url": PRESENCE_URL}])

    def _tick(self):
        was = self.running
        self.running = steam.is_game_running()
        self._ticks += 1
        if was != self.running:
            self.update_presence()
        if was and not self.running:
            self.say("Deadlock closed.")
            QTimer.singleShot(1500, self._after_game_closed)
        if self._ticks % 5 == 0 and not self.running:
            self.check_gameinfo()
        self._refresh_nav()

    def _after_game_closed(self):
        if self.mgr.pending and self.mgr.lib.settings.auto_apply:
            self.apply_now()

    def _watch_gameinfo(self):
        gd = self.mgr.lib.game_dir
        if self.watcher.files():
            self.watcher.removePaths(self.watcher.files())
        if gd:
            p = Path(gd) / "game" / "citadel" / "gameinfo.gi"
            if p.exists():
                self.watcher.addPath(str(p))

    # -------------------------------------------------------------- start-up
    def _startup(self):
        if self.mgr.lib.settings.helper:
            from sapphire import helper
            try:
                if not helper.is_enabled():
                    helper.enable(start_now=False)   # e.g. after a reinstall
                if not helper.helper_running():
                    helper.start()
            except OSError as exc:
                log.warning("helper: %s", exc)
        if not self.mgr.lib.settings.onboarded:
            self.run_setup(first=True)
            return
        self._start_pages()

    def run_setup(self, first: bool = False):
        dlg = OnboardingDialog(self.mgr, self)
        dlg.import_requested.connect(self.import_from)
        finished = dlg.exec() == QDialog.Accepted
        if finished or first:
            # Skipping the first run still counts: nobody wants the wizard every launch.
            self.mgr.lib.settings.onboarded = True
            self.mgr.lib.save()
        self._watch_gameinfo()
        self._start_pages()
        if finished:
            self.say("Setup finished.")

    def _start_pages(self):
        if not self.mgr.game_dir:
            self.go(4)
            self._refresh_nav()
        else:
            self.go(0 if not self.mgr.lib.mods else 1)
            self.browse.start()
            # Self-heal on every start: re-sync files and gameinfo.gi (cheap when nothing changed).
            self.mgr._dirty = True
            self.apply_now(quiet=True)
        if any(m.source == "gamebanana" for m in self.mgr.lib.mods.values()):
            QTimer.singleShot(1500, self.check_updates)
        QTimer.singleShot(4000, self.check_app_update)
        self._app_update_timer = QTimer(self, interval=6 * 3600 * 1000)
        self._app_update_timer.timeout.connect(self.check_app_update)
        self._app_update_timer.start()

    def _game_dir_changed(self):
        self._watch_gameinfo()
        self.mgr._dirty = True
        self.apply_now()
        self._refresh_nav()

    # -------------------------------------------------------------- apply
    def request_apply(self):
        self._refresh_nav()
        if self.mgr.lib.settings.auto_apply:
            self._apply_timer.start()

    def apply_now(self, quiet: bool = False, force: bool = False):
        if not self.mgr.lib.game_dir:
            return
        if self._applying:
            self._apply_again = True
            return
        self._applying = True
        self._refresh_nav()

        def done(result):
            self._applying = False
            n = len(self.mgr.lib.enabled_in_order())
            if force:
                self.say(f"Reapplied: {result.written} file{'s' if result.written != 1 else ''} rewritten, "
                         f"{n} mod{'s' if n != 1 else ''} on, gameinfo.gi checked.", 12000)
            elif not quiet:
                fixed = sum(1 for rep in self.mgr.camera_report.values() if any(r.status == "fixed" for r in rep))
                self.say(f"Applied. {n} mod{'s' if n != 1 else ''} on."
                         + (f" ({result.written} files written)" if result.written else "")
                         + (f" Camera fixed on {fixed} older skin{'s' if fixed != 1 else ''}." if fixed else ""))
            self._after_apply()

        def failed(exc):
            self._applying = False
            if isinstance(exc, GameRunning):
                self.running = True
            elif isinstance(exc, NoGame):
                self.go(4)
            else:
                error(self, "Couldn't apply mods", str(exc))
            self._after_apply()

        run(self.mgr.apply, force, on_done=done, on_error=failed, pool=JOB_POOL)

    def _after_apply(self):
        self._refresh_nav()
        self._watch_gameinfo()
        self.installed.reload()
        run(self.mgr.conflicts, on_done=self.installed.set_conflicts,
            on_error=lambda e: log.warning("conflict scan failed: %s", e))
        if self._apply_again:
            self._apply_again = False
            self.apply_now(quiet=True)

    def reapply(self):
        if self.running:
            self.say("Deadlock is running. Close it first, then Reapply.")
            return
        self.say("Reapplying every mod…")
        self.apply_now(force=True)

    def apply_appearance(self):
        st = self.mgr.lib.settings
        theme.apply(QApplication.instance(), st.theme_preset, st.theme_colors, theme.SCALES.get(st.ui_scale, 1.0))
        for page in (self.browse, self.installed):
            page.rescale()
        self._refresh_nav()

    def check_gameinfo(self, manual: bool = False):
        self._watch_gameinfo()  # the file is replaced on update, so re-watch
        if self.running or self._applying or not self.mgr.lib.game_dir:
            return

        def done(fixed):
            self._watch_gameinfo()
            if fixed:
                self.say("A Deadlock update reset gameinfo.gi, so Sapphire put the mod folders back.", 15000)
            elif manual:
                self.say("gameinfo.gi is set up correctly.")

        def failed(exc):
            log.error("gameinfo check failed: %s", exc)
            if manual:
                error(self, "gameinfo.gi problem", str(exc))

        run(self.mgr.ensure_gameinfo, on_done=done, on_error=failed, pool=JOB_POOL)

    def reset_vanilla(self):
        if not confirm(self, "Restore the game",
                       "Turn every mod off and remove Sapphire's changes from the game folder? "
                       "Your mods stay in the library, so you can turn them back on later.",
                       "Turn off and restore", danger=True):
            return
        try:
            self.mgr.reset_to_vanilla()
        except Exception as exc:  # noqa: BLE001
            error(self, "Couldn't restore", str(exc))
            return
        self._library_changed()
        self.say("Game restored. All mods are off.")

    def clear_all(self):
        n = len(self.mgr.lib.mods)
        if not confirm(self, "Clear all data",
                       f"Delete all {n} installed mod{'s' if n != 1 else ''} and every profile from Sapphire and "
                       "from the game? This can't be undone. You can re-add mods from Browse afterwards. "
                       "Settings and your Deadlock folder are kept.",
                       "Delete everything", danger=True):
            return
        try:
            self.mgr.clear_all_data()
        except Exception as exc:  # noqa: BLE001
            error(self, "Couldn't clear data", str(exc))
            return
        self._library_changed()
        self.profiles.reload()
        self.say("All mods and profiles removed. Fresh start.")

    def launch(self):
        self.launch_btn.setEnabled(False)
        self.launch_btn.setText("Starting…")

        def failed(exc):
            if isinstance(exc, GameRunning):
                self.running = True
            else:
                error(self, "Couldn't launch", str(exc))
            self._refresh_nav()

        def done(_):
            self.say("Asked Steam to start Deadlock.")
            QTimer.singleShot(4000, self._refresh_nav)

        run(self.mgr.launch, on_done=done, on_error=failed, pool=JOB_POOL)

    def _profile_switched(self):
        self._library_changed()
        self.request_apply()
        if not self.mgr.lib.settings.auto_apply:
            self.say("Profile loaded. Apply changes to use it in game.")

    # -------------------------------------------------------------- jobs
    def _jobs_ui(self):
        self.installed.jobs_changed()
        active = self.jobs.active()
        running = self.jobs.running()
        visible = bool(active)
        for w in (self.job_label, self.job_bar, self.job_cancel):
            w.setVisible(visible)
        self._refresh_nav()
        if not visible:
            return
        job = running or active[-1]
        extra = f"  (+{len(active) - 1} queued)" if len(active) > 1 else ""
        self.job_label.setText(f"{job.stage or 'Waiting'}: {job.label}{extra}")
        if job.total:
            self.job_bar.setRange(0, 1000)
            self.job_bar.setValue(int(job.done / job.total * 1000))
        else:
            self.job_bar.setRange(0, 0)

    def _cancel_jobs(self):
        for job in self.jobs.active():
            job.cancel.set()
            if job.state == "queued":
                self.jobs.update(job, state="cancelled")

    def _chooser(self, sets, name):
        return self.caller.call(choose_variants, self, sets, name)

    def _queue(self, label: str, fn, *args, success: str = "", kind: str = "install", silent: bool = False,
               key: str = "", after=None):
        # One active job per thing: clicking Update all (or Install) again while it's
        # still queued or running must not line the same download up a second time.
        busy = self.jobs.active_for(key)
        if busy is not None:
            return busy
        job = Job(label, kind=kind, key=key)
        job.retry = lambda: self._queue(label, fn, *args, success=success, kind=kind, silent=silent, key=key,
                                        after=after)
        self.jobs.add(job)

        def progress(stage, done, total):
            self.jobs.update(job, state="running", stage=stage, done=done, total=total)

        def worker(progress=None):
            if job.cancel.is_set():
                raise Cancelled()
            self.jobs.update(job, state="running", stage="Starting")
            return fn(*args, choose=self._chooser, progress=progress, cancel=job.cancel)

        def done(result):
            self.jobs.update(job, state="done", stage="Done")
            if not silent:
                self.say(success.format(name=getattr(result, "name", label)))
            self._library_changed()
            self.request_apply()
            if after is not None:
                after(result)

        def failed(exc):
            if isinstance(exc, Cancelled) or job.cancel.is_set():
                self.jobs.update(job, state="cancelled")
                self.say(f"Cancelled: {label}")
                return
            self.jobs.update(job, state="failed", error=str(exc))
            self.say(f"Failed: {label}. See Downloads.", 12000)

        run(worker, on_done=done, on_error=failed, on_progress=progress, pool=JOB_POOL)
        return job

    def install_gb(self, model: str, gb_id: int, file=None, add: bool = False):
        existing = self.mgr.lib.by_gb(model, gb_id)
        label = existing.name if existing else f"GameBanana {model.lower()} {gb_id}"
        if file is not None:
            label = file.filename

        def do(model, gb_id, file, add, choose=None, progress=None, cancel=None):
            return self.mgr.install_gamebanana(model, gb_id, file, choose=choose,
                                               progress=progress, cancel=cancel, add=add)
        fid = file.id if file is not None else "newest"
        self._queue(label, do, model, gb_id, file, add,
                    success="Installed {name}.", key=f"gb:{model}:{gb_id}:{fid}:{int(add)}")

    def update_mod(self, uid: str):
        mod = self.mgr.lib.mods.get(uid)
        if not mod:
            return

        def do(uid, choose=None, progress=None, cancel=None):
            return self.mgr.update(uid, choose=choose, progress=progress, cancel=cancel)
        self._queue(mod.name, do, uid, success="Updated {name}.", kind="update", key=f"mod:{uid}")

    def refetch_mod(self, uid: str):
        """Other variants: list the mod's GameBanana files, let the user pick one, download it."""
        mod = self.mgr.lib.mods.get(uid)
        if not mod:
            return
        self.say(f"Looking up files for {mod.name}…")

        def listed(files):
            self.say("")
            picked = choose_file(self, files, mod)
            if picked is None:
                return
            again = picked.id == mod.file_id

            def do(uid, file_id, choose=None, progress=None, cancel=None):
                return self.mgr.refetch(uid, file_id, choose=choose, progress=progress, cancel=cancel)
            self._queue(f"{mod.name} — {picked.filename}", do, uid, picked.id,
                        success=("Downloaded {name} again; every VPK it ships is kept." if again
                                 else "Switched {name} to " + picked.filename + "."),
                        kind="update", key=f"mod:{uid}")

        def failed(exc):
            self.say("")
            error(self, "Couldn't list files", str(exc))

        run(self.mgr.variant_files, uid, on_done=listed, on_error=failed)

    def roll_back(self, uid: str):
        mod = self.mgr.lib.mods.get(uid)
        if not mod or self.jobs.active_for(f"mod:{uid}"):
            return
        prev = (mod.previous or {}).get("file_name") or "the previous version"
        if not confirm(self, "Roll back", f"Switch “{mod.name}” back to {prev}? The current version is kept, "
                                          "so you can roll forward again from the same button.", "Roll back"):
            return
        try:
            m = self.mgr.roll_back(uid)
        except Exception as exc:  # noqa: BLE001
            error(self, "Couldn't roll back", str(exc))
            return
        self._library_changed()
        self.request_apply()
        self.say(f"Rolled {m.name} back to {m.file_name}.")

    def open_collection(self, cid: int):
        from sapphire.ui.collection import CollectionDialog
        dlg = CollectionDialog(self.mgr, cid, self.images, self)
        if dlg.exec():
            subs = dlg.chosen()
            for sub in subs:
                self.install_gb(sub.model, sub.id)
            if subs:
                self.say(f"Installing {len(subs)} mod{'s' if len(subs) != 1 else ''} from the collection. "
                         "See Downloads.", 12000)

    def import_profile_file(self, path):
        try:
            shared = self.mgr.read_shared_profile(path)
        except Exception as exc:  # noqa: BLE001
            error(self, "Couldn't open that profile", str(exc))
            return
        have = sum(1 for e in shared["mods"] if self.mgr.match_shared(e) is not None)
        local = [e["name"] for e in shared["mods"] if e["source"] != "gamebanana" and self.mgr.match_shared(e) is None]
        download = len(shared["mods"]) - have - len(local)
        lines = [f"“{shared['name']}” has {len(shared['mods'])} mod{'s' if len(shared['mods']) != 1 else ''}."]
        if have:
            lines.append(f"• {have} you already have")
        if download:
            lines.append(f"• {download} to download from GameBanana")
        if local:
            lines.append(f"• {len(local)} added from files, which can't be downloaded: " + ", ".join(local[:5])
                         + ("…" if len(local) > 5 else ""))
        lines.append("\nWhat should the profile be called here?")
        default = shared["name"]
        if default in self.mgr.lib.profiles:
            default = f"{default} (shared)"
        name = ask_text(self, "Import profile", "\n".join(lines), default)
        if not name:
            return
        if name in self.mgr.lib.profiles and not confirm(
                self, "Replace profile", f"“{name}” already exists. Replace it?", "Replace"):
            return

        def do(shared, name, choose=None, progress=None, cancel=None):
            return self.mgr.import_shared_profile(shared, name, choose=choose, progress=progress, cancel=cancel)

        def after(res):
            self.profiles.reload()
            extra = []
            if res["failed"]:
                extra.append(f"couldn't download {', '.join(res['failed'][:4])}")
            if res["missing"]:
                extra.append(f"{len(res['missing'])} not available")
            msg = f"Profile “{name}” is ready ({res['downloaded']} downloaded" + \
                  ("; " + "; ".join(extra) if extra else "") + "). Switch to it now?"
            if confirm(self, "Profile imported", msg, "Switch now"):
                self.mgr.load_profile(name)
                self.profiles.reload()
                self._profile_switched()

        self._queue(f"Profile: {name}", do, shared, name, silent=True, kind="import",
                    key=f"profile:{name}", after=after)

    def set_helper(self, on: bool):
        from sapphire import helper
        try:
            if on:
                helper.enable(start_now=True)
                self.say("Background helper on: mods keep loading after game updates, even with Sapphire closed.")
            else:
                helper.disable()
                self.say("Background helper off.")
        except OSError as exc:
            error(self, "Couldn't change the helper", str(exc))

    def update_all(self):
        for mod in [m for m in self.mgr.lib.ordered() if m.update]:
            self.update_mod(mod.uid)   # skips mods already queued or updating

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add mod files", str(Path.home() / "Downloads"),
                                                "Mod files (*.zip *.7z *.rar *.vpk);;All files (*)")
        for f in files:
            self.install_file(Path(f))

    def install_file(self, path: Path):
        def do(path, choose=None, progress=None, cancel=None):
            return self.mgr.install_local(path, choose=choose)
        self._queue(path.name, do, path, success="Added {name}.")

    def import_from(self, which: str):
        dlg = ImportDialog(self.mgr, which, self)
        if dlg.exec() != QDialog.Accepted or dlg.plan is None:
            return
        plan = dlg.plan
        profiles_only = dlg.profiles_only.isChecked()
        label = f"Import from {plan.source}"
        job = self.jobs.add(Job(label, kind="import"))

        def progress(stage, done, total):
            self.jobs.update(job, state="running", stage=stage, done=done, total=total)

        def worker(progress=None):
            self.jobs.update(job, state="running", stage="Starting")
            return self.mgr.run_import(plan, choose=self._chooser, progress=progress, cancel=job.cancel,
                                       profiles_only=profiles_only)

        def done(res):
            self.jobs.update(job, state="done")
            self._library_changed()
            self.request_apply()
            if profiles_only:
                msg = f"Imported {res['profiles']} profile{'s' if res['profiles'] != 1 else ''} from {plan.source}."
                if res.get("unmatched"):
                    msg += f" {res['unmatched']} mod{'s' if res['unmatched'] != 1 else ''} in them aren't installed here, so they were skipped."
            else:
                msg = (f"Imported {res['imported']} mod{'s' if res['imported'] != 1 else ''}"
                       + (f" and {res['profiles']} profile{'s' if res['profiles'] != 1 else ''}" if res['profiles'] else "")
                       + f" from {plan.source}.")
            if res["failed"]:
                msg += f" {res['failed']} failed; see the log."
            self.say(msg, 20000)
            unknown = [m.uid for m in self.mgr.lib.mods.values() if m.source == "local"]
            if unknown:
                self.identify(unknown)

        def failed(exc):
            if isinstance(exc, Cancelled):
                self.jobs.update(job, state="cancelled")
                self.say("Import cancelled.")
            else:
                self.jobs.update(job, state="failed", error=str(exc))
                error(self, "Import failed", str(exc))
            self._library_changed()

        run(worker, on_done=done, on_error=failed, on_progress=progress, pool=JOB_POOL)

    def identify(self, uids=None):
        targets = [m for m in self.mgr.lib.mods.values() if m.source == "local" and (uids is None or m.uid in uids)]
        if not targets:
            self.say("Nothing to identify: every mod is already linked to GameBanana.")
            return
        self.installed.identify_btn.setEnabled(False)
        self.installed.identify_btn.setText("Identifying…")

        def done(results):
            self.installed.identify_btn.setEnabled(True)
            self.installed.identify_btn.setText("Identify unknown")
            found = sum(1 for _u, m in results if m)
            self._library_changed()
            self.request_apply()
            if found:
                self.say(f"Identified {found} of {len(results)} mod{'s' if len(results) != 1 else ''}.", 15000)
            else:
                self.say(f"None of the {len(results)} unknown mod{'s' if len(results) != 1 else ''} matched a "
                         "GameBanana file.", 15000)

        def failed(exc):
            self.installed.identify_btn.setEnabled(True)
            self.installed.identify_btn.setText("Identify unknown")
            error(self, "Couldn't identify mods", str(exc))

        run(self.mgr.identify, uids, on_done=done, on_error=failed)

    # ------------------------------------------------------------ app updates
    def check_app_update(self, manual: bool = False):
        if self.updater.installed:
            self._show_restart()
            return
        if manual:
            self.settings.app_update_btn.setEnabled(False)
            self.settings.app_update_btn.setText("Checking…")

        def done(rel):
            self.settings.app_update_btn.setEnabled(True)
            self.settings.app_update_btn.setText("Check for updates")
            self.settings.set_update_state(rel)
            if rel:
                what = "" if rel.source == "release" else " (latest from the main branch)"
                self.update_label.setText(f"Sapphire {rel.version} is available{what}. You have {__version__}.")
                self.update_notes.setVisible(bool(rel.url))
                if getattr(self, "_notes_conn", None) is not None:
                    self.update_notes.clicked.disconnect(self._notes_conn)
                self._notes_conn = self.update_notes.clicked.connect(lambda: self._show_notes(rel))
                self.update_go.setText(f"Update to {rel.version}")
                self.update_go.setEnabled(True)
                self.update_later.show()
                self.update_bar.show()
            elif manual:
                self.say(f"Sapphire {__version__} is the latest version.")

        def failed(exc):
            self.settings.app_update_btn.setEnabled(True)
            self.settings.app_update_btn.setText("Check for updates")
            log.warning("app update check failed: %s", exc)
            if manual:
                error(self, "Couldn't check for updates", str(exc))

        run(self.updater.check, manual, on_done=done, on_error=failed)

    def _show_notes(self, rel):
        if not rel.notes:
            QDesktopServices.openUrl(QUrl(rel.url))
            return
        box = QMessageBox(self)
        box.setWindowTitle(f"What's new in Sapphire {rel.version}")
        box.setTextFormat(Qt.MarkdownText)
        box.setText(rel.notes[:6000])
        more = box.addButton("Open on GitHub", QMessageBox.ActionRole)
        box.addButton("Close", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is more:
            QDesktopServices.openUrl(QUrl(rel.url))

    def install_app_update(self):
        rel = self.updater.available
        if not rel:
            return
        if running_from_source():
            error(self, "Running from source", "You're running Sapphire from a source checkout, so update it "
                  "with git pull instead.")
            return
        self.update_go.setEnabled(False)
        self.update_later.hide()
        job = self.jobs.add(Job(f"Sapphire {rel.version}", kind="app-update"))

        def progress(stage, done, total):
            self.update_label.setText(f"{stage} Sapphire {rel.version}…")
            self.jobs.update(job, state="running", stage=stage, done=done, total=total)

        def done(_):
            self.jobs.update(job, state="done")
            self._show_restart()

        def failed(exc):
            self.jobs.update(job, state="failed", error=str(exc))
            self.update_go.setEnabled(True)
            self.update_later.show()
            self.update_label.setText(f"Update to {rel.version} failed.")
            error(self, "Update failed", str(exc))

        run(self.updater.install, rel, on_done=done, on_error=failed, on_progress=progress, pool=JOB_POOL)

    def _show_restart(self):
        rel = self.updater.installed
        if not rel:
            return
        self.update_label.setText(f"Sapphire {rel.version} is installed. Restart to start using it.")
        self.update_notes.hide()
        self.update_go.setText("Restart now")
        self.update_go.setEnabled(True)
        if not getattr(self, "_restart_wired", False):
            self.update_go.clicked.disconnect(self.install_app_update)
            self.update_go.clicked.connect(self._restart)
            self._restart_wired = True
        self.update_later.show()
        self.update_bar.show()
        self.settings.set_update_state(None, installed=rel)

    def _restart(self):
        if self.jobs.active() and not confirm(self, "Restart Sapphire", "Downloads are still running. Restart anyway?", "Restart"):
            return
        self._cancel_jobs()
        self.mgr.lib.save()
        log.info("restarting after update")
        restart()

    def check_updates(self, manual: bool = False):
        if manual:
            self.installed.check_btn.setEnabled(False)
            self.installed.check_btn.setText("Checking…")

        def done(found):
            self.installed.check_btn.setEnabled(True)
            self.installed.check_btn.setText("Check for updates")
            self._library_changed()
            n_checked = sum(1 for m in self.mgr.lib.mods.values() if m.source == "gamebanana" and m.gb_id)
            auto = self.mgr.auto_update_targets(found) if self.mgr.lib.settings.auto_update else []
            if auto and not manual:
                for m in auto:
                    self.update_mod(m.uid)
                self.say(f"Updating {len(auto)} mod{'s' if len(auto) != 1 else ''} automatically. "
                         "See Downloads.", 15000)
                return
            if found:
                self.say(f"{len(found)} update{'s' if len(found) != 1 else ''} available. See Installed.", 15000)
            elif manual:
                self.say("Everything is up to date.")
            if manual:
                box = QMessageBox(self)
                box.setWindowTitle("Mod updates")
                if found:
                    names = "\n".join(f"• {m.name}" for m in found[:15])
                    if len(found) > 15:
                        names += f"\n• … and {len(found) - 15} more"
                    box.setText(f"{len(found)} of {n_checked} mod{'s' if n_checked != 1 else ''} "
                                f"{'have' if len(found) != 1 else 'has'} an update:\n\n{names}")
                    upd = box.addButton("Update all", QMessageBox.AcceptRole)
                    box.addButton("Later", QMessageBox.RejectRole)
                    box.exec()
                    if box.clickedButton() is upd:
                        self.update_all()
                else:
                    box.setText(f"All {n_checked} mod{'s' if n_checked != 1 else ''} are up to date."
                                if n_checked else "No GameBanana mods to check. Mods added from files can't be "
                                                   "checked until they're identified.")
                    box.addButton("OK", QMessageBox.AcceptRole)
                    box.exec()

        def failed(exc):
            self.installed.check_btn.setEnabled(True)
            self.installed.check_btn.setText("Check for updates")
            if manual:
                error(self, "Couldn't check for updates", str(exc))

        run(self.mgr.check_updates, on_done=done, on_error=failed)

    # -------------------------------------------------------------- drag & drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(MOD_FILE_TYPES)
                                          for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in MOD_FILE_TYPES and path.is_file():
                self.install_file(path)

    def closeEvent(self, e):
        if self.jobs.active() and not confirm(self, "Quit Sapphire", "Downloads are still running. Quit anyway?", "Quit"):
            e.ignore()
            return
        self._cancel_jobs()
        self.presence.stop()
        e.accept()


def setup_logging():
    handler = logging.handlers.RotatingFileHandler(paths.log_file(), maxBytes=1_000_000, backupCount=2)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if os.environ.get("SAPPHIRE_DEBUG"):
        root.addHandler(logging.StreamHandler())
        root.setLevel(logging.DEBUG)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    setup_logging()
    log.info("Sapphire %s starting", __version__)
    QApplication.setApplicationName(APP_NAME)
    QApplication.setDesktopFileName(APP_ID)
    from sapphire import helper
    _gui_lock = helper.hold_gui_lock()  # noqa: F841 - held for the process lifetime; the helper backs off
    app = QApplication(argv)
    manager = Manager()
    st = manager.lib.settings
    theme.apply(app, st.theme_preset, st.theme_colors, theme.SCALES.get(st.ui_scale, 1.0))
    icon = Path(theme.ASSETS) / "sapphire.svg"
    app.setWindowIcon(QIcon(str(icon)))
    win = MainWindow(manager)
    win.show()
    # Files passed on the command line (e.g. "Open with Sapphire") get installed.
    for arg in argv[1:]:
        p = Path(arg)
        if p.suffix.lower() in MOD_FILE_TYPES and p.is_file():
            win.install_file(p)
    code = app.exec()
    NET_POOL.waitForDone(2000)
    JOB_POOL.waitForDone(5000)
    return code
