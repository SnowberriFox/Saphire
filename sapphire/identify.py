"""Working out which GameBanana mod an unknown VPK came from.

Uses the public hash-lookup service run by the Deadlock Mod Manager project
(the same one its "Analyze Local Addons" button talks to). It has indexed the
VPKs inside every GameBanana download, so a hash of your file maps straight
back to the mod and the exact file it was downloaded from.

Two fingerprints are sent:
  * sha256 of the whole file (exact match, 100%)
  * a "content signature": sha256 over the sorted list of
    "<path>\\0<length>\\0<crc32>" for every entry (90%; survives a re-pack)
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from sapphire import __version__, paths
from sapphire.vpk import VpkError, read_entries

log = logging.getLogger(__name__)

API = "https://api.deadlockmods.app/api/v2/vpk-analyse-hashes"
JUNK = ("thumbs.db", ".ds_store", "desktop.ini", ".tmp", ".temp")
MIN_CERTAINTY = 90


class IdentifyError(Exception):
    pass


@dataclass
class Fingerprint:
    sha256: str
    content_signature: str
    size: int


@dataclass
class Match:
    model: str           # "Mod" or "Sound"
    gb_id: int
    file_id: int | None
    certainty: int
    match_type: str
    name: str = ""
    author: str = ""
    source_path: str = ""   # where the VPK sat inside the download


def fingerprint(path: Path) -> Fingerprint:
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
            size += len(chunk)
    try:
        entries = read_entries(path)
    except (VpkError, OSError) as exc:
        raise IdentifyError(f"not a readable VPK: {exc}") from exc
    tuples = []
    for e in entries:
        p = e.path.lower().replace("\\", "/")
        if any(j in p for j in JUNK):
            continue
        tuples.append(f"{p}\x00{e.length}\x00{e.crc:08x}")
    tuples.sort()
    sig = hashlib.sha256("\n".join(tuples).encode()).hexdigest()
    return Fingerprint(sha256=h.hexdigest(), content_signature=sig, size=size)


def _parse_match(raw: dict) -> Match | None:
    vpk = raw.get("matchedVpk") or {}
    info = raw.get("match") or {}
    if not isinstance(vpk, dict) or not isinstance(info, dict):
        return None
    sub_type = (vpk.get("submissionType") or "").lower()
    sub_id = vpk.get("submissionId")
    mod = vpk.get("mod") if isinstance(vpk.get("mod"), dict) else {}
    remote = str(mod.get("remoteId") or "")
    if not sub_id and remote:
        if remote.startswith("snd-"):
            sub_type, sub_id = "sound", remote[4:]
        else:
            sub_type, sub_id = sub_type or "mod", remote
    try:
        gb_id = int(str(sub_id))
    except (TypeError, ValueError):
        return None
    if gb_id <= 0:
        return None
    file_id = None
    try:
        if vpk.get("fileId"):
            file_id = int(str(vpk["fileId"]))
    except ValueError:
        pass
    return Match(
        model="Sound" if sub_type == "sound" else "Mod",
        gb_id=gb_id,
        file_id=file_id,
        certainty=int(info.get("certainty") or 0),
        match_type=str(info.get("matchType") or ""),
        name=str(mod.get("name") or ""),
        author=str(mod.get("author") or ""),
        source_path=str(vpk.get("sourcePath") or ""),
    )


class Identifier:
    def __init__(self, session: requests.Session | None = None, cache_file: Path | None = None,
                 api: str = API):
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", f"Sapphire/{__version__} (Deadlock mod manager; Linux)")
        self.api = api
        self.cache_file = cache_file or paths.cache_dir() / "identify-cache.json"
        self._lock = threading.Lock()
        try:
            self._cache: dict = json.loads(self.cache_file.read_text())
        except (OSError, ValueError):
            self._cache = {}

    def _save(self):
        with self._lock:
            try:
                self.cache_file.write_text(json.dumps(self._cache))
            except OSError:
                pass

    def lookup(self, path: Path) -> Match | None:
        """Best match for the VPK at `path`, or None if the service doesn't know it."""
        fp = fingerprint(path)
        with self._lock:
            hit = self._cache.get(fp.sha256)
        if hit is not None and time.time() - hit.get("at", 0) < 7 * 86400:
            return Match(**hit["match"]) if hit.get("match") else None
        body = {"sha256": fp.sha256, "contentSignature": fp.content_signature, "fileSize": fp.size}
        try:
            resp = self.session.post(self.api, json=body, timeout=(6, 30))
        except requests.RequestException as exc:
            raise IdentifyError(f"Couldn't reach the mod identification service: {exc.__class__.__name__}") from exc
        if resp.status_code == 404:
            results = []
        elif resp.status_code >= 400:
            raise IdentifyError(f"Identification service returned HTTP {resp.status_code}")
        else:
            try:
                results = resp.json()
            except ValueError as exc:
                raise IdentifyError("Identification service sent something that isn't JSON") from exc
        if isinstance(results, dict):
            results = results.get("results") or results.get("data") or [results]
        best: Match | None = None
        for raw in results if isinstance(results, list) else []:
            if not isinstance(raw, dict):
                continue
            m = _parse_match(raw)
            if m and m.certainty >= MIN_CERTAINTY and (best is None or m.certainty > best.certainty):
                best = m
        with self._lock:
            self._cache[fp.sha256] = {"at": time.time(), "match": best.__dict__ if best else None}
        self._save()
        return best
