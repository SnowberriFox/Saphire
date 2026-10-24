"""1.7.0: priority list with locks, drag to reorder (list and grid), patch notes."""

from __future__ import annotations

import os

import pytest

from sapphire import library, patchnotes
from sapphire.library import InstalledMod, Library

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def lib_with(names: str) -> Library:
    lib = Library()
    for n in names:
        lib.add(InstalledMod(uid=n, name=f"Mod {n}", source="local"), top=False)
    return lib


# ------------------------------------------------------------------ locking
def test_pin_and_move_keep_locked_slots():
    order = list("ABCDE")
    assert library.pin(["X"] + order, {"C": 2}) == list("XACBDE")       # install on top: C stays #3
    assert library.move(order, {"C": 2}, "A", 4) == list("BDCEA")        # C stays #3
    assert library.move(order, {"C": 2}, "E", 0) == list("EACBD")
    # onto the locked slot: above the lock when moving up, below it when moving down
    assert library.move(order, {"C": 2}, "E", 2) == list("AECBD")
    assert library.move(order, {"C": 2}, "A", 2) == list("BDCAE")
    # moving a locked mod moves its lock; landing on another lock swaps them
    locks = {"C": 2, "E": 4}
    assert library.move(order, locks, "C", 4) == list("ABEDC") and locks == {"C": 4, "E": 2}
    # a lock past the end clamps to the bottom but remembers its slot
    assert library.pin(list("AB"), {"A": 5}) == list("BA")


def test_library_locks_survive_installs_removals_and_profiles(tmp_path):
    lib = lib_with("ABCDE")
    lib.lock("C")
    assert lib.mods["C"].locked and lib.mods["C"].lock_at == 2
    lib.add(InstalledMod(uid="X", name="new", source="local"), top=True)
    assert lib.order.index("C") == 2
    lib.remove("A")
    lib.remove("B")
    assert lib.order.index("C") == 2 and lib.order == ["X", "D", "C", "E"]
    lib.snapshot("p")
    lib.set_order(["C", "E", "D", "X"])            # e.g. an imported order: the lock still wins
    assert lib.order.index("C") == 2
    lib.move_to("E", 3)
    assert lib.order.index("C") == 2 and lib.order[-1] == "E"
    lib.save()
    again = Library(lib.path)
    assert again.mods["C"].lock_at == 2 and again.order == lib.order
    again.lock("C", False)
    assert not again.mods["C"].locked


def test_replace_uid_keeps_place():
    lib = lib_with("ABC")
    lib.replace_uid("B", "gb-Mod-1")
    assert lib.order == ["A", "gb-Mod-1", "C"] and lib.mods["gb-Mod-1"].uid == "gb-Mod-1"


# ------------------------------------------------------------- drag (UI)
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _list(qapp, mode: str, n: int = 6):
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QListView, QListWidget, QListWidgetItem

    from sapphire.ui.reorder import ROLE_UID, ReorderList
    w = ReorderList()
    if mode == "grid":
        w.setViewMode(QListView.IconMode)
        w.setFlow(QListWidget.LeftToRight)
        w.setWrapping(True)
        w.setMovement(QListWidget.Static)
        w.setGridSize(QSize(100, 100))
        w.resize(330, 400)                 # three cards per row
    else:
        w.resize(300, 600)
    for i in range(n):
        it = QListWidgetItem(f"item {i}")
        it.setData(ROLE_UID, str(i))
        it.setSizeHint(QSize(100, 100) if mode == "grid" else QSize(280, 40))
        w.addItem(it)
    w.show()
    qapp.processEvents()
    return w


def _drag(qapp, w, src, dst):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    vp = w.viewport()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, src)
    for t in (0.2, 0.5, 1.0):
        QTest.mouseMove(vp, src + (dst - src) * t)
        qapp.processEvents()
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, dst)
    qapp.processEvents()


def test_drag_reorders_in_list_and_grid(qapp):
    from PySide6.QtCore import QPoint
    seen = []
    lst = _list(qapp, "list")
    lst.moved.connect(lambda uid, i: seen.append((uid, i)))
    r0, r3 = lst.visualItemRect(lst.item(0)), lst.visualItemRect(lst.item(3))
    _drag(qapp, lst, r0.center(), QPoint(r3.center().x(), r3.bottom() - 3))   # lower half of row 3
    assert seen == [("0", 3)]

    seen.clear()
    grid = _list(qapp, "grid")
    grid.moved.connect(lambda uid, i: seen.append((uid, i)))
    a, b = grid.visualItemRect(grid.item(5)), grid.visualItemRect(grid.item(1))
    assert b.top() == grid.visualItemRect(grid.item(0)).top()      # 1 is on the first row
    _drag(qapp, grid, a.center(), QPoint(b.left() + 8, b.center().y()))   # left half of card 1
    assert seen == [("5", 1)]
    assert grid.count() == 6           # nothing deleted (Qt's icon-mode drop could do that)


