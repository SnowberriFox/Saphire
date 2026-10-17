"""GameBanana apiv11 client for Deadlock (game id 20948). No API key needed."""

from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from sapphire import __version__, paths

log = logging.getLogger(__name__)

API = "https://gamebanana.com/apiv11"
GAME_ID = 20948
MODELS = ("Mod", "Sound")

# GameBanana sort tokens (verified by other Deadlock managers against the live API).
SORTS = {
    "popular": ("Most liked", "Generic_MostLiked"),
    "views": ("Most viewed", "Generic_MostViewed"),
    "newest": ("Newest", "Generic_Newest"),
    "updated": ("Recently updated", "Generic_LatestModified"),
}

LIST_FIELDS = ",".join([
    "_idRow", "_sModelName", "_sName", "_sProfileUrl", "_tsDateAdded", "_tsDateModified",
    "_tsDateUpdated", "_nLikeCount", "_nViewCount", "_nDownloadCount", "_bHasFiles",
    "_bIsObsolete", "_bHasContentRatings", "_aSubmitter", "_aPreviewMedia", "_aGame",
    "_aRootCategory", "_aSubCategory", "_sVersion",
])
URL_RE = re.compile(r"gamebanana\.com/(mods|sounds)/(?:[a-z]+/)?(\d+)", re.IGNORECASE)


class GameBananaError(Exception):
    pass


class Cancelled(Exception):
    pass


# ------------------------------------------------------------------ data types

@dataclass
class Submission:
    id: int
    model: str
    name: str
    url: str = ""
    author: str = ""
    author_id: int = 0
    date_added: int = 0
    date_modified: int = 0
    likes: int = 0
    views: int = 0
    downloads: int = 0
    nsfw: bool = False
    obsolete: bool = False
    has_files: bool = True
    root_category: str = ""
    sub_category: str = ""
    version: str = ""
    thumb_url: str = ""
    image_urls: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"gb-{self.model}-{self.id}"

    @property
    def category_label(self) -> str:
        if self.root_category and self.sub_category and self.sub_category != self.root_category:
            return f"{self.root_category} › {self.sub_category}"
        return self.sub_category or self.root_category


@dataclass
class GBFile:
    id: int
    filename: str
    size: int = 0
    download_url: str = ""
    date_added: int = 0
    description: str = ""
    downloads: int = 0
    archived: bool = False
    md5: str = ""


@dataclass
class Details:
    submission: Submission
    text_html: str = ""
    files: list[GBFile] = field(default_factory=list)  # newest first, archived last


@dataclass
class Category:
    id: int
    name: str
    count: int = 0
    icon_url: str = ""
    children: list["Category"] = field(default_factory=list)


@dataclass
class Page:
    items: list[Submission]
    total: int
    complete: bool
    page: int


# --------------------------------------------------------------------- parsing

def _images(media) -> tuple[str, list[str]]:
    if not isinstance(media, dict):
        return "", []
    images = media.get("_aImages") or []
    thumb, full = "", []
    for i, img in enumerate(images):
        if not isinstance(img, dict):
            continue
        base = (img.get("_sBaseUrl") or "").rstrip("/")
        if not base.startswith("https://"):
            continue
        if img.get("_sFile"):
            full.append(f"{base}/{img['_sFile']}")
        if i == 0:
            small = img.get("_sFile530") or img.get("_sFile220") or img.get("_sFile")
            if small:
                thumb = f"{base}/{small}"
    return thumb, full


def parse_submission(raw: dict, model: str = "Mod") -> Submission:
    thumb, images = _images(raw.get("_aPreviewMedia"))
    submitter = raw.get("_aSubmitter") or {}
    root = raw.get("_aRootCategory") or raw.get("_aSuperCategory") or {}
    sub = raw.get("_aSubCategory") or raw.get("_aCategory") or {}
    return Submission(
        id=int(raw.get("_idRow") or 0),
        model=raw.get("_sModelName") or model,
        name=html.unescape(raw.get("_sName") or "Untitled"),
        url=raw.get("_sProfileUrl") or "",
        author=html.unescape(submitter.get("_sName") or "") if isinstance(submitter, dict) else "",
        author_id=int(submitter.get("_idRow") or 0) if isinstance(submitter, dict) else 0,
        date_added=int(raw.get("_tsDateAdded") or 0),
        date_modified=int(raw.get("_tsDateModified") or raw.get("_tsDateUpdated") or 0),
        likes=int(raw.get("_nLikeCount") or 0),
        views=int(raw.get("_nViewCount") or 0),
        downloads=int(raw.get("_nDownloadCount") or 0),
        nsfw=bool(raw.get("_bIsNsfw") or raw.get("_bHasContentRatings")),
        obsolete=bool(raw.get("_bIsObsolete")),
        has_files=bool(raw.get("_bHasFiles", True)),
        root_category=html.unescape(root.get("_sName") or "") if isinstance(root, dict) else "",
        sub_category=html.unescape(sub.get("_sName") or "") if isinstance(sub, dict) else "",
        version=str(raw.get("_sVersion") or ""),
        thumb_url=thumb,
        image_urls=images,
    )


