"""Offscreen UI smoke test with fake GameBanana data. Saves screenshots.

Run: QT_QPA_PLATFORM=offscreen python3 tests/ui_smoke.py <out_dir>
"""

import os
import random
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

tmp = Path(tempfile.mkdtemp(prefix="sapphire-ui-"))
os.environ["SAPPHIRE_HOME"] = str(tmp / "home")
os.environ["HOME"] = str(tmp / "userhome")
(tmp / "userhome").mkdir()

from helpers import make_game, make_vpk  # noqa: E402
from PySide6.QtCore import QTimer, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from sapphire import archive, steam  # noqa: E402
from sapphire.core import Manager  # noqa: E402
from sapphire.gamebanana import Category, Details, GameBananaClient, GBFile, Page, Submission  # noqa: E402
from sapphire.library import Library  # noqa: E402
from sapphire.ui import theme  # noqa: E402
from sapphire.ui.app import MainWindow  # noqa: E402
from sapphire.ui.dialogs import FileVariantDialog, VariantDialog  # noqa: E402
from sapphire.vpk import find_sets  # noqa: E402

steam.is_game_running = lambda *a, **k: False
archive.find_7z = lambda: None
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else tmp / "shots")
OUT.mkdir(parents=True, exist_ok=True)

HEROES = ["Haze", "Lady Geist", "Abrams", "Infernus", "Seven", "Vindicta", "Mo & Krill", "Pocket",
          "Wraith", "Yamato", "Dynamo", "Kelvin", "Bebop", "Paradox", "Shiv", "Ivy"]
NAMES = ["Noir Detective {h}", "{h} but Gold Plated", "Clockwork {h}", "{h} Saint Mask",
         "Prohibition-era {h}", "{h} Jade Opera Skin", "Gaslamp {h} Recolour", "{h} Brass Knuckles",
         "Midnight Carnival {h}", "{h} Speakeasy Suit", "Clean HUD (minimal)", "Readable Damage Numbers",
         "Soul Orb Sound Pack", "Quieter Ability Pings", "{h} Voice Lines EN Remix", "Patina Map Lighting"]
AUTHORS = ["velvetgear", "ossuary_ink", "TallyMarks", "Meridian", "copperwick", "nightjarr", "Brasshand",
           "fennec.dev", "liminal_lou", "OddBolt"]
random.seed(4)


def fake_image(seed: int) -> QImage:
    img = QImage(530, 298, QImage.Format_RGB32)
    p = QPainter(img)
    g = QLinearGradient(0, 0, 530, 298)
    hue = (seed * 37) % 360
    g.setColorAt(0, QColor.fromHsv(hue, 90, 110))
    g.setColorAt(1, QColor.fromHsv((hue + 40) % 360, 120, 45))
    p.fillRect(img.rect(), g)
    p.setPen(QColor(255, 255, 255, 40))
    for i in range(0, 530, 22):
        p.drawLine(i, 298, i + 120, 0)
    p.setBrush(QColor(0, 0, 0, 70))
    p.setPen(Qt.NoPen)
    p.drawEllipse(200 + seed % 60, 60, 130, 200)
    p.end()
    return img


def make_subs(n, start=0):
    out = []
    for i in range(start, start + n):
        h = HEROES[i % len(HEROES)]
        name = NAMES[i % len(NAMES)].format(h=h)
        out.append(Submission(
            id=600000 + i, model="Mod", name=name, url=f"https://gamebanana.com/mods/{600000 + i}",
            author=AUTHORS[i % len(AUTHORS)], author_id=1000 + i % len(AUTHORS),
            date_added=1_750_000_000 + i * 9000, date_modified=1_759_000_000 + i * 5000,
            likes=random.randint(3, 900), views=random.randint(800, 90000),
            root_category="Skins" if "{h}" in NAMES[i % len(NAMES)] else "HUD",
            sub_category=h if "{h}" in NAMES[i % len(NAMES)] else "Interface",
            nsfw=(i == 7), obsolete=(i == 11),
            thumb_url=f"https://images.gamebanana.com/img/ss/mods/530-90_fake{i}.jpg",
            image_urls=[f"https://images.gamebanana.com/img/ss/mods/fake{i}.jpg",
                        f"https://images.gamebanana.com/img/ss/mods/fake{i}b.jpg"]))
    return out


