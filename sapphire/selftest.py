"""`sapphire --selftest`: check this install works, without touching your mods.

Imports every part Sapphire needs (Qt and its multimedia backend, the archive
and compression libraries), checks 7-Zip can extract a real archive, builds
the main window offscreen and closes it again. Uses a throwaway data folder, so
your library, settings and the game are never touched. Prints one line per
check and exits non-zero if any fails. CI runs it inside the Flatpak.
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path


def run() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sapphire-selftest-"))
    os.environ["SAPPHIRE_HOME"] = str(tmp / "home")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    results: list[tuple[str, bool, str]] = []

    def check(name, fn):
        try:
            detail = fn() or ""
            results.append((name, True, str(detail)))
        except Exception as exc:  # noqa: BLE001
            results.append((name, False, f"{exc.__class__.__name__}: {exc}"))
            traceback.print_exc()

    def versions():
        import PySide6

        from sapphire import __version__
        return f"Sapphire {__version__}, Python {sys.version.split()[0]}, PySide6 {PySide6.__version__}"

    def libs():
        import lz4.block
        import py7zr
        import rarfile  # noqa: F401
        import requests  # noqa: F401
        import zstandard
        data = b"sapphire" * 100
        assert lz4.block.decompress(lz4.block.compress(data, store_size=False), uncompressed_size=len(data)) == data
        assert zstandard.ZstdDecompressor().decompress(zstandard.ZstdCompressor().compress(data)) == data
        return f"py7zr {py7zr.__version__}, zstandard {zstandard.__version__}"

    def seven_zip():
        import zipfile

        from sapphire import archive
        exe = archive.find_7z()
        if not exe:
            if os.environ.get("FLATPAK_ID"):
                raise RuntimeError("7-Zip not found (it ships inside the Flatpak)")
            return "not installed: .7z and .rar fall back to the Python readers"
        z = tmp / "t.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("pak01_dir.vpk", b"x")
        out = archive.extract(z, tmp / "x")
        assert (Path(out) / "pak01_dir.vpk").is_file() or any(Path(out).rglob("pak01_dir.vpk"))
        return exe

    def multimedia():
        # Decode a real MP3 (GameBanana previews are MP3) through Qt's player:
        # a second of silent MPEG-1 Layer III frames, built by hand.
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtWidgets import QApplication

        from sapphire.ui.audio import pick_audio_backend
        app = QApplication.instance() or QApplication([])
        backend = pick_audio_backend()
        from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
        clip = tmp / "silence.mp3"
        clip.write_bytes((bytes([0xFF, 0xFB, 0x90, 0x64]) + bytes(413)) * 40)
        player, out = QMediaPlayer(), QAudioOutput()
        out.setVolume(0.0)
        player.setAudioOutput(out)
        seen, loop = [], QEventLoop()
        player.mediaStatusChanged.connect(lambda st: (seen.append(st), st in (
            QMediaPlayer.EndOfMedia, QMediaPlayer.InvalidMedia) and loop.quit()))
        player.errorOccurred.connect(lambda *_: loop.quit())
        player.setSource(QUrl.fromLocalFile(str(clip)))
        player.play()
        QTimer.singleShot(8000, loop.quit)
        loop.exec()
        if QMediaPlayer.EndOfMedia not in seen or not player.hasAudio():
            raise RuntimeError(f"couldn't decode MP3 ({player.errorString() or 'no audio'})")
        del app
        n = len(QMediaDevices.audioOutputs())
        return f"backend {os.environ.get('QT_AUDIO_BACKEND') or backend}, MP3 decodes, {n} output(s)"

    def window():
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication

        from sapphire.core import Manager
        from sapphire.library import Library
        from sapphire.ui import theme
        from sapphire.ui.app import MainWindow
        app = QApplication.instance() or QApplication([])
        theme.apply(app)
        lib = Library()
        lib.settings.onboarded = True       # skip the first-run wizard
        lib.save()
        win = MainWindow(Manager(lib))
        win.show()
        for page in range(win.stack.count()):
            win.go(page)
            app.processEvents()
        QTimer.singleShot(1500, app.quit)
        app.exec()
        win.close()
        return f"{win.stack.count()} pages"

    check("versions", versions)
    check("libraries", libs)
    check("7-Zip", seven_zip)
    check("sound", multimedia)
    check("window", window)
    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    return 0 if all(ok for _, ok, _ in results) else 1
