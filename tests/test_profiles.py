"""1.11.0: profiles are separate setups (Ham's request, like Deadlock Mod Manager).

Every mod is downloaded once; each profile has its own mods, order and on/off,
and only shows its own. Changes save into the active profile as you make them.
"""

from __future__ import annotations

import json

import pytest

from sapphire.core import Manager, ManagerError
from sapphire.library import InstalledMod, Library


def lib_with(names: str) -> Library:
    lib = Library()
    for n in names:
        lib.add(InstalledMod(uid=n, name=f"Mod {n}", source="local"), top=False)
    return lib


def visible(lib: Library) -> list[str]:
    return [m.uid for m in lib.visible()]


def test_fresh_library_has_a_default_profile():
    lib = Library()
    assert lib.active_profile == "Default" and list(lib.profiles) == ["Default"]
    lib.add(InstalledMod(uid="A", name="A", source="local"))
    lib.save()
    assert Library(lib.path).profiles["Default"].entries == [("A", True)]


def test_profiles_only_show_their_own_mods_and_share_the_files():
    lib = lib_with("ABC")
    mgr = Manager(lib)
    mgr.new_profile("Ham")                 # empty
    mgr.load_profile("Ham")
    assert visible(lib) == [] and not any(m.enabled for m in lib.mods.values())
    assert set(lib.mods) == set("ABC")     # still downloaded
    lib.add(InstalledMod(uid="H", name="Ham's skin", source="local"))   # installing joins this profile only
    assert mgr.add_to_profile(["B"]) == ["B"]
    assert visible(lib) == ["B", "H"] and lib.mods["B"].enabled
    mgr.load_profile("Default")
    assert visible(lib) == list("ABC") and not lib.mods["H"].enabled
    assert lib.profiles_with("B") == ["Default", "Ham"]
    assert [m.uid for m in lib.not_in_profile()] == ["H"]
    # order and on/off are per profile
    mgr.set_enabled("A", False)
    lib.move_to("C", 0)
    mgr.load_profile("Ham")
    assert visible(lib) == ["B", "H"] and lib.mods["A"].enabled is False
    mgr.load_profile("Default")
    assert visible(lib) == ["C", "A", "B"] and lib.mods["A"].enabled is False and lib.mods["B"].enabled


def test_remove_from_profile_keeps_files_uninstall_removes_everywhere():
    lib = lib_with("AB")
    mgr = Manager(lib)
    mgr.save_profile("Copy")               # copy of Default, now active
    mgr.remove_from_profile("A")
    assert visible(lib) == ["B"] and "A" in lib.mods
    assert lib.profiles_with("A") == ["Default"]
    lib.remove("B")                        # uninstall
    assert all("B" not in dict(p.entries) for p in lib.profiles.values())


def test_cant_delete_the_profile_youre_on():
    mgr = Manager(lib_with("A"))
    mgr.new_profile("Other")
    with pytest.raises(ManagerError):
        mgr.delete_profile("Default")
    mgr.delete_profile("Other")
    assert list(mgr.lib.profiles) == ["Default"]
    with pytest.raises(ManagerError):
        mgr.new_profile("Default")


def test_locks_stay_inside_their_profile():
    lib = lib_with("ABCD")
    lib.lock("B")                          # #2 in Default
    lib.new_profile("Other")
    lib.switch("Other")
    lib.add_to_profile(["D", "C"])
    assert visible(lib) == ["D", "C"]      # B's lock doesn't drag it in
    lib.switch("Default")
    assert visible(lib)[1] == "B"


def test_migration_keeps_what_was_on_in_each_profile(tmp_path):
    # 1.10 state: one list of 4 mods; profiles were snapshots of on/off
    mods = {u: {"uid": u, "name": u, "source": "local", "enabled": u in "AB"} for u in "ABCD"}
    state = {"schema": 1, "mods": mods, "order": list("ABCD"), "active_profile": "Kyle",
             "profiles": {"Kyle": {"entries": [["A", True], ["B", False], ["C", True], ["D", False]], "saved_at": 1},
                          "Astella": {"entries": [["C", True], ["D", True], ["A", False]], "saved_at": 1}}}
    path = tmp_path / "state.json"
    path.write_text(json.dumps(state))
    lib = Library(path)
    # the active profile keeps what's on right now (A, B), not its older snapshot
    assert lib.active_profile == "Kyle" and visible(lib) == ["A", "B"]
    assert lib.profiles["Astella"].entries == [("C", True), ("D", True)]
    lib.switch("Astella")
    assert visible(lib) == ["C", "D"] and not lib.mods["A"].enabled
    lib.save()
    assert json.loads(path.read_text())["schema"] == 2


def test_migration_without_profiles_makes_default(tmp_path):
    mods = {u: {"uid": u, "name": u, "source": "local", "enabled": u == "A"} for u in "AB"}
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"schema": 1, "mods": mods, "order": ["A", "B"]}))
    lib = Library(path)
    assert lib.active_profile == "Default" and visible(lib) == ["A"]
    assert [m.uid for m in lib.not_in_profile()] == ["B"]


def test_duplicate_copies_mods_order_and_switches():
    lib = lib_with("ABC")
    mgr = Manager(lib)
    mgr.set_enabled("B", False)
    mgr.duplicate_profile("Default", "Copy")
    assert lib.profiles["Copy"].entries == [("A", True), ("B", False), ("C", True)]
    with pytest.raises(ManagerError):
        mgr.duplicate_profile("Default", "Copy")


def test_shared_profile_import_doesnt_touch_the_current_one():
    # a mod downloaded for an imported profile isn't added to the one you're on
    lib = lib_with("A")
    lib.add(InstalledMod(uid="X", name="for the shared one", source="local"), member=False)
    assert visible(lib) == ["A"] and lib.mods["X"].enabled is False


def test_a_mod_listed_twice_shows_once(tmp_path):
    # older versions could write a uid into the load order twice (Installed showed
    # "101" for 98 mods); loading cleans it up
    mods = {u: {"uid": u, "name": u, "source": "local", "enabled": True} for u in "ABC"}
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"schema": 1, "mods": mods, "order": ["A", "B", "A", "C", "B"],
                                "profiles": {"P": {"entries": [["A", True]]},
                                             "Q": {"entries": [["A", True], ["A", True], ["C", True]]}},
                                "active_profile": "P"}))
    lib = Library(path)
    assert visible(lib) == ["A", "B", "C"] and lib.order == ["A", "B", "C"]
    lib.switch("Q")
    assert visible(lib) == ["A", "C"]
    lib.set_order(["C", "C", "A"])
    assert lib.order.count("C") == 1