ALL = make_subs(90)
ALL[12].audio_url = "https://files.gamebanana.com/preview/sounds/soul_orb.mp3"


class FakeClient(GameBananaClient):
    def browse(self, model="Mod", page=1, per_page=30, search="", category_id=None, sort="popular",
               submitter_id=None):
        items = [s for s in ALL if (not search or search.lower() in s.name.lower())
                 and (not submitter_id or s.author_id == submitter_id)]
        if sort == "popular":
            items.sort(key=lambda s: -s.likes)
        chunk = items[(page - 1) * per_page: page * per_page]
        return Page(items=chunk, total=len(items) + 8400, complete=page * per_page >= len(items), page=page)

    def categories(self, model="Mod"):
        return [Category(1, "Skins", 6120, children=[Category(100 + i, h, 40 + i * 13) for i, h in enumerate(HEROES)]),
                Category(2, "HUD", 812), Category(3, "Other/Misc", 455), Category(4, "Maps", 120)]

    def details(self, model, mod_id):
        sub = next(s for s in ALL if s.id == mod_id)
        files = [GBFile(id=mod_id * 10 + 2, filename=f"{sub.name.lower().replace(' ', '_')}_v2.zip",
                        size=48_000_000, date_added=1_759_500_000, downloads=1840,
                        description="All three colourways included. Pick one when installing."),
                 GBFile(id=mod_id * 10 + 1, filename=f"{sub.name.lower().replace(' ', '_')}_v1.zip",
                        size=44_200_000, date_added=1_752_000_000, downloads=5210, archived=True)]
        text = ("<p>A full model replacement with new textures and tuned materials.</p>"
                "<p><b>Includes:</b> base, gold and jade variants. Works with the latest patch.</p>"
                "<ul><li>Camera-safe proportions</li><li>No gameplay changes</li></ul>")
        return Details(submission=sub, text_html=text, files=files)

    def collection(self, collection_id, max_pages=40):
        from sapphire.gamebanana import Collection
        return Collection(id=collection_id, name="Tamie's mod suggestions: Vanilla-ish Skins", author="Tamie",
                          items=[ALL[0], ALL[2], ALL[3], ALL[7], ALL[12], ALL[14], ALL[20]], skipped=3)

    def files(self, model, mod_id):
        return self.details(model, mod_id).files

    def download(self, file, dest_dir, progress=None, cancel=None):
        dest_dir.mkdir(parents=True, exist_ok=True)
        z = dest_dir / file.filename
        with zipfile.ZipFile(z, "w") as zf:
            for c in ("Base", "Gold", "Jade"):
                v = make_vpk(tmp / "dlbuild" / c / "pak01_dir.vpk", {f"models/{c.lower()}.vmdl_c": b"x" * 100})
                zf.write(v, f"{c}/pak01_dir.vpk")
        if progress:
            progress(z.stat().st_size, z.stat().st_size)
        return z


