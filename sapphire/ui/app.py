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
from sapphire.ui.dialogs import choose_variants, confirm, error
from sapphire.ui.images import ImageCache
from sapphire.ui.importing import ImportDialog
from sapphire.ui.installed import InstalledPage
from sapphire.ui.onboarding import OnboardingDialog
from sapphire.ui.pages import ProfilesPage, SettingsPage
from sapphire.updater import Updater, UpdateError, restart, running_from_source
from sapphire.ui.workers import JOB_POOL, NET_POOL, MainThreadCaller, run

log = logging.getLogger("sapphire")
MOD_FILE_TYPES = (".zip", ".7z", ".rar", ".vpk")


class Job:
    def __init__(self, label: str):
        self.label = label
        self.cancel = threading.Event()


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
        self.jobs: list[Job] = []
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
        self.profiles = ProfilesPage(manager)
        self.settings = SettingsPage(manager)
        for page in (self.browse, self.installed, self.profiles, self.settings):
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
        self.settings.setup_requested.connect(self.run_setup)
        self.settings.import_requested.connect(self.import_from)
        self.settings.app_update_requested.connect(lambda: self.check_app_update(manual=True))
        self.settings.appearance_changed.connect(self.apply_appearance)
        self.installed.reapply_requested.connect(self.reapply)

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
        for i, label in enumerate(("Browse", "Installed", "Profiles", "Settings")):
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
        elif index == 3:
            self.settings.refresh()

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

    def _tick(self):
        was = self.running
        self.running = steam.is_game_running()
        self._ticks += 1
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
            self.go(3)
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
                self.say(f"Applied. {n} mod{'s' if n != 1 else ''} on."
                         + (f" ({result.written} files written)" if result.written else ""))
            self._after_apply()

        def failed(exc):
            self._applying = False
            if isinstance(exc, GameRunning):
                self.running = True
            elif isinstance(exc, NoGame):
                self.go(3)
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
    def _job_started(self, job: Job):
        self.jobs.append(job)
        self._jobs_ui()

    def _job_finished(self, job: Job):
        if job in self.jobs:
            self.jobs.remove(job)
        self._jobs_ui()

    def _jobs_ui(self, done: int = 0, total: int = 0, stage: str = ""):
        visible = bool(self.jobs)
        for w in (self.job_label, self.job_bar, self.job_cancel):
            w.setVisible(visible)
        if not visible:
            return
        job = self.jobs[0]
        extra = f"  (+{len(self.jobs) - 1} queued)" if len(self.jobs) > 1 else ""
        self.job_label.setText(f"{stage or 'Waiting'}: {job.label}{extra}")
        if total:
            self.job_bar.setRange(0, 1000)
            self.job_bar.setValue(int(done / total * 1000))
        else:
            self.job_bar.setRange(0, 0)

    def _cancel_jobs(self):
        for job in self.jobs:
            job.cancel.set()

    def _chooser(self, sets, name):
        return self.caller.call(choose_variants, self, sets, name)

    def _queue(self, label: str, fn, *args, success: str = ""):
        job = Job(label)
        self._job_started(job)

        def progress(stage, done, total):
            if self.jobs and self.jobs[0] is job:
                self._jobs_ui(done, total, stage)

        def worker(progress=None):
            if job.cancel.is_set():
                raise Cancelled()
            return fn(*args, choose=self._chooser, progress=progress, cancel=job.cancel)

        def done(mod):
            self._job_finished(job)
            self.say(success.format(name=getattr(mod, "name", label)))
            self._library_changed()
            self.request_apply()

        def failed(exc):
            self._job_finished(job)
            if isinstance(exc, Cancelled):
                self.say(f"Cancelled: {label}")
                return
            error(self, "Install failed", f"{label}\n\n{exc}")

        run(worker, on_done=done, on_error=failed, on_progress=progress, pool=JOB_POOL)

    def install_gb(self, model: str, gb_id: int, file=None):
        existing = self.mgr.lib.by_gb(model, gb_id)
        label = existing.name if existing else f"GameBanana {model.lower()} {gb_id}"
        if file is not None:
            label = file.filename

        def do(model, gb_id, file, choose=None, progress=None, cancel=None):
            return self.mgr.install_gamebanana(model, gb_id, file, choose=choose,
                                               progress=progress, cancel=cancel)
        self._queue(label, do, model, gb_id, file, success="Installed {name}.")

    def update_mod(self, uid: str):
        mod = self.mgr.lib.mods.get(uid)
        if not mod:
            return

        def do(uid, choose=None, progress=None, cancel=None):
            return self.mgr.update(uid, choose=choose, progress=progress, cancel=cancel)
        self._queue(mod.name, do, uid, success="Updated {name}.")

    def update_all(self):
        for mod in [m for m in self.mgr.lib.ordered() if m.update]:
            self.update_mod(mod.uid)

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
        job = Job(label)
        self._job_started(job)

        def progress(stage, done, total):
            if self.jobs and self.jobs[0] is job:
                self._jobs_ui(done, total, stage)

        def worker(progress=None):
            return self.mgr.run_import(plan, choose=self._chooser, progress=progress, cancel=job.cancel,
                                       profiles_only=profiles_only)

        def done(res):
            self._job_finished(job)
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
            self._job_finished(job)
            if isinstance(exc, Cancelled):
                self.say("Import cancelled.")
            else:
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
                try:
                    self.update_notes.clicked.disconnect()
                except RuntimeError:
                    pass
                self.update_notes.clicked.connect(lambda: self._show_notes(rel))
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
        job = Job(f"Sapphire {rel.version}")
        self._job_started(job)

        def progress(stage, done, total):
            self.update_label.setText(f"{stage} Sapphire {rel.version}…")
            if self.jobs and self.jobs[0] is job:
                self._jobs_ui(done, total, stage)

        def done(_):
            self._job_finished(job)
            self._show_restart()

        def failed(exc):
            self._job_finished(job)
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
        try:
            self.update_go.clicked.disconnect()
        except RuntimeError:
            pass
        self.update_go.clicked.connect(self._restart)
        self.update_later.show()
        self.update_bar.show()
        self.settings.set_update_state(None, installed=rel)

    def _restart(self):
        if self.jobs and not confirm(self, "Restart Sapphire", "Downloads are still running. Restart anyway?", "Restart"):
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
            if found:
                self.say(f"{len(found)} update{'s' if len(found) != 1 else ''} available. See Installed.", 15000)
            elif manual:
                self.say("Everything is up to date.")

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
        if self.jobs and not confirm(self, "Quit Sapphire", "Downloads are still running. Quit anyway?", "Quit"):
            e.ignore()
            return
        self._cancel_jobs()
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
