#!/usr/bin/env python3
"""Archive Metafy guides you have purchased into PDFs.

For each guide this saves, under guides/<guide title>/:
  <guide title> - <date time>.pdf   every chapter in one readable PDF, video links included
  guide.html                        the same content as a web page (uses the images/ folder)
  images/                           every image from the guide (downscaled for a sane PDF size)
  videos/                           Metafy-hosted videos, saved as MP4 while their stream links are valid
  videos.md                         every video link found, grouped by chapter
  source.json                       section titles, URLs, video links and the author, as data

Usage:
  python metafy_archiver.py                 # log in, open your library, archive everything
  python metafy_archiver.py URL [URL ...]   # archive specific guides
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import BrowserContext, Page, sync_playwright

from mfa_common import (SKIP_PATH_RE, clean_url, guide_base, hash_text, human_duration, human_size,  # noqa: F401 (re-exported)
                        launch_or_install, log, pdf_name, safe_name, strip_site)
from mfa_media import (ImageStore, Image, download_video, find_ffmpeg, is_media_url, link_expiry,  # noqa: F401
                       merge_videos, never_download, shrink_image, stable_key, video_host)
from mfa_output import (DEFAULT_THEME, THEMES, changes_text, diff_sections, place_images, place_videos,  # noqa: F401
                        render_pdf, write_outputs)

HERE = Path(__file__).resolve().parent
PROFILE_DIR = HERE / ".browser-profile"
STATE_FILE = HERE / ".state.json"
START_URL = "https://metafy.gg/"
LIBRARY_URL = "https://metafy.gg/account/purchases/guides"  # where Metafy lists the guides you bought
MEDIA_RE = re.compile(
    r"\.(m3u8|mpd|mp4|webm|mov)(\?|$)|stream\.mux\.com|videodelivery\.net|cloudflarestream\.com"
    r"|player\.vimeo\.com/video|youtube(-nocookie)?\.com/embed",
    re.I,
)

# Browser-side scripts live in js/ so they can be edited and linted as JavaScript.
JS = {p.stem: p.read_text(encoding="utf-8") for p in (HERE / "js").glob("*.js")}


# ----------------------------------------------------------------------------- browser helpers

def settle(page: Page, expand: bool = True) -> None:
    """Wait for the app to render, open collapsed bits and trigger lazy loading.

    We wait for the content element rather than 'network idle': analytics beacons keep most
    sites from ever going idle, which used to cost ~15 s per section.
    """
    with contextlib.suppress(Exception):
        page.wait_for_selector("article, main, [role=main]", timeout=10_000)
    for name in (("expand",) if expand else ()) + ("scroll",):
        try:
            page.evaluate(JS[name])
        except Exception as e:  # navigation mid-script etc.
            log(f"    (note: page script interrupted: {str(e).splitlines()[0][:80]})")
    with contextlib.suppress(Exception):
        page.wait_for_load_state("networkidle", timeout=3_000)


def evaluate_retry(page: Page, js: str, arg=None, tries: int = 2):
    """page.evaluate, retried once after re-settling: a late redirect can kill the first attempt."""
    for attempt in range(1, tries + 1):
        try:
            return page.evaluate(js, arg) if arg is not None else page.evaluate(js)
        except Exception as e:
            if attempt == tries:
                raise
            log(f"    (retrying page script: {str(e).splitlines()[0][:80]})")
            settle(page, expand=False)


def login_state(page: Page) -> str:
    """'in', 'out' or 'unknown' (heuristic)."""
    try:
        return page.evaluate(JS["login"])
    except Exception:
        return "unknown"


def ensure_logged_in(page: Page, args, first_run: bool) -> None:
    """Pause for login when the saved session is missing, expired, or --login was passed."""
    try:
        page.goto(START_URL, wait_until="domcontentloaded", timeout=60_000)
        settle(page, expand=False)
    except Exception:
        pass
    state = login_state(page)
    if not (first_run or args.login or state == "out"):
        return
    why = "no saved session" if first_run else ("--login" if args.login else "the saved session looks logged out")
    if args.headless:
        raise SystemExit(f"Login needed ({why}) but --headless has no window to log in with. Run once without --headless.")
    prompt = f"\nLogin needed ({why}). Log in to Metafy in the browser window, then press Enter here... "
    for _ in range(3):
        answer = input(prompt).strip().lower()
        if answer in ("q", "quit", "skip"):
            break
        with contextlib.suppress(Exception):
            page.goto(START_URL, wait_until="domcontentloaded", timeout=60_000)
            settle(page, expand=False)
        if login_state(page) != "out":
            return
        prompt = ("\nThe page still looks logged out, and paid sections will come out empty without a login.\n"
                  "Log in in the browser window and press Enter again (or type q to continue anyway)... ")
    log("WARNING: continuing without a login; locked sections will not be recorded as archived.")


def open_browser(pw, args) -> BrowserContext:
    """Your installed Google Chrome if possible (its profile looks least like automation), else the
    bundled Chromium, which is downloaded on the spot the first time."""
    kwargs = {
        "user_data_dir": str(args.profile), "headless": args.headless, "viewport": {"width": 1360, "height": 900},
        "args": ["--disable-blink-features=AutomationControlled"], "ignore_default_args": ["--enable-automation"],
    }
    if args.browser == "chrome":
        try:
            return pw.chromium.launch_persistent_context(channel="chrome", **kwargs)
        except Exception as e:
            log(f"Could not start Google Chrome ({str(e).splitlines()[0][:80]}); using bundled Chromium.")
    return launch_or_install(lambda: pw.chromium.launch_persistent_context(**kwargs))


def current_page(ctx: BrowserContext) -> Page:
    return ctx.pages[-1] if ctx.pages else ctx.new_page()


# ----------------------------------------------------------------------------- crawl

def resolve_out_dir(out_root: Path, title: str, base: str) -> Path:
    """Folder for this guide. Two guides with the same title must not share (and clobber) one folder."""
    slug = base.rsplit("/", 1)[-1]
    cand = out_root / safe_name(title, slug)
    src = cand / "source.json"
    if cand.exists() and src.exists():
        try:
            if json.loads(src.read_text(encoding="utf-8")).get("url") != base:
                cand = out_root / safe_name(f"{title} ({slug})", slug)
        except Exception:
            cand = out_root / safe_name(f"{title} ({slug})", slug)
    elif cand.exists() and any(cand.iterdir()):
        cand = out_root / safe_name(f"{title} ({slug})", slug)
    return cand


def load_source(d: Path | None) -> dict | None:
    try:
        return json.loads((d / "source.json").read_text(encoding="utf-8")) if d else None
    except Exception:
        return None


def archive_guide(ctx: BrowserContext, page: Page, base: str, out_root: Path, args,
                  prev_dir: Path | None = None, ffmpeg: str | None = None) -> dict | None:
    """Crawl every section of one guide and write guide.html, images/, videos/, videos.md, source.json.

    Returns {"dir", "pdf", "title", "changes"} (the PDF is not rendered here) or None if nothing was captured.
    """
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(base))
    base_path = urlsplit(base).path
    sniffed: list[str] = []

    def listener(req) -> None:
        if MEDIA_RE.search(req.url):
            sniffed.append(req.url)
    page.on("request", listener)

    queue, seen = [base], {base}
    chapters, text_hashes = [], set()
    locked = 0  # sections that came back nearly empty, usually a paywall seen while logged out
    nav_titles: dict[str, str] = {}  # section URL -> its label in the sidebar
    tmp_dir = out_root / f".partial-{hashlib.sha1(base.encode()).hexdigest()[:8]}"
    shutil.rmtree(tmp_dir, ignore_errors=True)  # left over from an interrupted run
    theme = getattr(args, "theme", DEFAULT_THEME)
    images = ImageStore(ctx, tmp_dir / "images", args.max_image_px, bg=THEMES[theme]["bg_rgb"])
    guide_title = author = ""
    video_files: dict[str, Path] = {}  # rel path -> where the file currently is
    consumed: set[Path] = set()  # earlier files replaced by a re-encoded copy
    want = "x264" if args.compress_videos else "copy"
    # Videos saved by an earlier run, keyed by what stays stable across runs (the Mux playback id),
    # not by file name: sections get inserted and renumber everything after them.
    prev_videos: dict[str, dict] = {}
    prev_source = load_source(prev_dir)
    if prev_dir and prev_source:
        for s in prev_source.get("sections", []):
            for pv in s.get("videos", []):
                f = prev_dir / pv["file"] if pv.get("file") else None
                if f and f.exists() and f.stat().st_size > 10_000:
                    prev_videos[stable_key(pv["url"])] = {"path": f, "encoded": pv.get("encoded", "copy")}

    def in_guide(u: str) -> bool:
        p = urlsplit(u).path
        return (u.startswith(origin) and (p == base_path or p.startswith(base_path + "/"))
                and not SKIP_PATH_RE.search(p))

    def fetch_video(v: dict, chapter_no: int, chapter_title: str, k: int, referer: str) -> None:
        """Save this video if it is a Metafy-hosted stream; annotate v with file/encoded/note."""
        exp = f" (stream link expires {v['expires'].replace('T', ' ')})" if v.get("expires") else ""
        if args.no_videos:
            v["note"] = "not downloaded (--no-videos)" + exp
            return
        if not ffmpeg:
            v["note"] = "not downloaded: ffmpeg not found" + exp
            return
        name = safe_name(f"{chapter_no:02d}-{chapter_title}") + (f"-{k}" if k else "") + ".mp4"
        rel = f"videos/{name}"
        prev = prev_videos.get(stable_key(v["url"]))
        if prev and not (args.compress_videos and prev["encoded"] != "x264"):
            renamed = "" if prev["path"].name == name else f" (was {prev['path'].name})"
            log(f"    video already saved earlier: {name}{renamed}")
            v["file"], v["encoded"] = rel, prev["encoded"]
            video_files[rel] = prev["path"]
            return
        if prev:
            log(f"    compressing the copy saved earlier -> {name} (no download)")
            source = str(prev["path"])
        else:
            log(f"    downloading {v['host']} video -> {name}" + (" (compressing)" if args.compress_videos else ""))
            source = v["url"]
        if download_video(ffmpeg, source, tmp_dir / "videos" / name, referer,
                          max_height=args.video_max_height, compress=args.compress_videos):
            v["file"], v["encoded"] = rel, want
            video_files[rel] = tmp_dir / "videos" / name
            if prev:
                consumed.add(prev["path"])
        else:
            v["note"] = "download failed; only the link is kept" + exp

    try:
        while queue:
            if len(chapters) >= args.max_pages:
                log(f"    stopping at --max-pages={args.max_pages}; {len(queue)} section(s) not archived")
                break
            url = queue.pop(0)
            sniffed.clear()
            log(f"  - {url.replace(origin, '')}")
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            except Exception as e:
                log(f"    could not load: {str(e).splitlines()[0][:100]}")
                continue
            if resp is not None and resp.status >= 400:
                log(f"    could not load: HTTP {resp.status}" + (" (is the URL right?)" if url == base else ""))
                continue
            settle(page)

            # Sibling sections: the sidebar's order is the guide's order, so enqueue those first.
            links = evaluate_retry(page, JS["links"])
            fresh = []
            for link in sorted(links, key=lambda lnk: not lnk["nav"]):
                u = clean_url(link["href"])
                if not in_guide(u):
                    continue
                if link["nav"] and link["text"] and u not in nav_titles:
                    nav_titles[u] = link["text"].splitlines()[0]
                if u not in seen:
                    seen.add(u)
                    fresh.append(u)
            queue += fresh

            data = evaluate_retry(page, JS["extract"], {"selector": args.selector, "basePath": base_path})
            guide_title = guide_title or data["guideTitle"]
            author = author or data["author"]
            digest = hashlib.sha1(hash_text(data["text"]).encode()).hexdigest()
            if digest in text_hashes:
                log("    same content as an earlier page, skipped")
                continue
            text_hashes.add(digest)
            if len(data["text"]) < 200 and not data["images"] and not data["videos"]:
                log("    WARNING: almost no content here (locked, or not loaded?)")
                locked += 1

            title = (nav_titles.get(url) if url != base else "") or data["title"] \
                or strip_site(data["docTitle"]) or url.rsplit("/", 1)[-1]
            saved = images.get_many(data["images"], url)
            body = place_images(data["html"], data["images"], saved)

            videos = merge_videos(data["videos"], sniffed, data.get("ignore", []))
            n_media = 0
            for v in videos:
                if not never_download(v) and v["kind"] in ("stream", "video") and is_media_url(v["url"]):
                    fetch_video(v, len(chapters) + 1, title, n_media, url)
                    n_media += 1
            body = place_videos(body, videos)

            chapters.append({"url": url, "title": title, "html": body, "videos": videos, "hash": digest})
            missing = sum(1 for s in saved if not s)
            n_saved = sum(1 for v in videos if v.get("file"))
            log(f"    {len(data['text']):,} chars, {len(saved) - missing}/{len(saved)} images, "
                f"{len(videos)} videos ({n_saved} saved)")
            if queue:
                time.sleep(args.delay)
    except BaseException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    finally:
        page.remove_listener("request", listener)

    if not chapters:
        log("  nothing captured for this guide")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None

    guide_title = guide_title or chapters[0]["title"] or base.rsplit("/", 1)[-1]
    out_dir = resolve_out_dir(out_root, guide_title, base)
    changes = diff_sections(load_source(prev_dir) or load_source(out_dir), chapters)
    if changes:
        log("  " + changes_text(changes))
    out_dir.mkdir(parents=True, exist_ok=True)
    # Replace the previous html/images, but keep earlier PDFs: they are timestamped versions.
    shutil.rmtree(out_dir / "images", ignore_errors=True)
    if (tmp_dir / "images").exists():
        (tmp_dir / "images").rename(out_dir / "images")
    # Videos are big: move new ones in, rename reused ones that changed number, copy from another
    # folder only if the guide's folder itself changed; never re-download what we have.
    for rel, src in video_files.items():
        dest = out_dir / rel
        if not src.exists() or src.resolve() == dest.resolve():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_relative_to(tmp_dir) or src.is_relative_to(out_dir):
            src.replace(dest)
        else:
            shutil.copy2(src, dest)
    kept = {(out_dir / rel).resolve() for rel in video_files}
    for f in consumed:
        if f.resolve() not in kept:  # a re-encode often lands on the same name it replaces
            f.unlink(missing_ok=True)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    if (out_dir / "videos").is_dir():
        orphans = sorted(f.name for f in (out_dir / "videos").glob("*.mp4") if f"videos/{f.name}" not in video_files)
        if orphans:
            log(f"  note: videos/ also holds {len(orphans)} file(s) no section refers to any more: {', '.join(orphans)[:200]}")

    now = dt.datetime.now()
    pdf = out_dir / pdf_name(guide_title, now)
    write_outputs(out_dir, guide_title, author, base, chapters, now, pdf.name, changes,
                  theme=theme, paper=getattr(args, "paper", "Letter"))
    return {"dir": out_dir, "pdf": pdf, "title": guide_title, "changes": changes, "locked": locked}


LOAD_MORE_RE = r"^(load|show|see|view)\s+(more|all)(\s+guides)?$"


def expand_listing(page: Page, max_clicks: int = 50) -> int:
    """Click 'Load more' style buttons until the page stops growing. Returns the number of clicks."""
    clicks = 0
    for _ in range(max_clicks):
        before = page.evaluate("() => document.querySelectorAll('a[href]').length")
        clicked = page.evaluate(
            """re => { const rx = new RegExp(re, 'i');
                      const b = [...document.querySelectorAll('button, a, [role=button]')]
                        .find(e => rx.test((e.innerText || '').trim()) && e.getBoundingClientRect().height > 0);
                      if (!b) return false; b.scrollIntoView(); b.click(); return true; }""", LOAD_MORE_RE)
        if not clicked:
            break
        clicks += 1
        try:
            page.wait_for_function("n => document.querySelectorAll('a[href]').length > n", arg=before, timeout=8_000)
        except Exception:
            break  # the button is still there but nothing new appeared
    if clicks:
        log(f"  (clicked 'Load more' {clicks} time{'s' if clicks != 1 else ''})")
        settle(page, expand=False)
    return clicks


def find_guides(page: Page, args) -> list[tuple[str, str]]:
    """Collect guide links from whatever page the user has opened (their library)."""
    settle(page, expand=False)
    expand_listing(page)
    found: dict[str, str] = {}
    for link in evaluate_retry(page, JS["links"]):
        base = guide_base(link["href"])
        if base and (not args.match or re.search(args.match, base, re.I)):
            if len(link["text"]) > len(found.get(base, "")):
                found[base] = link["text"].splitlines()[0] if link["text"] else ""
            found.setdefault(base, "")
    return list(found.items())


# ----------------------------------------------------------------------------- state

def previous_dir(entry, out_root: Path) -> Path | None:
    """The folder an earlier run used for this guide, if it still exists."""
    if isinstance(entry, str):
        return Path(entry) if Path(entry).is_dir() else None
    if isinstance(entry, dict) and entry.get("dir"):
        d = out_root / entry["dir"]
        return d if d.is_dir() else None
    return None


def previous_pdf(entry, out_root: Path) -> Path | None:
    """Where an earlier run put this guide's PDF, if it is still there.

    Entries are {"dir": ..., "pdf": ...} relative to the output folder; older state files stored an
    absolute folder path whose PDF was always guide.pdf.
    """
    if isinstance(entry, str):
        d = Path(entry)
        pdfs = sorted(d.glob("*.pdf")) if d.is_dir() else []
        return pdfs[-1] if pdfs else None
    if isinstance(entry, dict) and entry.get("pdf"):
        p = out_root / entry["pdf"]
        return p if p.exists() else None
    return None


def dir_size(d: Path) -> int:
    return sum(p.stat().st_size for p in d.rglob("*") if p.is_file()) if d.is_dir() else 0


# ----------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="*", help="guide URLs to archive (default: every guide linked from your library page)")
    ap.add_argument("-o", "--out", type=Path, default=HERE / "guides", help="output folder (default: ./guides)")
    ap.add_argument("--force", action="store_true", help="re-download guides that were already archived")
    ap.add_argument("--login", action="store_true", help="pause for login even if a saved session exists")
    ap.add_argument("--match", help="only archive guides whose URL matches this regex")
    ap.add_argument("--selector", help="CSS selector of the guide content, if auto-detection grabs the wrong area")
    ap.add_argument("--paper", default="Letter", choices=["Letter", "A4"], help="PDF paper size")
    ap.add_argument("--theme", default=DEFAULT_THEME, choices=sorted(THEMES),
                    help="PDF look: 'dark' matches Metafy (default), 'light' is plain paper")
    ap.add_argument("--max-image-px", type=int, default=1600,
                    help="downscale images to this many pixels on the long side; 0 keeps originals (default 1600)")
    ap.add_argument("--no-videos", action="store_true", help="don't download Metafy-hosted videos, keep links only")
    ap.add_argument("--video-max-height", type=int, default=720, metavar="PX",
                    help="pick the stream variant at most this tall, e.g. 480 (default 720); no re-encoding")
    ap.add_argument("--compress-videos", action="store_true",
                    help="re-encode videos with x264 at up to 30 fps and --video-max-height (about a third smaller, slower)")
    ap.add_argument("--ffmpeg", help="path to ffmpeg (default: PATH, then the imageio-ffmpeg package)")
    ap.add_argument("--delay", type=float, default=1.5, help="seconds to wait between pages (default 1.5)")
    ap.add_argument("--max-pages", type=int, default=300, help="max sections per guide")
    ap.add_argument("--browser", default="chrome", choices=["chrome", "chromium"])
    ap.add_argument("--library-url", help="page that lists your purchased guides (remembered after the first run)")
    ap.add_argument("--profile", type=Path, default=PROFILE_DIR, help=argparse.SUPPRESS)
    ap.add_argument("--headless", action="store_true", help="run without a window (only once you're logged in)")
    args = ap.parse_args()
    args.out = args.out.expanduser()
    for stream in (sys.stdout, sys.stderr):  # Windows consoles may not be UTF-8; never crash on a "·"
        with contextlib.suppress(Exception):
            stream.reconfigure(errors="replace")
    bad = [u for u in args.urls if not guide_base(u)]
    if bad:
        log("These don't look like Metafy guide links (expected https://metafy.gg/guides/view/<guide>...):")
        for u in bad:
            log(f"  {u}")
        return 2

    t_start = time.time()
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    first_run = not args.profile.exists()
    args.out.mkdir(parents=True, exist_ok=True)
    out_root = args.out.resolve()
    ffmpeg = None if args.no_videos else find_ffmpeg(args.ffmpeg)
    if not args.no_videos and not ffmpeg:
        log("Note: no usable ffmpeg found, so Metafy-hosted videos will be kept as (expiring) links only.\n"
            "      Fix: .venv/bin/pip install imageio-ffmpeg   or   brew install ffmpeg")
    if args.max_image_px > 0 and Image is None:
        log("Note: Pillow is not installed, so images are kept at full size (pip install Pillow).")

    with sync_playwright() as pw:
        ctx = open_browser(pw, args)
        page = current_page(ctx)
        try:
            targets: list[tuple[str, str]] = []
            if args.urls:
                ensure_logged_in(page, args, first_run)
                page = current_page(ctx)
                targets = [(guide_base(u), "") for u in args.urls]
            else:
                with contextlib.suppress(Exception):
                    page.goto(args.library_url or state.get("library_url") or LIBRARY_URL, wait_until="domcontentloaded", timeout=60_000)
                log("\nIn the browser window that just opened:")
                log("  1. Log in to Metafy (only needed the first time).")
                log("  2. Make sure the page lists the guides you've purchased (Account > Purchases > Guides).")
                input("Then press Enter here... ")
                page = current_page(ctx)
                if login_state(page) == "out":
                    log("WARNING: the page looks logged out; paid sections may come out empty.")
                state["library_url"] = page.url
                STATE_FILE.write_text(json.dumps(state, indent=2))
                targets = find_guides(page, args)
                if not targets:
                    dump = args.out / "library-debug.html"
                    dump.write_text(page.content(), encoding="utf-8")
                    log(f"\nNo guide links found on {page.url}")
                    log(f"Saved that page to {dump} for troubleshooting.")
                    log("You can also pass guide URLs directly:  python metafy_archiver.py <guide-url> ...")
                    return 1
                log(f"\nFound {len(targets)} guide(s):")
                for i, (u, t) in enumerate(targets, 1):
                    log(f"  {i:2d}. {t or u.rsplit('/', 1)[-1]}\n      {u}")

            done = state.setdefault("done", {})
            ok = failed = skipped = 0
            for n, (base, label) in enumerate(targets, 1):
                prev = previous_pdf(done.get(base), out_root)
                if prev and not args.force:
                    log(f"\n[{n}/{len(targets)}] already archived, skipping (--force to redo): {prev}")
                    skipped += 1
                    continue
                log(f"\n[{n}/{len(targets)}] {label or base}")
                t0 = time.time()
                try:
                    res = archive_guide(ctx, page, base, out_root, args,
                                        prev_dir=previous_dir(done.get(base), out_root), ffmpeg=ffmpeg)
                    if not res:
                        failed += 1
                        continue
                    render_pdf(pw, res["dir"], res["pdf"], res["title"], args.paper)
                    if res["locked"]:
                        log(f"  WARNING: {res['locked']} section(s) came out empty (locked?). This guide is NOT marked as done;\n"
                            f"           the next run will redo it. If you were logged out, run again with --login.")
                        done.pop(base, None)
                    else:
                        done[base] = {"dir": str(res["dir"].relative_to(out_root)),
                                      "pdf": str(res["pdf"].relative_to(out_root))}
                    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
                    sizes = [f"PDF {human_size(res['pdf'].stat().st_size)}",
                             f"images {human_size(dir_size(res['dir'] / 'images'))}"]
                    if (res["dir"] / "videos").is_dir():
                        sizes.append(f"videos {human_size(dir_size(res['dir'] / 'videos'))}")
                    log(f"  saved: {res['pdf']}")
                    log(f"  {' · '.join(sizes)} · {human_duration(time.time() - t0)}")
                    ok += 1
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    failed += 1
                    log(f"  FAILED: {str(e).splitlines()[0][:200]}")
            log(f"\nDone in {human_duration(time.time() - t_start)}. {ok} archived, {skipped} skipped, {failed} failed. Output: {out_root}")
            return 0 if not failed else 2
        except KeyboardInterrupt:
            log("\nStopped.")
            return 130
        finally:
            with contextlib.suppress(Exception):
                ctx.close()


if __name__ == "__main__":
    sys.exit(main())
