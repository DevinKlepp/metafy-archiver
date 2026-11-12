"""Small helpers shared by the archiver modules."""
from __future__ import annotations

import datetime as dt
import re
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit

# /guides/view/<slug>, /guides/<slug>, /@coach/guides/<slug> ...
GUIDE_RE = re.compile(r"^(?P<base>(?:/[^/]+)*?/guides?/(?:view/)?(?P<slug>[^/]+))", re.I)
NOT_A_SLUG = {"view", "discover", "browse", "search", "new", "all", "popular", "create"}
SKIP_PATH_RE = re.compile(r"/(checkout|purchase|buy|gift|share|reviews?|edit|settings)(/|$)", re.I)


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


def safe_name(name: str, fallback: str = "guide") -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:110] or fallback


def strip_site(title: str) -> str:
    return re.sub(r"\s*[|\-–—]\s*Metafy.*$", "", title or "", flags=re.I).strip()


def pdf_name(title: str, when: dt.datetime) -> str:
    """'<title> - 2026-11-11 2153.pdf' (no colons: they are illegal on Windows and awkward in Finder)."""
    return safe_name(f"{title} - {when:%Y-%m-%d %H%M}") + ".pdf"


def launch_or_install(launch):
    """Call a Playwright launch function; if its browser is missing, install Chromium once and retry.

    This is what lets a fresh download work without anyone knowing the `playwright install` step.
    """
    try:
        return launch()
    except Exception as e:
        if not any(s in str(e) for s in ("Executable doesn't exist", "playwright install")):
            raise
        log("Downloading the browser Playwright needs (one time, about 150 MB)...")
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)
        return launch()


def human_size(n: int | float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def human_duration(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"
