"""Small helpers shared by the archiver modules."""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

# /guides/view/<slug>, /guides/<slug>, /@coach/guides/<slug> ...
GUIDE_RE = re.compile(r"^(?P<base>(?:/[^/]+)*?/guides?/(?:view/)?(?P<slug>[^/]+))", re.I)
NOT_A_SLUG = {"view", "discover", "browse", "search", "new", "all", "popular", "create"}
SKIP_PATH_RE = re.compile(r"/(checkout|purchase|buy|gift|share|reviews?|edit|settings)(/|$)", re.I)
WINDOWS_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)", re.I)


def log(msg: str = "") -> None:
    print(msg, flush=True)


def clean_url(url: str) -> str:
    s = urlsplit(url)
    return urlunsplit((s.scheme, s.netloc, s.path.rstrip("/") or "/", "", ""))


def guide_base(url: str) -> str | None:
    """Return the guide's root URL if this looks like a guide (or chapter) link."""
    s = urlsplit(url)
    if s.scheme not in ("http", "https"):
        return None
    m = GUIDE_RE.match(s.path)
    if not m or m.group("slug").lower() in NOT_A_SLUG or SKIP_PATH_RE.search(s.path):
        return None
    return urlunsplit((s.scheme, s.netloc, m.group("base"), "", ""))


def safe_name(name: str, fallback: str = "guide", limit: int = 80) -> str:
    """A file or folder name that is legal on macOS, Linux and Windows.

    80 characters keeps `...\\guides\\<title>\\<title> - <stamp>.pdf` under Windows' 260-character
    path limit for any reasonable download location.
    """
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    name = name[:limit].strip(" .") or fallback
    if WINDOWS_RESERVED.match(name):  # "CON", "aux.txt" ... cannot be created on Windows
        name += "_"
    return name


def strip_site(title: str) -> str:
    return re.sub(r"\s*[|\-–—]\s*Metafy.*$", "", title or "", flags=re.I).strip()


def pdf_name(title: str, when: dt.datetime) -> str:
    """'<title> - 2026-11-11 2153.pdf' (no colons: they are illegal on Windows and awkward in Finder)."""
    return safe_name(f"{title} - {when:%Y-%m-%d %H%M}") + ".pdf"


def launch_or_install(launch, fallback=None):
    """Call a Playwright launch function; if its browser is missing, install Chromium once and retry.

    This is what lets a fresh download work without anyone knowing the `playwright install` step.
    `fallback` (another launch function, typically the installed Google Chrome) is tried when
    the bundled browser still cannot be installed or started, for example on a Linux release
    Playwright does not support yet.
    """
    def missing(e):
        return any(s in str(e) for s in ("Executable doesn't exist", "playwright install"))
    try:
        return launch()
    except Exception as e:
        if not missing(e):
            raise
    log("Downloading the browser Playwright needs (one time, about 150 MB)...")
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)
    try:
        return launch()
    except Exception as e:
        if fallback is None:
            raise
        log(f"Bundled browser unavailable ({str(e).splitlines()[0]}); trying Google Chrome instead")
        return fallback()


VOLATILE_RES = [
    # live counters on a guide's cover: "130+ ratings", "330+ purchases", "758 reviews"
    re.compile(r"\b\d[\d,.]*\s*\+?\s*(ratings?|purchases?|reviews?|students?|members?|sales|enrolled|views?)\b", re.I),
    # relative times: "13 hours ago", "a day ago", "just now"
    re.compile(r"\b(\d+|an?)\s+(second|minute|hour|day|week|month|year)s?\s+ago\b|\bjust now\b|\byesterday\b", re.I),
]


def hash_text(text: str) -> str:
    """Section text with the bits that change on their own blanked out, so re-runs only report real edits."""
    for rx in VOLATILE_RES:
        text = rx.sub("#", text)
    return re.sub(r"\s+", " ", text).strip()


def zip_folder(folder: Path) -> Path:
    """Pack a guide folder into <folder>.zip next to it (rebuilt each time).

    Media files are already compressed, so they are stored as-is; that makes zipping a
    250 MB guide a matter of seconds rather than minutes. Written to a .part file first so an
    interrupted run never leaves a truncated zip behind.
    """
    import zipfile
    # Not with_suffix(): "v1.2 Guide" would become "v1.zip".
    dest = folder.parent / (folder.name + ".zip")
    part = folder.parent / (folder.name + ".zip.part")
    stored = {".mp4", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf", ".avif"}
    with zipfile.ZipFile(part, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file() and not p.name.startswith("."):
                z.write(p, p.relative_to(folder.parent),
                        compress_type=zipfile.ZIP_STORED if p.suffix.lower() in stored else zipfile.ZIP_DEFLATED)
    part.replace(dest)
    return dest


def load_state(path: Path) -> dict:
    """The run state ({"done": {...}, "library_url": ...}); a damaged file is set aside, not fatal."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
        raise ValueError("not an object")
    except Exception as e:
        backup = path.with_name(path.name + ".broken")
        path.replace(backup)
        log(f"Note: {path.name} could not be read ({str(e)[:60]}); moved to {backup.name} and starting fresh.\n"
            f"      Guides already archived will be redone unless you restore it.")
        return {}


def save_state(path: Path, state: dict) -> None:
    """Write via a temporary file so an interrupted run never leaves a half-written state behind."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def human_size(n: int | float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def human_duration(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"