def build_state(mgr: Manager):
    game = make_game(tmp / "steam" / "steamapps" / "common")
    mgr.set_game_dir(game)
    # a fake Grimoire install so the import dialog has something to show
    import json
    gdata = Path(os.environ["HOME"]) / ".config" / "Grimoire"
    gdata.mkdir(parents=True)
    citadel = game / "game" / "citadel"
    make_vpk(citadel / "addons" / "pak01_dir.vpk", {"models/vindicta.vmdl_c": b"v" * 3000})
    make_vpk(citadel / "addons" / "pak02_dir.vpk", {"hud/minimal.vxml_c": b"h" * 900})
    make_vpk(citadel / "addons" / ".disabled" / "jade_lash.vpk", {"models/lash.vmdl_c": b"l" * 1200})
    (gdata / "mod-metadata.json").write_text(json.dumps({
        "pak01_dir.vpk": {"modName": "Vindicta Nightjar", "author": "nightjarr", "gameBananaId": 600003,
                          "gameBananaFileId": 6000032, "categoryName": "Vindicta"},
        "pak02_dir.vpk": {"modName": "Minimal HUD", "gameBananaId": 600010, "gameBananaFileId": 6000102},
        "jade_lash.vpk": {"modName": "Jade Lash", "author": "ossuary_ink", "gameBananaId": 600007},
    }))
    (gdata / "profiles.json").write_text(json.dumps([{"id": "x", "name": "Grimoire ranked", "mods": [
        {"fileName": "pak01_dir.vpk", "enabled": True, "priority": 0, "gameBananaId": 600003, "gameBananaFileId": 6000032},
        {"fileName": "jade_lash.vpk", "enabled": True, "priority": 1, "gameBananaId": 600007}]}]))
    dmm = Path(os.environ["HOME"]) / ".local/share/dev.stormix.deadlock-mod-manager"
    dmm.mkdir(parents=True)
    (dmm / "state.json").write_text(json.dumps({"local-config": {"state": {"localMods": [
        {"remoteId": "600005", "name": "Seven Storm Coat", "installOrder": 0,
         "selectedDownloads": [{"url": "https://gamebanana.com/dl/6000052", "name": "seven_storm.zip"}]}],
        "profiles": {}}}}))
    work = tmp / "mods"
    specs = [
        (ALL[0], {"models/heroes/haze/haze.vmdl_c": b"a", "materials/haze/skin.vmat_c": b"a"}),
        (ALL[1], {"models/heroes/haze/haze.vmdl_c": b"b"}),
        (ALL[10], {"panorama/layout/hud.vxml_c": b"c", "panorama/images/hud/bar.vtex_c": b"c"}),
        (ALL[12], {"sounds/orbs/pickup.vsnd_c": b"d"}),
        (ALL[4], {"models/heroes/infernus/infernus.vmdl_c": b"e"}),
        (ALL[13], {"sounds/orbs/pickup.vsnd_c": b"f", "sounds/ping.vsnd_c": b"f"}),
    ]
    from sapphire.library import InstalledMod, UpdateInfo
    for i, (sub, files) in enumerate(specs):
        v = make_vpk(work / str(i) / "pak01_dir.vpk", files)
        sets = find_sets(work / str(i))
        stored = mgr._store(sub.key, sets)
        mod = InstalledMod(uid=sub.key, name=sub.name, model="Mod", gb_id=sub.id, url=sub.url,
                           author=sub.author, category=sub.category_label, thumb_url=sub.thumb_url,
                           file_id=sub.id * 10 + 1, file_name="v1.zip", file_date=1_752_000_000,
                           vpks=stored, installed_at=1_758_000_000, enabled=(i != 4))
        if i == 0:
            mod.update = UpdateInfo(sub.id * 10 + 2, "v2.zip", 1_759_500_000)
            mod.previous = {"file_id": sub.id * 10, "file_name": "noir_detective_haze_v0.9.zip",
                            "file_date": 1_745_000_000, "updated_at": 1_750_000_000, "vpks": []}
            mgr.previous_dir(sub.key).mkdir(parents=True, exist_ok=True)
        if sub is ALL[12]:
            mod.audio_url = sub.audio_url
        mgr.lib.add(mod, top=False)
    mgr.lib.settings.onboarded = True
    mgr.lib.settings.patch_notes = "never"   # opened explicitly further down
    mgr.lib.save()
    cfg = mgr.game_dir / "game/citadel/cfg"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "citadel_hero_settings.lst").write_bytes((Path(__file__).with_name("hero_settings_sample.lst")).read_bytes())
    (cfg / "autoexec.cfg").write_text("// my autoexec\nfps_max 240\n")
    mgr.save_profile("Mine")
    mgr.lib.mods[ALL[1].key].enabled = False
    mgr.save_profile("Partner's setup")
    mgr.load_profile("Mine")


