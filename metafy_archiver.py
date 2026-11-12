#!/usr/bin/env python3
"""Archive Metafy guides you have purchased into PDFs.

For each guide this saves, under guides/<guide title>/:
  <guide title> - <date time>.pdf   every chapter in one readable PDF, video links included
  guide.html                        the same content as a web page (uses the images/ folder)
  images/                           every image from the guide
  videos.md                         every video link found, grouped by chapter
  source.json                       section titles, URLs, video links and the author, as data

Usage:
  python metafy_archiver.py                 # log in, open your library, archive everything
  python metafy_archiver.py URL [URL ...]   # archive specific guides
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import mimetypes
import re
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from playwright.sync_api import BrowserContext, Page, sync_playwright

HERE = Path(__file__).resolve().parent
PROFILE_DIR = HERE / ".browser-profile"
STATE_FILE = HERE / ".state.json"
START_URL = "https://metafy.gg/"

# /guides/view/<slug>, /guides/<slug>, /@coach/guides/<slug> ...
GUIDE_RE = re.compile(r"^(?P<base>(?:/[^/]+)*?/guides?/(?:view/)?(?P<slug>[^/]+))", re.I)
NOT_A_SLUG = {"view", "discover", "browse", "search", "new", "all", "popular", "create"}
SKIP_PATH_RE = re.compile(r"/(checkout|purchase|buy|gift|share|reviews?|edit|settings)(/|$)", re.I)
MEDIA_RE = re.compile(
    r"\.(m3u8|mpd|mp4|webm|mov)(\?|$)|stream\.mux\.com|videodelivery\.net|cloudflarestream\.com"
    r"|player\.vimeo\.com/video|youtube(-nocookie)?\.com/embed",
    re.I,
)
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif")

# Browser-side scripts live in js/ so they can be edited and linted as JavaScript.
JS = {p.stem: p.read_text(encoding="utf-8") for p in (HERE / "js").glob("*.js")}

CSS = """
@page { margin: 18mm 16mm; }
* { box-sizing: border-box; }
body { font: 11.5pt/1.55 -apple-system, "Helvetica Neue", Arial, sans-serif; color: #1a1a1a;
       max-width: 820px; margin: 0 auto; padding: 0 12px; overflow-wrap: anywhere; }
