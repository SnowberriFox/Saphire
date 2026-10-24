import io
import json
import os
import stat
import sys
import tarfile
from pathlib import Path

import pytest

from sapphire import updater


def test_version_parsing():
    assert updater.parse_version("v1.2.3") == (1, 2, 3)
    assert updater.parse_version("1.10") == (1, 10)
    assert updater.is_newer("1.1.1", "1.1.0")
    assert updater.is_newer("v2.0.0", "1.9.9")
    assert not updater.is_newer("1.1.0", "1.1.0")
    assert not updater.is_newer("garbage", "1.0.0")


class FakeResp:
    def __init__(self, status, body=b"", headers=None):
        self.status_code = status
        self._body = body if isinstance(body, bytes) else body.encode()
        self.headers = headers or {}
        self.text = self._body.decode(errors="replace")

    def json(self):
        return json.loads(self._body)

    def iter_content(self, n):
        for i in range(0, len(self._body), n):
            yield self._body[i:i + n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeSession:
    def __init__(self, routes):
        self.routes = routes
        self.headers = {}
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(url)
        for prefix, resp in self.routes.items():
            if url.startswith(prefix):
                return resp
        return FakeResp(404)


def test_check_prefers_release_then_branch(monkeypatch):
    monkeypatch.setattr(updater, "__version__", "1.1.0")
    rel = json.dumps({"tag_name": "v1.3.0", "tarball_url": "https://api.github.com/x/tarball/v1.3.0",
                      "body": "notes", "html_url": "https://github.com/r/releases/v1.3.0"})
    u = updater.Updater(FakeSession({"https://api.github.com/repos/SnowberriFox/Saphire/releases/latest": FakeResp(200, rel)}))
    found = u.check(force=True)
    assert found and found.version == "1.3.0" and found.source == "release" and found.notes == "notes"

    raw = 'APP_NAME = "Sapphire"\n__version__ = "1.2.0"\n'
    u = updater.Updater(FakeSession({"https://raw.githubusercontent.com/SnowberriFox/Saphire/main/": FakeResp(200, raw)}))
    found = u.check(force=True)
    assert found and found.version == "1.2.0" and found.source == "branch"
    assert found.tarball_url.endswith("/tarball/main")

    # same version on the branch -> nothing
    u = updater.Updater(FakeSession({"https://raw.githubusercontent.com/": FakeResp(200, '__version__ = "1.1.0"')}))
    assert u.check(force=True) is None
    # nothing anywhere -> None, no error
    assert updater.Updater(FakeSession({})).check(force=True) is None
    # server trouble -> error
    with pytest.raises(updater.UpdateError):
        updater.Updater(FakeSession({"https://api.github.com/": FakeResp(500)})).check(force=True)


def test_newer_main_beats_an_older_release(monkeypatch):
    monkeypatch.setattr(updater, "__version__", "1.6.0")
    rel = json.dumps({"tag_name": "v1.6.0", "tarball_url": "https://api.github.com/x/tarball/v1.6.0"})
    raw = '__version__ = "1.6.1"\n'
    u = updater.Updater(FakeSession({
        "https://api.github.com/repos/SnowberriFox/Saphire/releases/latest": FakeResp(200, rel),
        "https://raw.githubusercontent.com/SnowberriFox/Saphire/main/": FakeResp(200, raw)}))
    found = u.check(force=True)
    assert found and found.version == "1.6.1" and found.source == "branch"
    # same version on both: the release (with its notes and bundle) wins
    raw2 = '__version__ = "1.7.0"\n'
    rel2 = json.dumps({"tag_name": "v1.7.0", "tarball_url": "t", "body": "notes"})
    u = updater.Updater(FakeSession({
        "https://api.github.com/repos/SnowberriFox/Saphire/releases/latest": FakeResp(200, rel2),
        "https://raw.githubusercontent.com/SnowberriFox/Saphire/main/": FakeResp(200, raw2)}))
    assert u.check(force=True).source == "release"


def test_check_is_rate_limited(monkeypatch):
    monkeypatch.setattr(updater, "__version__", "1.0.0")
    s = FakeSession({"https://raw.githubusercontent.com/": FakeResp(200, '__version__ = "9.0.0"')})
    u = updater.Updater(s)
    u.check()
    u.check()
    assert len([c for c in s.calls if "__init__" in c]) == 1
    u.check(force=True)
    assert len([c for c in s.calls if "__init__" in c]) == 2


def make_tarball(top: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in ((f"{top}/pyproject.toml", b"[project]\nname='sapphire'\n"),
                           (f"{top}/sapphire/__init__.py", b'__version__ = "1.2.0"\n')):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        evil = tarfile.TarInfo("../../escape.txt")
        evil.size = 1
        tf.addfile(evil, io.BytesIO(b"x"))
    return buf.getvalue()


def test_install_runs_uv_against_extracted_source(tmp_path, monkeypatch):
    log = tmp_path / "uv.log"
    uv = tmp_path / "uv"
    uv.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$@\" > {log}\nexit 0\n")
    uv.chmod(uv.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(updater, "running_from_source", lambda: False)
    monkeypatch.setattr(updater, "in_venv", lambda: True)
    monkeypatch.setattr(updater, "find_uv", lambda: str(uv))
    body = make_tarball("SnowberriFox-Saphire-abc123")
    s = FakeSession({"https://api.github.com/repos/SnowberriFox/Saphire/tarball/main":
                     FakeResp(200, body, {"Content-Length": str(len(body))})})
    u = updater.Updater(s)
    rel = updater.Release(version="1.2.0", source="branch",
                          tarball_url="https://api.github.com/repos/SnowberriFox/Saphire/tarball/main")
    stages = []
    u.install(rel, progress=lambda st, d, t: stages.append(st))
    args = log.read_text().split("\n")
    assert args[:6] == ["pip", "install", "--quiet", "--python", sys.executable, "--reinstall-package"]
    src = Path(args[7])
    assert src.name == "SnowberriFox-Saphire-abc123"
    assert stages[0] == "Downloading" and "Installing" in stages
    assert u.installed is rel and u.available is None
    assert not (tmp_path / "escape.txt").exists() and not Path("/home/claude/escape.txt").exists()


def test_install_refuses_from_source(monkeypatch):
    monkeypatch.setattr(updater, "running_from_source", lambda: True)
    with pytest.raises(updater.UpdateError):
        updater.Updater(FakeSession({})).install(updater.Release("9.0.0", "https://x"))


def test_install_reports_uv_failure(tmp_path, monkeypatch):
    uv = tmp_path / "uv"
    uv.write_text("#!/bin/sh\necho 'boom: no space' >&2\nexit 1\n")
    uv.chmod(uv.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(updater, "running_from_source", lambda: False)
    monkeypatch.setattr(updater, "in_venv", lambda: True)
    monkeypatch.setattr(updater, "find_uv", lambda: str(uv))
    body = make_tarball("top")
    s = FakeSession({"https://x": FakeResp(200, body)})
    with pytest.raises(updater.UpdateError, match="boom"):
        updater.Updater(s).install(updater.Release("1.2.0", "https://x"))


def test_changelog_section():
    text = "# Changelog\n\n## 1.3.0 — 2026-10-17\n\n### Added\n- Themes\n\n## 1.2.0 — 2026-10-17\n\n- Updater\n"
    assert updater.changelog_section(text, "1.3.0") == "### Added\n- Themes"
    assert updater.changelog_section(text, "1.2.0") == "- Updater"
    assert updater.changelog_section(text, "9.9.9") == ""


def test_branch_check_reads_changelog(monkeypatch):
    monkeypatch.setattr(updater, "__version__", "1.0.0")
    s = FakeSession({"https://raw.githubusercontent.com/SnowberriFox/Saphire/main/sapphire/__init__.py":
                     FakeResp(200, '__version__ = "1.3.0"'),
                     "https://raw.githubusercontent.com/SnowberriFox/Saphire/main/CHANGELOG.md":
                     FakeResp(200, "## 1.3.0 — today\n- Shiny\n\n## 1.2.0\n- Old")})
    rel = updater.Updater(s).check(force=True)
    assert rel.version == "1.3.0" and rel.notes == "- Shiny" and rel.url.endswith("CHANGELOG.md")
