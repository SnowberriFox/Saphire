"""Keeping Sapphire itself up to date, straight from GitHub.

Where a new version comes from, in order:
  1. the latest GitHub release of the repo (tag like v1.2.0), if any
  2. otherwise the version number in sapphire/__init__.py on the main branch

How it's installed: the tarball is downloaded and unpacked into Sapphire's
cache, then installed into Sapphire's own Python environment with uv (the
same tool install.sh used). Nothing outside ~/.local/share/sapphire is
touched, so it works the same on Ubuntu and Bazzite. The app then needs a
restart, which the UI offers.

Running from a source checkout (python -m sapphire in a git clone) is
detected and the updater steps aside: use git pull there.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

from sapphire import __version__, paths

log = logging.getLogger(__name__)

REPO = "SnowberriFox/Saphire"
BRANCH = "main"
API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
CHECK_INTERVAL = 6 * 3600


class UpdateError(Exception):
    pass


@dataclass
class Release:
    version: str
    tarball_url: str
    notes: str = ""
    source: str = "release"      # "release" or "branch"
    url: str = ""                # page to open


def parse_version(text: str) -> tuple[int, ...]:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not m:
        return (0,)
    return tuple(int(x) for x in m.groups() if x is not None)


def is_newer(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


def running_from_source() -> bool:
    """True when started from a git checkout rather than the installed copy."""
    here = Path(__file__).resolve()
    return (here.parent.parent / ".git").exists() or (here.parent.parent / "install.sh").exists()


def in_venv() -> bool:
    return sys.prefix != sys.base_prefix or (Path(sys.prefix) / "pyvenv.cfg").exists()


def find_uv() -> str | None:
    for cand in (shutil.which("uv"), Path.home() / ".local/bin/uv", Path.home() / ".cargo/bin/uv",
                 Path(sys.prefix) / "bin" / "uv"):
        if cand and Path(cand).is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return None


class Updater:
    def __init__(self, session: requests.Session | None = None, repo: str = REPO):
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", f"Sapphire/{__version__}")
        self.repo = repo
        self.last_check = 0.0
        self.available: Release | None = None
        self.installed: Release | None = None   # set once an update has been installed (needs restart)
        self._lock = threading.Lock()

    # ------------------------------------------------------------- checking
    def check(self, force: bool = False) -> Release | None:
        with self._lock:
            if not force and time.time() - self.last_check < CHECK_INTERVAL:
                return self.available
        rel = self._latest_release()
        if rel is None:
            rel = self._branch_version()
        with self._lock:
            self.last_check = time.time()
            self.available = rel if rel and is_newer(rel.version) else None
            return self.available

    def _get(self, url: str, **kw):
        try:
            return self.session.get(url, timeout=(6, 30), **kw)
        except requests.RequestException as exc:
            raise UpdateError(f"Couldn't reach GitHub: {exc.__class__.__name__}") from exc

    def _latest_release(self) -> Release | None:
        resp = self._get(f"{API}/repos/{self.repo}/releases/latest",
                         headers={"Accept": "application/vnd.github+json"})
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise UpdateError(f"GitHub returned HTTP {resp.status_code} while checking releases")
        data = resp.json()
        tag = str(data.get("tag_name") or data.get("name") or "")
        if not tag or data.get("draft") or data.get("prerelease"):
            return None
        return Release(version=tag.lstrip("vV"), tarball_url=data.get("tarball_url") or
                       f"{API}/repos/{self.repo}/tarball/{tag}",
                       notes=str(data.get("body") or ""), source="release",
                       url=str(data.get("html_url") or f"https://github.com/{self.repo}/releases"))

    def _branch_version(self) -> Release | None:
        resp = self._get(f"{RAW}/{self.repo}/{BRANCH}/sapphire/__init__.py")
        if resp.status_code >= 400:
            if resp.status_code == 404:
                return None
            raise UpdateError(f"GitHub returned HTTP {resp.status_code} while checking the main branch")
        m = re.search(r'__version__\s*=\s*"([^"]+)"', resp.text)
        if not m:
            return None
        return Release(version=m.group(1), tarball_url=f"{API}/repos/{self.repo}/tarball/{BRANCH}",
                       notes="", source="branch", url=f"https://github.com/{self.repo}/commits/{BRANCH}")

    # ----------------------------------------------------------- installing
    def install(self, rel: Release, progress: Callable[[str, int, int], None] | None = None) -> None:
        if running_from_source():
            raise UpdateError("You're running Sapphire from a source checkout. Update it with git pull.")
        if not in_venv():
            raise UpdateError("Sapphire isn't running from its own environment, so it can't update itself. "
                              "Re-run install.sh.")
        uv = find_uv()
        if not uv:
            raise UpdateError("uv (the installer tool) wasn't found. Re-run install.sh once; "
                              "updates will work after that.")
        work = Path(tempfile.mkdtemp(prefix="update-", dir=paths.cache_dir()))
        try:
            tarball = work / "sapphire.tar.gz"
            if progress:
                progress("Downloading", 0, 0)
            try:
                with self.session.get(rel.tarball_url, stream=True, timeout=(8, 120),
                                      allow_redirects=True) as resp:
                    if resp.status_code >= 400:
                        raise UpdateError(f"Download failed (HTTP {resp.status_code})")
                    total = int(resp.headers.get("Content-Length") or 0)
                    done = 0
                    with open(tarball, "wb") as fh:
                        for chunk in resp.iter_content(256 * 1024):
                            fh.write(chunk)
                            done += len(chunk)
                            if progress:
                                progress("Downloading", done, total)
            except requests.RequestException as exc:
                raise UpdateError(f"Download interrupted: {exc.__class__.__name__}") from exc
            if progress:
                progress("Unpacking", 0, 0)
            src = self._extract(tarball, work / "src")
            if not (src / "pyproject.toml").is_file():
                raise UpdateError("The download doesn't look like Sapphire (no pyproject.toml).")
            if progress:
                progress("Installing", 0, 0)
            cmd = [uv, "pip", "install", "--quiet", "--python", sys.executable,
                   "--reinstall-package", "sapphire", str(src)]
            env = dict(os.environ)
            env.pop("PYTHONPATH", None)
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=900)
            if proc.returncode != 0:
                tail = proc.stderr.decode(errors="replace").strip().splitlines()[-3:]
                raise UpdateError("Install failed:\n" + "\n".join(tail))
            with self._lock:
                self.installed = rel
                self.available = None
            log.info("updated to %s from %s", rel.version, rel.source)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    @staticmethod
    def _extract(tarball: Path, dest: Path) -> Path:
        dest.mkdir(parents=True, exist_ok=True)
        dest_r = dest.resolve()
        with tarfile.open(tarball, "r:gz") as tf:
            members = []
            for m in tf.getmembers():
                target = (dest / m.name).resolve()
                if not str(target).startswith(str(dest_r)) or m.issym() or m.islnk():
                    continue
                members.append(m)
            try:
                tf.extractall(dest, members=members, filter="data")
            except TypeError:  # Python < 3.12
                tf.extractall(dest, members=members)
        # GitHub tarballs have a single top-level folder: <owner>-<repo>-<sha>/
        tops = [p for p in dest.iterdir() if p.is_dir()]
        if len(tops) == 1 and (tops[0] / "pyproject.toml").is_file():
            return tops[0]
        return dest


def restart() -> None:
    """Replace this process with a fresh Sapphire."""
    launcher = Path.home() / ".local" / "bin" / "sapphire"
    if launcher.is_file() and os.access(launcher, os.X_OK):
        os.execv(str(launcher), [str(launcher)])
    os.execv(sys.executable, [sys.executable, "-m", "sapphire"])