def parse_file(raw: dict, archived: bool = False) -> GBFile:
    return GBFile(
        id=int(raw.get("_idRow") or 0),
        filename=raw.get("_sFile") or f"file-{raw.get('_idRow')}",
        size=int(raw.get("_nFilesize") or 0),
        download_url=raw.get("_sDownloadUrl") or f"https://gamebanana.com/dl/{raw.get('_idRow')}",
        date_added=int(raw.get("_tsDateAdded") or 0),
        description=html.unescape(raw.get("_sDescription") or ""),
        downloads=int(raw.get("_nDownloadCount") or 0),
        archived=archived or bool(raw.get("_bIsArchived")),
        md5=(raw.get("_sMd5Checksum") or "").lower(),
    )


def parse_category(raw: dict) -> Category:
    children = raw.get("_aChildren") or []
    if isinstance(children, dict):
        children = list(children.values())
    return Category(
        id=int(raw.get("_idRow") or 0),
        name=html.unescape(raw.get("_sName") or "?"),
        count=int(raw.get("_nItemCount") or 0),
        icon_url=raw.get("_sIconUrl") or "",
        children=[parse_category(c) for c in children if isinstance(c, dict)],
    )


def parse_url(text: str) -> tuple[str, int] | None:
    """'https://gamebanana.com/mods/649307' -> ('Mod', 649307)."""
    m = URL_RE.search(text or "")
    if not m:
        return None
    return ("Sound" if m.group(1).lower() == "sounds" else "Mod"), int(m.group(2))


def newest_file(files: list[GBFile]) -> GBFile | None:
    live = [f for f in files if not f.archived]
    pool = live or files
    return max(pool, key=lambda f: (f.date_added, f.id), default=None)


# ---------------------------------------------------------------------- client