h1, h2, h3, h4 { line-height: 1.25; break-after: avoid; margin: 1.4em 0 .5em; }
h1 { font-size: 22pt; } h2 { font-size: 16pt; } h3 { font-size: 13pt; }
img, svg { max-width: 100%; height: auto; display: block; margin: 10px 0; break-inside: avoid; }
a { color: #1a55c4; }
pre, code { font: 9.5pt/1.4 Menlo, monospace; background: #f3f3f3; }
pre { padding: 10px; white-space: pre-wrap; }
table { border-collapse: collapse; margin: 12px 0; width: 100%; }
td, th { border: 1px solid #bbb; padding: 5px 8px; text-align: left; vertical-align: top; }
blockquote { border-left: 3px solid #999; margin: 12px 0; padding: 2px 14px; color: #444; }
.mfa-cover { padding: 60px 0 20px; }
.mfa-cover h1 { font-size: 30pt; margin: 0 0 12px; }
.mfa-meta { color: #555; font-size: 10pt; line-height: 1.7; }
.mfa-toc li { margin: 3px 0; }
.mfa-chapter { break-before: page; }
.mfa-chapter-src { color: #666; font-size: 9pt; margin-top: -4px; }
.mfa-video { border: 1px solid #9ab; border-left: 5px solid #1a55c4; background: #f2f6fc;
             padding: 8px 12px; margin: 12px 0; font-size: 10.5pt; break-inside: avoid; }
.mfa-video img { max-height: 220px; width: auto; }
.mfa-missing { border: 1px dashed #c66; color: #933; background: #fff5f5; padding: 8px 12px;
               margin: 10px 0; font-size: 9.5pt; }
.mfa-vlist { font-size: 10pt; }
.mfa-vlist li { margin: 4px 0; }
"""


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


def settle(page: Page, expand: bool = True) -> None:
    """Wait for the app to render, open collapsed bits and trigger lazy loading.

    We wait for the content element rather than 'network idle': analytics beacons keep most
    sites from ever going idle, which used to cost ~15 s per section.
    """
    try:
        page.wait_for_selector("article, main, [role=main]", timeout=10_000)
    except Exception:
        pass
    for name in (("expand",) if expand else ()) + ("scroll",):
        try:
            page.evaluate(JS[name])
        except Exception as e:  # navigation mid-script etc.
            log(f"    (note: page script interrupted: {str(e).splitlines()[0][:80]})")
    try:
        page.wait_for_load_state("networkidle", timeout=3_000)
    except Exception:
        pass


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
    input(f"\nLogin needed ({why}). Log in to Metafy in the browser window, then press Enter here... ")
    if login_state(page) == "out":
        log("WARNING: the page still looks logged out; paid sections may come out empty.")


def download_image(ctx: BrowserContext, url: str, img_dir: Path, referer: str, cache: dict) -> str | None:
    if url in cache:
        return cache[url]
    rel = None
    try:
        r = ctx.request.get(url, headers={"Referer": referer}, timeout=45_000)
        if r.ok:
            body = r.body()
            ctype = (r.headers.get("content-type") or "").split(";")[0].strip()
            ext = Path(urlsplit(url).path).suffix.lower()
            if ext not in IMAGE_EXTS:
                ext = mimetypes.guess_extension(ctype) or ".img"
            name = f"{len(cache) + 1:03d}-{hashlib.sha1(url.encode()).hexdigest()[:8]}{ext}"
            img_dir.mkdir(parents=True, exist_ok=True)
            (img_dir / name).write_bytes(body)
            rel = f"images/{name}"
        else:
            log(f"    image failed ({r.status}): {url[:90]}")
    except Exception as e:
        log(f"    image failed: {url[:90]} ({str(e).splitlines()[0][:60]})")
    cache[url] = rel
    return rel


def place_images(body: str, image_urls: list[str], saved: list[str | None]) -> str:
    """Swap MFAIMG_n_ placeholders for local paths; a visible note replaces images that failed."""
    for i, (img_url, rel) in enumerate(zip(image_urls, saved)):
        tag_re = re.compile(rf"<img\b[^>]*\bsrc=\"MFAIMG_{i}_\"[^>]*>")
        if rel:
            body = tag_re.sub(lambda m: m.group(0).replace(f"MFAIMG_{i}_", html.escape(rel, quote=True)), body)
        else:
            note = (f"<div class='mfa-missing'>Image not saved: "
                    f"<a href='{html.escape(img_url or '', quote=True)}'>{html.escape(img_url or '?')}</a></div>")
            body = tag_re.sub(note, body)
    return body


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


def archive_guide(ctx: BrowserContext, page: Page, base: str, out_root: Path, args) -> dict | None:
    """Crawl every section of one guide and write guide.html, images/, videos.md and source.json.

    Returns {"dir", "pdf", "title"} (the PDF is not rendered here) or None if nothing was captured.
    """
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(base))
    base_path = urlsplit(base).path
    sniffed: list[str] = []
    listener = lambda req: sniffed.append(req.url) if MEDIA_RE.search(req.url) else None
    page.on("request", listener)

    queue, seen = [base], {base}
    chapters, text_hashes, img_cache = [], set(), {}
    nav_titles: dict[str, str] = {}  # section URL -> its label in the sidebar
    tmp_dir = out_root / f".partial-{hashlib.sha1(base.encode()).hexdigest()[:8]}"
    shutil.rmtree(tmp_dir, ignore_errors=True)  # left over from an interrupted run
    guide_title = author = ""

    def in_guide(u: str) -> bool:
        p = urlsplit(u).path
        return (u.startswith(origin) and (p == base_path or p.startswith(base_path + "/"))
                and not SKIP_PATH_RE.search(p))

    try:
        while queue:
            if len(chapters) >= args.max_pages:
                log(f"    stopping at --max-pages={args.max_pages}; {len(queue)} section(s) not archived")
                break
            url = queue.pop(0)
            sniffed.clear()
            log(f"  - {url.replace(origin, '')}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            except Exception as e:
                log(f"    could not load: {str(e).splitlines()[0][:100]}")
                continue
            settle(page)

            # Sibling sections: the sidebar's order is the guide's order, so enqueue those first.
            links = evaluate_retry(page, JS["links"])
            fresh = []
            for link in sorted(links, key=lambda l: not l["nav"]):
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
            digest = hashlib.sha1(data["text"].encode()).hexdigest()
            if digest in text_hashes:
                log("    same content as an earlier page, skipped")
                continue
            text_hashes.add(digest)
            if len(data["text"]) < 200 and not data["images"] and not data["videos"]:
                log("    WARNING: almost no content here (locked, or not loaded?)")

            saved = [download_image(ctx, u, tmp_dir / "images", url, img_cache) if u else None for u in data["images"]]
            body = place_images(data["html"], data["images"], saved)

            videos = data["videos"]
            known = {v["url"] for v in videos}
            for s in dict.fromkeys(sniffed):
                m = re.search(r"/(?:embed|video)/([\w-]{6,})", s)
                if m and any(m.group(1) in k for k in known):
                    continue  # the same embed, already listed as a normal link
                if s not in known and not any(s.split("?")[0] in k for k in known):
                    videos.append({"url": s, "label": "stream captured while the page loaded", "kind": "stream"})
            title = (nav_titles.get(url) if url != base else "") or data["title"] \
                or strip_site(data["docTitle"]) or url.rsplit("/", 1)[-1]
            chapters.append({"url": url, "title": title, "html": body, "videos": videos})
            missing = sum(1 for s in saved if not s)
            log(f"    {len(data['text']):,} chars, {len(saved) - missing}/{len(saved)} images, {len(videos)} videos")
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
    out_dir.mkdir(parents=True, exist_ok=True)
    # Replace the previous html/images, but keep earlier PDFs: they are timestamped versions.
    shutil.rmtree(out_dir / "images", ignore_errors=True)
    if (tmp_dir / "images").exists():
        (tmp_dir / "images").rename(out_dir / "images")
    shutil.rmtree(tmp_dir, ignore_errors=True)

    now = dt.datetime.now()
    pdf = out_dir / pdf_name(guide_title, now)
    write_outputs(out_dir, guide_title, author, base, chapters, now, pdf.name)
    return {"dir": out_dir, "pdf": pdf, "title": guide_title}


def write_outputs(out_dir: Path, title: str, author: str, base: str, chapters: list[dict],
                  now: dt.datetime, pdf_file: str) -> None:
    esc = html.escape
    stamp = now.strftime("%Y-%m-%d %H:%M")
    n = len(chapters)
    parts = [
        f"<!doctype html><html><head><meta charset='utf-8'><title>{esc(title)}</title><style>{CSS}</style></head><body>",
        f"<div class='mfa-cover'><h1>{esc(title)}</h1><div class='mfa-meta'>"
        + (f"By {esc(author)}<br>" if author else "")
        + f"Source: <a href='{esc(base)}'>{esc(base)}</a><br>"
        f"{n} section{'s' if n != 1 else ''} &middot; archived {stamp} for personal use</div></div>",
    ]
    if n > 1:
        parts.append("<h2>Contents</h2><ol class='mfa-toc'>")
        parts += [f"<li><a href='#ch{i}'>{esc(c['title'])}</a></li>" for i, c in enumerate(chapters, 1)]
        parts.append("</ol>")
    md = [f"# Video links: {title}", ""] + ([f"By {author}  "] if author else []) + [
        f"Source: {base}  ", f"Archived: {stamp}", "",
        "Stream links (.m3u8/.mp4 with tokens) can expire; YouTube/Vimeo/Twitch links are stable.", ""]
    for i, c in enumerate(chapters, 1):
        parts.append(f"<section class='mfa-chapter' id='ch{i}'>")
        if n > 1:
            parts.append(f"<div class='mfa-chapter-src'>Section {i} of {n} &middot; "
                         f"<a href='{esc(c['url'])}'>{esc(c['url'])}</a></div>")
        parts.append(c["html"])
        if c["videos"]:
            parts.append("<h3>Videos in this section</h3><ul class='mfa-vlist'>")
            md += [f"## {i}. {c['title']}", ""]
            for v in c["videos"]:
                label = f"{esc(v['label'])}: " if v["label"] else ""
                parts.append(f"<li>{label}<a href='{esc(v['url'])}'>{esc(v['url'])}</a></li>")
                md.append(f"- {v['label'] + ': ' if v['label'] else ''}<{v['url']}>")
            parts.append("</ul>")
            md.append("")
        parts.append("</section>")
    parts.append("</body></html>")
    (out_dir / "guide.html").write_text("\n".join(parts), encoding="utf-8")
    if not any(c["videos"] for c in chapters):
        md.append("No video links were found in this guide.")
    (out_dir / "videos.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (out_dir / "source.json").write_text(json.dumps(
        {"title": title, "author": author, "url": base, "archived": now.isoformat(timespec="minutes"),
         "pdf": pdf_file,
         "sections": [{"title": c["title"], "url": c["url"], "videos": c["videos"]} for c in chapters]},
        indent=2, ensure_ascii=False), encoding="utf-8")


def render_pdf(pw, out_dir: Path, pdf_path: Path, title: str, paper: str) -> None:
    """Render the saved guide.html to PDF with a separate headless browser (no login needed)."""
    browser = pw.chromium.launch(headless=True)
    try:
        page = browser.new_page()
        page.goto((out_dir / "guide.html").as_uri(), wait_until="load", timeout=120_000)
        page.pdf(
            path=str(pdf_path), format=paper, print_background=True,
            display_header_footer=True,
            header_template="<span></span>",
            footer_template=("<div style='font-size:8px;color:#777;width:100%;padding:0 16mm;display:flex;"
                             "justify-content:space-between'><span>" + html.escape(title) +
                             "</span><span><span class='pageNumber'></span> / <span class='totalPages'></span></span></div>"),
            margin={"top": "18mm", "bottom": "18mm", "left": "16mm", "right": "16mm"},
        )
    finally:
        browser.close()


def open_browser(pw, args) -> BrowserContext:
    kwargs = dict(
        user_data_dir=str(args.profile), headless=args.headless, viewport={"width": 1360, "height": 900},
        args=["--disable-blink-features=AutomationControlled"], ignore_default_args=["--enable-automation"],
    )
    if args.browser == "chrome":
        try:
            return pw.chromium.launch_persistent_context(channel="chrome", **kwargs)
        except Exception as e:
            log(f"Could not start Google Chrome ({str(e).splitlines()[0][:80]}); using bundled Chromium.")
    return pw.chromium.launch_persistent_context(**kwargs)


def find_guides(page: Page, args) -> list[tuple[str, str]]:
    """Collect guide links from whatever page the user has opened (their library)."""
    settle(page, expand=False)
    found: dict[str, str] = {}
    for link in evaluate_retry(page, JS["links"]):
        base = guide_base(link["href"])
        if base and (not args.match or re.search(args.match, base, re.I)):
            if len(link["text"]) > len(found.get(base, "")):
                found[base] = link["text"].splitlines()[0] if link["text"] else ""
            found.setdefault(base, "")
    return list(found.items())


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


def current_page(ctx: BrowserContext) -> Page:
    return ctx.pages[-1] if ctx.pages else ctx.new_page()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="*", help="guide URLs to archive (default: every guide linked from your library page)")
    ap.add_argument("-o", "--out", type=Path, default=HERE / "guides", help="output folder (default: ./guides)")
    ap.add_argument("--force", action="store_true", help="re-download guides that were already archived")
    ap.add_argument("--login", action="store_true", help="pause for login even if a saved session exists")
    ap.add_argument("--match", help="only archive guides whose URL matches this regex")
    ap.add_argument("--selector", help="CSS selector of the guide content, if auto-detection grabs the wrong area")
    ap.add_argument("--paper", default="Letter", choices=["Letter", "A4"], help="PDF paper size")
    ap.add_argument("--delay", type=float, default=1.5, help="seconds to wait between pages (default 1.5)")
    ap.add_argument("--max-pages", type=int, default=300, help="max sections per guide")
    ap.add_argument("--browser", default="chrome", choices=["chrome", "chromium"])
    ap.add_argument("--library-url", help="page that lists your purchased guides (remembered after the first run)")
    ap.add_argument("--profile", type=Path, default=PROFILE_DIR, help=argparse.SUPPRESS)
    ap.add_argument("--headless", action="store_true", help="run without a window (only once you're logged in)")
    args = ap.parse_args()

    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    first_run = not args.profile.exists()
    args.out.mkdir(parents=True, exist_ok=True)
    out_root = args.out.resolve()

    with sync_playwright() as pw:
        ctx = open_browser(pw, args)
        page = current_page(ctx)
        try:
            targets: list[tuple[str, str]] = []
            if args.urls:
                ensure_logged_in(page, args, first_run)
                page = current_page(ctx)
                for u in args.urls:
                    targets.append((guide_base(u) or clean_url(u), ""))
            else:
                try:
                    page.goto(args.library_url or state.get("library_url") or START_URL, wait_until="domcontentloaded", timeout=60_000)
                except Exception:
                    pass
                log("\nIn the browser window that just opened:")
                log("  1. Log in to Metafy (only needed the first time).")
                log("  2. Open the page that lists the guides you've purchased.")
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
                try:
                    res = archive_guide(ctx, page, base, out_root, args)
                    if not res:
                        failed += 1
                        continue
                    render_pdf(pw, res["dir"], res["pdf"], res["title"], args.paper)
                    done[base] = {"dir": str(res["dir"].relative_to(out_root)),
                                  "pdf": str(res["pdf"].relative_to(out_root))}
                    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
                    log(f"  saved: {res['pdf']}")
                    ok += 1
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    failed += 1
                    log(f"  FAILED: {str(e).splitlines()[0][:200]}")
            log(f"\nDone. {ok} archived, {skipped} skipped, {failed} failed. Output: {out_root}")
            return 0 if not failed else 2
        except KeyboardInterrupt:
            log("\nStopped.")
            return 130
        finally:
            try:
                ctx.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