def main():
    app = QApplication([])
    theme.apply(app)
    client = FakeClient()
    mgr = Manager(Library(), client)
    build_state(mgr)
    # onboarding screenshots first
    from sapphire.ui.onboarding import OnboardingDialog
    dlg = OnboardingDialog(mgr)
    dlg.resize(720, 540)
    dlg.show()
    app.processEvents()
    dlg.grab().save(str(OUT / "0a-setup-welcome.png"))
    dlg.steps[0].ack.setChecked(True)
    dlg.goto(1)
    app.processEvents()
    dlg.grab().save(str(OUT / "0b-setup-game.png"))
    dlg.goto(2)
    app.processEvents()
    dlg.grab().save(str(OUT / "0c-setup-existing.png"))
    dlg.goto(3)
    for _ in range(20):
        app.processEvents()
        if dlg.steps[3].ready:
            break
        import time as _t
        _t.sleep(0.1)
    app.processEvents()
    dlg.grab().save(str(OUT / "0d-setup-gamebanana.png"))
    print("setup: next enabled on last step =", dlg.next.isEnabled(), dlg.next.text())
    dlg.close()

    win = MainWindow(mgr)
    from sapphire import updater as _upd
    win.updater.check = lambda force=False: _upd.Release(version="1.2.0", tarball_url="https://x", source="release",
                                                         notes="Fixes", url="https://github.com/SnowberriFox/Saphire/releases")
    for i in range(120):  # pre-fill image cache (no network here)
        img = fake_image(i)
        win.images._pix[f"https://images.gamebanana.com/img/ss/mods/530-90_fake{i}.jpg"] = QPixmap.fromImage(img)
        win.images._pix[f"https://images.gamebanana.com/img/ss/mods/fake{i}.jpg"] = QPixmap.fromImage(img)
    win.resize(1440, 900)
    win.show()
    steps = []

    def shot(name):
        app.processEvents()
        win.grab().save(str(OUT / f"{name}.png"))
        print("saved", name)

    def browse():
        win.go(0)
        win.check_app_update()
        QTimer.singleShot(1200, browse_select)

    def browse_select():
        idx = win.browse.model.index(2)
        win.browse.grid.setCurrentIndex(idx)
        QTimer.singleShot(1200, lambda: (shot("1-browse"), installed()))

    def installed():
        win.go(1)
        win.installed.list.setCurrentRow(0)
        QTimer.singleShot(1500, lambda: (shot("2-installed"), conflicts()))

    def conflicts():
        # give one mod a second (inactive) variant so the Variants section shows
        from sapphire.library import StoredFile, StoredVpk
        m = mgr.lib.mods[ALL[12].key]
        extra = make_vpk(m.folder / "01_alt.vpk", {"sounds/orbs/pickup.vsnd_c": b"alt"})
        m.vpks.append(StoredVpk(label="Loud/pak01_dir.vpk", files=[StoredFile(stored="01_alt.vpk")], active=False))
        m.vpks[0].label = "Quiet/pak01_dir.vpk"
        mgr.lib.save()
        win.installed.reload()
        win.installed.list.setCurrentRow(3)
        QTimer.singleShot(800, lambda: (shot("3-installed-conflict"), installed_list()))

    def installed_list():
        win.installed.view_group.button(1).setChecked(True)
        QTimer.singleShot(800, lambda: (shot("3b-installed-list"), priority()))

    def priority():
        # Row 25/26: lock one mod, then drag a card in the real grid with the mouse.
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        page = win.installed
        page.view_group.button(0).setChecked(True)
        app.processEvents()
        order = list(mgr.lib.order)
        locked = order[2]
        page.set_locked(locked, True)
        app.processEvents()
        lst, vp = page.list, page.list.viewport()
        src = lst.visualItemRect(lst.item(5)).center()
        r1 = lst.visualItemRect(lst.item(1))
        dst = QPoint(r1.left() + 10, r1.center().y())
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, src)
        for t in (0.1, 0.4, 0.8, 1.0):
            QTest.mouseMove(vp, src + (dst - src) * t)
            app.processEvents()
        shot("3f-grid-dragging")
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, dst)
        app.processEvents()
        after = list(mgr.lib.order)
        print("grid drag:", order[5] == after[1], "locked stays #3:", after[2] == locked,
              "count kept:", len(after) == len(order) == lst.count())
        lst.setCurrentRow(2)
        QTimer.singleShot(600, lambda: (shot("3g-locked"), priority_dialog()))

    def priority_dialog():
        from sapphire.ui.priority import PriorityDialog
        dlg = PriorityDialog(win, mgr, select=mgr.lib.order[2])
        dlg.show()
        app.processEvents()
        dlg.grab().save(str(OUT / "15-priority.png"))
        dlg.list.setCurrentRow(len(dlg.order) - 1)
        dlg._step("top")
        print("priority dialog: locked still #3:", dlg.order[2] == mgr.lib.order[2], "draft only:",
              dlg.order != mgr.lib.order)
        dlg.reject()
        from sapphire.ui.patchnotes import PatchNotesDialog
        notes = PatchNotesDialog(win, mgr, "1.5.0")
        notes.show()
        app.processEvents()
        notes.grab().save(str(OUT / "16-patch-notes.png"))
        notes.close()
        mgr.set_locked(mgr.lib.order[2], False)
        win.installed.reload()
        downloads()

    def downloads():
        from sapphire.ui.downloads import Job
        j1 = win.jobs.add(Job("Clockwork Abrams", kind="install")); win.jobs.update(j1, state="running", stage="Downloading", done=18_000_000, total=45_800_000)
        j2 = win.jobs.add(Job("Soul Orb Sound Pack", kind="update"))
        j3 = win.jobs.add(Job("Midnight Carnival Wraith", kind="install")); win.jobs.update(j3, state="done")
        j4 = win.jobs.add(Job("Shiv Voice Lines EN Remix", kind="install")); win.jobs.update(j4, state="failed", error="Download was incomplete, try again")
        win.go(3)
        def after():
            shot("3c-downloads")
            for j in (j1, j2):
                win.jobs.update(j, state="done")
            update_twice()
        QTimer.singleShot(600, after)

    def update_twice():
        # Update all pressed twice while the first batch is still going: no duplicates.
        import threading
        gate = threading.Event()
        real = mgr.update
        mgr.update = lambda uid, **kw: (gate.wait(5), mgr.lib.mods[uid])[1]
        pending = [m.uid for m in mgr.lib.ordered() if m.update]
        win.update_all()
        win.update_all()
        app.processEvents()
        keyed = [j for j in win.jobs.jobs if j.key.startswith("mod:") and j.active]
        print("update all twice:", len(pending), "pending ->", len(keyed), "jobs; button:",
              win.installed.update_all_btn.text(), "enabled:", win.installed.update_all_btn.isEnabled())
        gate.set()

        def restore():
            mgr.update = real
            camera()
        QTimer.singleShot(800, restore)

    def camera():
        from sapphire.camera_fix import ModelReport
        mods = mgr.lib.ordered()
        mgr.camera_report = {
            mods[0].uid: [ModelReport("models/heroes_wip/haze/haze.vmdl_c", "fixed", "",
                                      ["aim", "crouching_pivot", "near_00", "standing_pivot"] * 4)],
            mods[2].uid: [ModelReport("models/heroes_wip/inferno/inferno_v4.vmdl_c", "warning",
                                      "camera pivots use mixed frames; left as is")]}
        win.go(1)
        win.installed.reload()
        win.installed.list.setCurrentRow(0)
        def snap():
            shot("3d-camera-fixed")
            win.installed.view_group.button(1).setChecked(True)
            QTimer.singleShot(500, lambda: (shot("3e-camera-list"), win.installed.view_group.button(0).setChecked(True),
                                            setattr(mgr, "camera_report", {}), planned()))
        QTimer.singleShot(900, snap)

    def planned():
        # Installed: roll back + other skins for the hero
        win.go(1)
        win.installed.reload()
        win.installed.list.setCurrentRow(0)
        def inst():
            shot("11-installed-rollback-hero")
            win.go(0)
            win.browse.detail.show_sub(ALL[12])
            QTimer.singleShot(700, fav_and_sound)
        QTimer.singleShot(700, inst)

    def fav_and_sound():
        mgr.lib.toggle_favourite(ALL[12])
        mgr.lib.toggle_favourite(ALL[3])
        win.browse.detail._render()
        shot("12-browse-sound-preview-fav")
        win.browse.filters.favourites_only.setChecked(True)
        def favs():
            shot("13-browse-favourites")
            win.browse.filters.favourites_only.setChecked(False)
            from sapphire.ui.collection import CollectionDialog
            dlg = CollectionDialog(mgr, 164637, win.images, win)
            dlg.show()
            def col():
                app.processEvents()
                dlg.grab().save(str(OUT / "14-collection.png"))
                print("saved 14-collection; chosen:", [s.name for s in dlg.chosen()], "button:", dlg.ok.text())
                dlg.close()
                crosshair_shots()
            QTimer.singleShot(900, col)
        QTimer.singleShot(900, favs)

    def crosshair_shots():
        win.go(4)
        tab = win.crosshair.crosshair
        v = tab.values()
        v.update(crosshair_color_r=40, crosshair_color_g=255, crosshair_color_b=140, crosshair_pip_gap=2,
                 crosshair_dot_size=3, crosshair_pip_outline_border=1)
        tab.set_values(v)
        def a():
            shot("15-crosshair")
            ok = tab.values()["crosshair_color_g"] == 255
            win.crosshair.tabs.setCurrentIndex(1)
            QTimer.singleShot(400, lambda: (shot("16-autoexec"), print("crosshair editor values ok:", ok,
                              "| autoexec:", repr(win.crosshair.autoexec.edit.toPlainText()[:30])),
                              win.crosshair.tabs.setCurrentIndex(0), profiles()))
        QTimer.singleShot(500, a)

    def profiles():
        win.go(2)
        win.profiles.list.setCurrentRow(0)
        QTimer.singleShot(400, lambda: (shot("4-profiles"), settings()))

    def settings():
        win.go(5)
        QTimer.singleShot(400, lambda: (shot("5-settings"), small_settings()))

    def small_settings():
        # a short window must scroll, not squash the sections together
        win.resize(1020, 640)
        app.processEvents()
        QTimer.singleShot(400, lambda: (shot("5b-settings-small"), win.resize(1360, 860), listview()))

    def listview():
        win.go(0)
        win.browse.view_group.button(1).setChecked(True)
        QTimer.singleShot(800, lambda: (shot("8-browse-list"), themed()))

    def themed():
        mgr.lib.settings.theme_preset = "Amber Hand"
        mgr.lib.settings.ui_scale = "Large"
        win.apply_appearance()
        win.go(1)
        QTimer.singleShot(800, lambda: (shot("9-amber-large"), parchment()))

    def parchment():
        mgr.lib.settings.theme_preset = "Parchment"
        mgr.lib.settings.theme_colors = {"accent": "#B5423A"}
        mgr.lib.settings.ui_scale = "Normal"
        win.apply_appearance()
        win.go(5)
        win.settings._refresh_swatches()
        QTimer.singleShot(800, lambda: (shot("10-parchment-settings"), restore_theme()))

    def restore_theme():
        mgr.lib.settings.theme_preset = "Sapphire"
        mgr.lib.settings.theme_colors = {}
        win.apply_appearance()
        win.browse.view_group.button(0).setChecked(True)
        win.installed.view_group.button(0).setChecked(True)
        importdlg()

    def importdlg():
        from sapphire.ui.importing import ImportDialog
        dlg = ImportDialog(mgr, "grimoire", win)
        dlg.show()

        def wait(n=0):
            app.processEvents()
            if dlg.plan is None and n < 50:
                return QTimer.singleShot(100, lambda: wait(n + 1))
            app.processEvents()
            dlg.grab().save(str(OUT / "7-import-grimoire.png"))
            print("saved 7-import-grimoire; plan mods:", [m.name for m in dlg.plan.mods] if dlg.plan else None)
            dlg.close()
            variants()
        wait()

    def variants():
        d = tmp / "variants"
        for c in ("Base", "Gold", "Jade"):
            make_vpk(d / c / "pak01_dir.vpk", {"a.txt": b"x" * 4000})
        dlg = VariantDialog(find_sets(d), "Noir Detective Haze", win)
        dlg.show()
        app.processEvents()
        dlg.grab().save(str(OUT / "6-variants.png"))
        print("saved 6-variants")
        dlg.close()
        # "Other variants…": the mod's files on GameBanana, installed one marked
        first = mgr.lib.ordered()[0]
        gbfiles = [GBFile(id=first.file_id, filename="yamato_blue_cd01a.rar", size=61_000_000, date_added=1_771_000_000,
                          description="Blue outfit"),
                   GBFile(id=first.file_id + 1, filename="yamato_red_cd01a.rar", size=61_200_000, date_added=1_771_000_000,
                          description="Red outfit"),
                   GBFile(id=first.file_id + 2, filename="yamato_gold_cd01a.rar", size=60_800_000, date_added=1_771_100_000,
                          description="Gold outfit, also recolours the katana"),
                   GBFile(id=first.file_id - 1, filename="yamato_blue_v1.rar", size=58_000_000, date_added=1_752_000_000,
                          archived=True)]
        fdlg = FileVariantDialog(gbfiles, first, win)
        fdlg.show()
        app.processEvents()
        fdlg.grab().save(str(OUT / "6b-other-variants.png"))
        print("saved 6b-other-variants; chosen:", fdlg.chosen().filename, "button:", fdlg.ok.text())
        fdlg.tree.setCurrentItem(fdlg.tree.topLevelItem(0))
        print("after selecting first row:", fdlg.chosen().filename, "button:", fdlg.ok.text())
        fdlg.close()
        # verify the startup apply actually deployed files
        addons = sorted(p.name for p in (mgr.game_dir / "game/citadel/addons").iterdir())
        print("deployed:", addons)
        from sapphire import gameinfo
        print("gameinfo patched:", gameinfo.inspect(gameinfo.read(mgr.game_dir)).folders)
        print("conflicts:", {k: (v.winning, v.losing) for k, v in win.installed.conflicts.items()})
        install_flow()

    def install_flow():
        import sapphire.ui.app as appmod
        asked = []

        def fake_choose(parent, sets, name):
            asked.append((name, [x.rel for x in sets]))
            return [x for x in sets if x.rel.startswith("Gold")]
        appmod.choose_variants = fake_choose
        target = ALL[20]
        win.install_gb("Mod", target.id, None)

        def check():
            if win.jobs.running() or any(j.state == "queued" and j.kind == "install" and j.label.startswith("GameBanana") for j in win.jobs.jobs):
                return QTimer.singleShot(200, check)
            mod = mgr.lib.by_gb("Mod", target.id)
            print("chooser asked:", asked)
            print("installed via UI:", mod and mod.name, mod and [v.label for v in mod.vpks])
            print("top of order:", mgr.lib.order[0] == target.key)
            QTimer.singleShot(1500, finish)

        QTimer.singleShot(300, check)

    def finish():
        addons = sorted(p.name for p in (mgr.game_dir / "game/citadel/addons").iterdir())
        print("deployed after install:", addons)
        app.quit()

    QTimer.singleShot(1500, browse)
    QTimer.singleShot(30000, app.quit)
    app.exec()


main()
