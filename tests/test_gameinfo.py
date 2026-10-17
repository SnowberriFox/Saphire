import pytest
from helpers import VANILLA

from sapphire import gameinfo


def vanilla() -> str:
    return VANILLA.read_bytes().decode("utf-8")


def search_block(text: str) -> list[str]:
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if l.strip() == "SearchPaths")
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == "}")
    return [l.strip() for l in lines[start:end + 1] if l.strip() and not l.strip().startswith("// These")
            and not l.strip().startswith("// *LANG") and not l.strip().startswith("// When")]


def test_vanilla_is_unpatched():
    st = gameinfo.inspect(vanilla())
    assert not st.patched and not st.foreign


def test_patch_inserts_before_game_citadel_and_keeps_crlf():
    text = vanilla()
    out = gameinfo.patch(text, ["citadel/addons"])
    assert "\r\n" in out and "\n" not in out.replace("\r\n", "")
    lines = [l.strip() for l in out.splitlines()]
    addons = lines.index("Game\t\t\t\tcitadel/addons")
    citadel = next(i for i, l in enumerate(lines) if l.split() == ["Game", "citadel"])
    assert addons < citadel
    assert lines[addons + 1].split() == ["Mod", "citadel"]
    assert lines[addons + 2].split() == ["Write", "citadel"]
    st = gameinfo.inspect(out)
    assert st.patched and st.folders == ["citadel/addons"] and not st.foreign
    # nothing outside our block changed
    assert gameinfo.unpatch(out) == text


def test_patch_is_idempotent_and_updates_folders():
    once = gameinfo.patch(vanilla(), ["citadel/addons"])
    assert gameinfo.patch(once, ["citadel/addons"]) == once
    assert not gameinfo.needs_patch(once, ["citadel/addons"])
    assert gameinfo.needs_patch(once, ["citadel/addons", "citadel/addons2"])
    twice = gameinfo.patch(once, ["citadel/addons", "citadel/addons2"])
    assert gameinfo.inspect(twice).folders == ["citadel/addons", "citadel/addons2"]
    assert twice.count(gameinfo.MARK_BEGIN) == 1


def test_cleans_up_other_managers_patch():
    # What Deadlock Mod Manager writes: its whole own SearchPaths template plus markers.
    text = vanilla()
    dmm = text.replace(
        "\t\t\tGame\t\t\t\tcitadel\r\n\t\t\tGame\t\t\t\tcore\r\n",
        "// Deadlock Mod Manager - Start\r\n"
        "            Game                citadel/addons\r\n"
        "            Mod                 citadel\r\n"
        "            Write               citadel\r\n"
        "            Game                citadel\r\n"
        "            Mod                 core\r\n"
        "            Write               core\r\n"
        "            Game                core\r\n"
        "// Deadlock Mod Manager - End\r\n")
    assert dmm != text
    st = gameinfo.inspect(dmm)
    assert st.foreign
    out = gameinfo.patch(dmm, ["citadel/addons"])
    st = gameinfo.inspect(out)
    assert st.patched and not st.foreign
    keys = [l.split() for l in out.splitlines() if l.split()[:1] in (["Mod"], ["Write"])]
    assert keys == [["Mod", "citadel"], ["Write", "citadel"]]
    assert "Mod Manager" not in out


def test_manual_patch_is_cleaned():
    text = vanilla().replace("\t\t\tGame\t\t\t\tcitadel\r\n",
                             "\t\t\tGame\t\t\t\tcitadel/addons\r\n\t\t\tGame\t\t\t\tcitadel\r\n")
    out = gameinfo.patch(text, ["citadel/addons"])
    assert sum(1 for l in out.splitlines() if l.split() == ["Game", "citadel/addons"]) == 1


def test_unpatch_with_no_folders():
    out = gameinfo.patch(vanilla(), ["citadel/addons"])
    assert gameinfo.patch(out, []) == vanilla()


def test_lf_files_and_broken_files():
    lf = vanilla().replace("\r\n", "\n")
    out = gameinfo.patch(lf, ["citadel/addons"])
    assert "\r" not in out
    with pytest.raises(gameinfo.GameInfoError):
        gameinfo.patch('"GameInfo"\n{\n}\n', ["citadel/addons"])


def test_file_apply_and_backup(tmp_path):
    from helpers import make_game
    game = make_game(tmp_path)
    path = gameinfo.gameinfo_path(game)
    path.chmod(0o444)  # some guides tell people to make it read-only
    assert gameinfo.apply(game, ["citadel/addons"], tmp_path / "bk") is True
    assert gameinfo.apply(game, ["citadel/addons"], tmp_path / "bk") is False
    assert len(list((tmp_path / "bk").glob("gameinfo-*.gi"))) == 1
    assert gameinfo.inspect(gameinfo.read(game)).patched
    assert gameinfo.apply(game, [], tmp_path / "bk") is True
    assert path.read_bytes() == VANILLA.read_bytes()
