"""1.12.0: Queued for later (Ham's idea).

Mid-match you can't sensibly fiddle with mods, so you queue a reminder
("change the variant", "find a different one", "get rid of it", or a note) and
Sapphire hands you the list once Deadlock closes. Reminders are per profile,
one per mod, and vanish with the mod.
"""

from __future__ import annotations

import json

from sapphire import steam
from sapphire.core import Manager
from sapphire.library import InstalledMod, Library


def lib_with(names: str) -> Library:
    lib = Library()
    for n in names:
        lib.add(InstalledMod(uid=n, name=f"Mod {n}", source="local"), top=False)
    return lib


def queued(lib: Library) -> list[tuple[str, str, str]]:
    return [(x.uid, x.kind, x.note) for x in lib.later()]


def test_queue_replace_and_tick_off():
    lib = lib_with("ABC")
    mgr = Manager(lib)
    mgr.remind_later("B", "variant", "  try the red one ")
    mgr.remind_later("A", "remove")
    assert queued(lib) == [("B", "variant", "try the red one"), ("A", "remove", "")]
    first = lib.later_for("B").at
    mgr.remind_later("B", "swap")                 # one per mod: replaces, keeps its place
    assert queued(lib) == [("B", "swap", ""), ("A", "remove", "")]
    assert lib.later_for("B").at == first
    assert lib.remind("C", "nonsense").kind == "note"
    assert mgr.done_later("A") is True and mgr.done_later("A") is False
    assert [u for u, _, _ in queued(lib)] == ["B", "C"]


def test_works_while_the_game_is_running(monkeypatch):
    lib = lib_with("AB")
    mgr = Manager(lib)
    monkeypatch.setattr(steam, "is_game_running", lambda *a, **k: True)
    mgr.remind_later("A", "variant")             # the whole point: no GameRunning here
    assert Library(lib.path).later_for("A").kind == "variant"


def test_survives_a_restart_and_is_per_profile():
    lib = lib_with("ABC")
    mgr = Manager(lib)
    mgr.remind_later("A", "variant", "blue")
    mgr.new_profile("Kyle", copy=True)
    mgr.load_profile("Kyle")
    assert queued(lib) == []                      # Kyle's list starts empty
    mgr.remind_later("C", "remove")
    again = Library(lib.path)
    assert queued(again) == [("C", "remove", "")]
    again.switch("Default")
    assert queued(again) == [("A", "variant", "blue")]
    raw = json.loads(lib.path.read_text())
    assert raw["profiles"]["Default"]["later"][0]["note"] == "blue"


def test_reminders_follow_the_mod():
    lib = lib_with("ABC")
    mgr = Manager(lib)
    for u in "ABC":
        mgr.remind_later(u, "note", u)
    mgr.remove("A")                               # uninstall: gone from every list
    mgr.remove_from_profile("B")                  # out of this profile: nothing left to do with it
    assert queued(lib) == [("C", "note", "C")]
    lib.replace_uid("C", "gb-Mod-9")              # identified on GameBanana
    assert queued(lib) == [("gb-Mod-9", "note", "C")]
    mgr.rename_profile("Default", "Mine")
    assert queued(lib) == [("gb-Mod-9", "note", "C")]


def test_old_and_broken_state_files_load():
    lib = lib_with("AB")
    lib.save()
    raw = json.loads(lib.path.read_text())
    for p in raw["profiles"].values():
        p.pop("later")                            # saved by 1.11
    raw["profiles"]["Default"]["later"] = None
    lib.path.write_text(json.dumps(raw))
    assert Library(lib.path).later() == []
    raw["profiles"]["Default"]["later"] = [{"uid": "A", "kind": "variant"}, {"uid": "gone"}, "junk",
                                           {"kind": "remove"}, {"uid": "A", "kind": "remove"}]
    lib.path.write_text(json.dumps(raw))
    assert queued(Library(lib.path)) == [("A", "remove", "")]   # unknown mods and junk dropped, one per mod