def test_locked_items_refuse_to_drag(qapp):
    seen, refused = [], []
    lst = _list(qapp, "list")
    lst.can_drag = lambda uid: uid != "0"
    lst.moved.connect(lambda uid, i: seen.append(uid))
    lst.refused.connect(refused.append)
    r0, r4 = lst.visualItemRect(lst.item(0)), lst.visualItemRect(lst.item(4))
    _drag(qapp, lst, r0.center(), r4.center())
    assert seen == [] and refused == ["0"]
    lst.reorderable = False
    _drag(qapp, lst, lst.visualItemRect(lst.item(1)).center(), r4.center())
    assert seen == []


def test_priority_dialog_moves_locks_and_saves(qapp):
    from sapphire.core import Manager
    from sapphire.ui.priority import PriorityDialog
    lib = lib_with("ABCDE")
    mgr = Manager(lib)
    dlg = PriorityDialog(None, mgr, select="C")
    dlg._toggle_lock()                       # lock C at #3
    dlg.list.setCurrentRow(4)                # E
    dlg._step("top")
    assert dlg.order == list("EACBD")
    dlg.list.setCurrentRow(0)
    dlg.number.setValue(5)
    dlg._go()
    assert dlg.order == list("ABCDE") and dlg.order.index("C") == 2
    assert lib.order == list("ABCDE") and not lib.mods["C"].locked   # draft only so far
    dlg.list.setCurrentRow(4)
    dlg._step("top")
    dlg.accept()
    assert lib.order == list("EACBD") and lib.mods["C"].lock_at == 2


# ------------------------------------------------------------- patch notes
TEXT = """# Changelog

## 1.7.0 — 2026-10-25
### Added
- seven

## 1.6.0 — 2026-10-24
- six

## 1.5.0 — 2026-10-23
- five
"""


def test_patch_notes_sections():
    assert [h for h, _ in patchnotes.notes_between(TEXT, "1.5.0", "1.7.0")] == \
        ["1.7.0 — 2026-10-25", "1.6.0 — 2026-10-24"]
    assert [h for h, _ in patchnotes.notes_between(TEXT, "", "1.7.0")] == ["1.7.0 — 2026-10-25"]
    assert [h for h, _ in patchnotes.notes_between(TEXT, "1.7.0", "1.7.0")] == ["1.7.0 — 2026-10-25"]
    assert "seven" in patchnotes.notes_between(TEXT, "1.6.0", "1.7.0")[0][1]
    assert patchnotes.should_show("update", "1.6.0", current="1.7.0")
    assert patchnotes.should_show("update", "", current="1.7.0")          # upgraded from before 1.7.0
    assert not patchnotes.should_show("update", "", fresh_install=True, current="1.7.0")
    assert not patchnotes.should_show("update", "1.7.0", current="1.7.0")
    assert patchnotes.should_show("always", "1.7.0", current="1.7.0")
    assert not patchnotes.should_show("never", "1.0.0", current="1.7.0")


def test_packaged_changelog_has_this_version():
    from sapphire import __version__
    text = patchnotes.changelog_text()
    assert any(v == __version__ for v, _, _ in patchnotes.sections(text))


def test_packaged_changelog_is_a_real_copy():
    # The in-app updater skips symlinks when it unpacks a release, so the copy
    # inside the package must be a real file, identical to the repo's CHANGELOG.md.
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    packaged = root / "sapphire" / "assets" / "CHANGELOG.md"
    assert not packaged.is_symlink()
    assert packaged.read_text(encoding="utf-8") == (root / "CHANGELOG.md").read_text(encoding="utf-8"), \
        "copy CHANGELOG.md to sapphire/assets/CHANGELOG.md"


def test_updater_unpack_keeps_patch_notes(tmp_path):
    # Build a GitHub-style tarball from the working tree and unpack it the way
    # the updater does: the patch notes must survive.
    import tarfile
    from pathlib import Path

    from sapphire.updater import Updater
    root = Path(__file__).resolve().parents[1]
    tb = tmp_path / "s.tar.gz"
    with tarfile.open(tb, "w:gz") as tf:
        for rel in ("pyproject.toml", "CHANGELOG.md", "sapphire/assets/CHANGELOG.md"):
            tf.add(root / rel, f"SnowberriFox-Saphire-abc123/{rel}")
    src = Updater._extract(tb, tmp_path / "src")
    assert (src / "sapphire/assets/CHANGELOG.md").stat().st_size > 1000