class GameBananaClient:
    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir or paths.cache_dir()
        self.session = requests.Session()
        self.session.headers["User-Agent"] = f"Sapphire/{__version__} (Deadlock mod manager; Linux)"
        retry = Retry(total=3, backoff_factor=0.6, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=("GET",), respect_retry_after_header=True)
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=16)
        self.session.mount("https://", adapter)
        self._mem: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()

    # -- plumbing --------------------------------------------------------------
    def _get(self, path: str, params: dict | None = None, ttl: float = 90.0):
        url = f"{API}/{path}"
        key = url + "?" + json.dumps(params or {}, sort_keys=True)
        now = time.monotonic()
        with self._lock:
            hit = self._mem.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
        try:
            resp = self.session.get(url, params=params, timeout=(6, 25))
        except requests.RequestException as exc:
            raise GameBananaError(f"Couldn't reach GameBanana: {exc.__class__.__name__}") from exc
        if resp.status_code == 404:
            raise GameBananaError("That mod doesn't exist (or was removed).")
        if resp.status_code >= 400:
            raise GameBananaError(f"GameBanana returned HTTP {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise GameBananaError("GameBanana sent back something that isn't JSON") from exc
        if isinstance(data, dict) and data.get("_sErrorCode"):
            raise GameBananaError(f"GameBanana error: {data.get('_sMsg') or data['_sErrorCode']}")
        with self._lock:
            self._mem[key] = (now, data)
            if len(self._mem) > 400:
                for k in list(self._mem)[:100]:
                    self._mem.pop(k, None)
        return data

    # -- browsing ----------------------------------------------------------------
    def browse(self, model: str = "Mod", page: int = 1, per_page: int = 30, search: str = "",
             category_id: int | None = None, sort: str = "popular",
             submitter_id: int | None = None) -> Page:
        if model not in MODELS:
            raise ValueError(model)
        params = {
            "_idGameRow": GAME_ID,
            "_aFilters[Generic_Game]": GAME_ID,
            "_nPerpage": per_page,
            "_nPage": page,
            "_csvProperties": LIST_FIELDS,
        }
        if category_id:
            params["_aFilters[Generic_Category]"] = category_id
        if submitter_id:
            params["_aFilters[Generic_Submitter]"] = submitter_id
        if sort in SORTS:
            params["_sSort"] = SORTS[sort][1]
        search = (search or "").strip()
        if search:
            params.update({"_sSearchString": search, "_sModelName": model,
                           "_aFilters[itemtype]": model})
            path = "Util/Search/Results"
        else:
            path = f"{model}/Index"
        data = self._get(path, params)
        records = data if isinstance(data, list) else data.get("_aRecords") or []
        meta = {} if isinstance(data, list) else data.get("_aMetadata") or {}
        items = []
        for raw in records:
            if not isinstance(raw, dict):
                continue
            game = raw.get("_aGame")
            # Belt and braces: never show another game's mods.
            if isinstance(game, dict) and game.get("_idRow") and int(game["_idRow"]) != GAME_ID:
                continue
            if raw.get("_sModelName") and raw["_sModelName"] not in MODELS:
                continue
            items.append(parse_submission(raw, model))
        return Page(items=items, total=int(meta.get("_nRecordCount") or len(items)),
                    complete=bool(meta.get("_bIsComplete", True)), page=page)

    def categories(self, model: str = "Mod") -> list[Category]:
        """Category tree (e.g. Skins › Haze). Cached on disk for a day."""
        cache = self.cache_dir / f"categories-{model}.json"
        try:
            if cache.is_file() and time.time() - cache.stat().st_mtime < 86400:
                raw = json.loads(cache.read_text())
                return [parse_category(c) for c in raw]
        except (OSError, ValueError):
            pass
        try:
            data = self._get(f"Util/{model}Category/NestedStructure", {"_idGameRow": GAME_ID}, ttl=3600)
        except GameBananaError:
            if cache.is_file():  # stale cache beats nothing when offline
                try:
                    return [parse_category(c) for c in json.loads(cache.read_text())]
                except (OSError, ValueError):
                    pass
            raise
        raw = data if isinstance(data, list) else list(data.values()) if isinstance(data, dict) else []
        raw = [c for c in raw if isinstance(c, dict)]
        try:
            cache.write_text(json.dumps(raw))
        except OSError:
            pass
        return [parse_category(c) for c in raw]

    def details(self, model: str, mod_id: int) -> Details:
        # ProfilePage returns the whole record (files, archived files, text, categories).
        # The field-picking form (?_csvProperties=...) rejects several names, so avoid it here.
        data = self._get(f"{model}/{int(mod_id)}/ProfilePage", ttl=60)
        if not isinstance(data, dict):
            raise GameBananaError("Unexpected response for mod details")
        game = data.get("_aGame")
        if isinstance(game, dict) and game.get("_idRow") and int(game["_idRow"]) != GAME_ID:
            raise GameBananaError("That isn't a Deadlock mod.")
        if data.get("_bIsTrashed") or data.get("_bIsWithheld"):
            raise GameBananaError("This mod has been removed from GameBanana.")
        sub = parse_submission(data, model)
        files = [parse_file(f) for f in data.get("_aFiles") or [] if isinstance(f, dict)]
        files += [parse_file(f, archived=True) for f in data.get("_aArchivedFiles") or []
                  if isinstance(f, dict)]
        files.sort(key=lambda f: (f.archived, -f.date_added, -f.id))
        return Details(submission=sub, text_html=data.get("_sText") or "", files=files)

    def files(self, model: str, mod_id: int) -> list[GBFile]:
        """Just the file list (archived ones flagged). Cheap, used by update checks."""
        data = self._get(f"{model}/{int(mod_id)}", {"_csvProperties": "_idRow,_aFiles"}, ttl=30)
        if not isinstance(data, dict):
            raise GameBananaError("Unexpected response for mod files")
        return [parse_file(f) for f in data.get("_aFiles") or [] if isinstance(f, dict)]

    # -- downloading -------------------------------------------------------------
    def download(self, file: GBFile, dest_dir: Path,
                 progress: Callable[[int, int], None] | None = None,
                 cancel: threading.Event | None = None) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w.\- ]+", "_", file.filename).strip() or f"file-{file.id}"
        target = dest_dir / safe
        part = target.with_name(target.name + ".part")
        try:
            with self.session.get(file.download_url, stream=True, timeout=(8, 60)) as resp:
                if resp.status_code >= 400:
                    raise GameBananaError(f"Download failed (HTTP {resp.status_code})")
                total = int(resp.headers.get("Content-Length") or file.size or 0)
                done = 0
                md5 = hashlib.md5()
                with open(part, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=256 * 1024):
                        if cancel is not None and cancel.is_set():
                            raise Cancelled()
                        if not chunk:
                            continue
                        fh.write(chunk)
                        md5.update(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, total)
        except requests.RequestException as exc:
            part.unlink(missing_ok=True)
            raise GameBananaError(f"Download interrupted: {exc.__class__.__name__}") from exc
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        if total and done != total:
            part.unlink(missing_ok=True)
            raise GameBananaError("Download was incomplete, try again")
        if file.md5 and len(file.md5) == 32 and md5.hexdigest() != file.md5:
            part.unlink(missing_ok=True)
            raise GameBananaError("Downloaded file failed its checksum, try again")
        part.replace(target)
        return target

    def fetch_bytes(self, url: str, timeout: float = 15) -> bytes:
        resp = self.session.get(url, timeout=(5, timeout))
        resp.raise_for_status()
        return resp.content
