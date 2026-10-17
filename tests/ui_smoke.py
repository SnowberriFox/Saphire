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
from sapphire.ui.dialogs import VariantDialog  # noqa: E402
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
        mgr.lib.add(mod, top=False)
    mgr.lib.settings.onboarded = True
    mgr.lib.save()
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
        win.installed.list.setCurrentRow(3)
        QTimer.singleShot(800, lambda: (shot("3-installed-conflict"), profiles()))

    def profiles():
        win.go(2)
        win.profiles.list.setCurrentRow(0)
        QTimer.singleShot(400, lambda: (shot("4-profiles"), settings()))

    def settings():
        win.go(3)
        QTimer.singleShot(400, lambda: (shot("5-settings"), variants()))

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
            if win.jobs:
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
