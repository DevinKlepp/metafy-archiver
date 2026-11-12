"""Writing guide.html, videos.md, source.json and rendering the PDF."""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from pathlib import Path

from mfa_common import launch_or_install

# Colours sampled from metafy.gg (dark) and a plain paper look (light). Values are CSS colours;
# "bg_rgb" is the same page background as an RGB tuple for flattening transparent images.
THEMES = {
    "dark": {
        "bg": "#07070a", "bg_rgb": (7, 7, 10), "fg": "#c0c0d1", "heading": "#ffffff", "muted": "#9494a8",
        "link": "#94f094", "card": "#14141a", "card2": "#1e1e27", "border": "#2a2a36", "code": "#1e1e27",
        "accent": "#94f094", "warn": "#f2be5c", "bad": "#f28b82", "badge": "#2a2a36", "badge_fg": "#c0c0d1",
        "changes_bg": "#1c1a10", "missing_bg": "#1f1113",
    },
    "light": {
        "bg": "#ffffff", "bg_rgb": (255, 255, 255), "fg": "#1a1a1a", "heading": "#111111", "muted": "#555555",
        "link": "#1a55c4", "card": "#f2f6fc", "card2": "#f3f3f3", "border": "#c9ced6", "code": "#f3f3f3",
        "accent": "#1d6b2f", "warn": "#8a6d00", "bad": "#993333", "badge": "#e4e9f2", "badge_fg": "#334455",
        "changes_bg": "#fdf8e3", "missing_bg": "#fff5f5",
    },
}
DEFAULT_THEME = "dark"

CSS_TEMPLATE = """
:root { --bg: %(bg)s; --fg: %(fg)s; --heading: %(heading)s; --muted: %(muted)s; --link: %(link)s;
        --card: %(card)s; --card2: %(card2)s; --border: %(border)s; --code: %(code)s; --accent: %(accent)s;
        --warn: %(warn)s; --bad: %(bad)s; --badge: %(badge)s; --badge-fg: %(badge_fg)s;
        --changes-bg: %(changes_bg)s; --missing-bg: %(missing_bg)s; }
@page { size: %(paper)s; margin: 18mm 16mm; background: var(--bg);
        @bottom-left { content: "%(footer)s"; color: var(--muted); font: 8pt -apple-system, "Helvetica Neue", Arial, sans-serif; }
        @bottom-right { content: counter(page) " / " counter(pages); color: var(--muted); font: 8pt -apple-system, "Helvetica Neue", Arial, sans-serif; } }
* { box-sizing: border-box; }
html { background: var(--bg); }
body { font: 11.5pt/1.55 -apple-system, "Helvetica Neue", Arial, sans-serif; color: var(--fg); background: var(--bg);
       max-width: 820px; margin: 0 auto; padding: 0 12px; overflow-wrap: anywhere; }
@media screen { body { padding: 32px 24px; } }
h1, h2, h3, h4 { color: var(--heading); line-height: 1.25; break-after: avoid; margin: 1.4em 0 .5em; }
h1 { font-size: 22pt; } h2 { font-size: 16pt; } h3 { font-size: 13pt; }
strong { color: var(--heading); }
img, svg { max-width: 100%%; max-height: 120mm; width: auto; height: auto; display: block; margin: 10px 0; break-inside: avoid; border-radius: 6px; }
a { color: var(--link); }
pre, code { font: 9.5pt/1.4 Menlo, monospace; background: var(--code); color: var(--fg); border-radius: 4px; }
pre { padding: 10px; white-space: pre-wrap; }
code { padding: 0 4px; }
table { border-collapse: collapse; margin: 12px 0; width: 100%%; }
td, th { border: 1px solid var(--border); padding: 5px 8px; text-align: left; vertical-align: top; }
th { background: var(--card2); color: var(--heading); }
blockquote { border-left: 3px solid var(--muted); margin: 12px 0; padding: 2px 14px; color: var(--muted); }
hr { border: 0; border-top: 1px solid var(--border); }
.mfa-cover { padding: 60px 0 20px; }
.mfa-cover h1 { font-size: 30pt; margin: 0 0 12px; }
.mfa-meta { color: var(--muted); font-size: 10pt; line-height: 1.7; }
.mfa-changes { border: 1px solid var(--warn); background: var(--changes-bg); padding: 8px 12px; margin: 14px 0; font-size: 10pt; border-radius: 6px; }
.mfa-toc li { margin: 3px 0; }
.mfa-toc .mfa-flag { font-size: 8.5pt; font-weight: 600; color: var(--warn); margin-left: 6px; }
.mfa-chapter { break-before: page; }
.mfa-chapter-src { color: var(--muted); font-size: 9pt; margin-top: -4px; }
.mfa-video { border: 1px solid var(--border); border-left: 5px solid var(--accent); background: var(--card);
             padding: 8px 12px; margin: 12px 0; font-size: 10.5pt; break-inside: avoid; border-radius: 6px; }
.mfa-video img { max-height: 220px; width: auto; }
.mfa-saved { color: var(--accent); font-weight: 600; }
.mfa-gone { color: var(--bad); }
.mfa-missing { border: 1px dashed var(--bad); color: var(--bad); background: var(--missing-bg); padding: 8px 12px;
               margin: 10px 0; font-size: 9.5pt; border-radius: 6px; }
.mfa-comment { border-left: 3px solid var(--border); background: var(--card); padding: 6px 12px; margin: 8px 0;
               font-size: 10pt; break-inside: avoid; border-radius: 0 6px 6px 0; }
.mfa-comment time { color: var(--muted); font-size: 9pt; margin-left: 6px; }
.mfa-vlist { font-size: 10pt; }
.mfa-vlist li { margin: 4px 0; }
.mfa-host { display: inline-block; font-size: 8.5pt; font-weight: 600; padding: 0 6px; border-radius: 3px;
            background: var(--badge); color: var(--badge-fg); margin-right: 6px; vertical-align: middle; }
"""


def css_for(theme: str, title: str, paper: str = "Letter") -> str:
    footer = title.replace("\\", "\\\\").replace('"', '\\"')[:80]
    return CSS_TEMPLATE % {**THEMES[theme], "paper": paper, "footer": footer}


def place_images(body: str, image_urls: list[str], saved: list[str | None]) -> str:
    """Swap MFAIMG_n_ placeholders for local paths; a visible note replaces images that failed."""
    for i, (img_url, rel) in enumerate(zip(image_urls, saved, strict=True)):
        tag_re = re.compile(rf"<img\b[^>]*\bsrc=\"MFAIMG_{i}_\"[^>]*>")
        if rel:
            marker, local = f"MFAIMG_{i}_", html.escape(rel, quote=True)
            body = tag_re.sub(lambda m, marker=marker, local=local: m.group(0).replace(marker, local), body)
        else:
            note = (f"<div class='mfa-missing'>Image not saved: "
                    f"<a href='{html.escape(img_url or '', quote=True)}'>{html.escape(img_url or '?')}</a></div>")
            body = tag_re.sub(note, body)
    return body


def video_status_html(v: dict) -> str:
    """The link line for a video: the saved file when there is one (the signed stream link is dead
    within hours, so it is not worth printing), otherwise the link plus why it was not saved."""
    esc = html.escape
    if v.get("file"):
        f = esc(v["file"], quote=True)
        return f"<span class='mfa-saved'>Saved copy: <a href='{f}'>{f}</a></span>"
    short = v["url"] if len(v["url"]) <= 100 else v["url"][:97] + "…"
    line = f"<a href='{esc(v['url'], quote=True)}'>{esc(short)}</a>"
    if v.get("note"):
        line += f" <span class='mfa-gone'>({esc(v['note'])})</span>"
    return line


def place_videos(body: str, videos: list[dict]) -> str:
    """Fill the MFAVID_n_ slot in each video box."""
    def repl(m: re.Match) -> str:
        i = int(m.group(1))
        return f"<div>{video_status_html(videos[i])}</div>" if i < len(videos) else ""
    return re.sub(r"<div>MFAVID_(\d+)_</div>", repl, body)


def describe_video(v: dict) -> str:
    """One-line plain-text status for the Markdown list."""
    bits = [v["host"] or "video"]
    if v.get("file"):
        bits.append(f"saved as {v['file']}")
    elif v.get("note"):
        bits.append(v["note"])
    elif v.get("expires"):
        bits.append(f"link expires {v['expires'].replace('T', ' ')}")
    return " · ".join(bits)


def diff_sections(prev: dict | None, chapters: list[dict]) -> dict | None:
    """What changed since the previous archive of this guide (by section URL and content hash)."""
    if not prev or not prev.get("sections"):
        return None
    old = {s["url"]: s for s in prev["sections"]}
    new = {c["url"]: c for c in chapters}
    added = [c["title"] for u, c in new.items() if u not in old]
    removed = [s["title"] for u, s in old.items() if u not in new]
    updated_urls = {u for u, c in new.items() if u in old and old[u].get("hash") and old[u]["hash"] != c["hash"]}
    for c in chapters:
        c["flag"] = "new" if c["url"] not in old else ("updated" if c["url"] in updated_urls else "")
    return {"since": prev.get("archived", "?"), "new": added, "removed": removed,
            "updated": [c["title"] for c in chapters if c["flag"] == "updated"]}


def changes_text(ch: dict | None) -> str:
    if not ch:
        return ""
    since = ch["since"].replace("T", " ")
    parts = [f"{len(ch[k])} {k}" for k in ("new", "updated", "removed") if ch[k]]
    return f"Changes since {since}: " + (", ".join(parts) if parts else "none")


def write_outputs(out_dir: Path, title: str, author: str, base: str, chapters: list[dict],
                  now: dt.datetime, pdf_file: str, changes: dict | None = None,
                  theme: str = DEFAULT_THEME, paper: str = "Letter") -> None:
    esc = html.escape
    stamp = now.strftime("%Y-%m-%d %H:%M")
    n = len(chapters)
    n_videos = sum(len(c["videos"]) for c in chapters)
    n_saved = sum(1 for c in chapters for v in c["videos"] if v.get("file"))
    parts = [
        f"<!doctype html><html data-theme='{theme}'><head><meta charset='utf-8'><title>{esc(title)}</title>"
        f"<style>{css_for(theme, title, paper)}</style></head><body>",
        f"<div class='mfa-cover'><h1>{esc(title)}</h1><div class='mfa-meta'>"
        + (f"By {esc(author)}<br>" if author else "")
        + f"Source: <a href='{esc(base)}'>{esc(base)}</a><br>"
        f"{n} section{'s' if n != 1 else ''}"
        + (f" &middot; {n_videos} video{'s' if n_videos != 1 else ''}"
           + (f", {n_saved} saved in <code>videos/</code>" if n_saved else "") if n_videos else "")
        + f" &middot; archived {stamp} for personal use</div>",
    ]
    if changes:
        detail = "".join(f"<br>{k.capitalize()}: {esc(', '.join(changes[k]))}" for k in ("new", "updated", "removed") if changes[k])
        parts.append(f"<div class='mfa-changes'>{esc(changes_text(changes))}{detail}</div>")
    parts.append("</div>")
    if n > 1:
        parts.append("<h2>Contents</h2><ol class='mfa-toc'>")
        parts += [f"<li><a href='#ch{i}'>{esc(c['title'])}</a>"
                  + (f"<span class='mfa-flag'>{c['flag'].upper()}</span>" if c.get("flag") else "") + "</li>"
                  for i, c in enumerate(chapters, 1)]
        parts.append("</ol>")
    md = [f"# Video links: {title}", ""] + ([f"By {author}  "] if author else []) + [
        f"Source: {base}  ", f"Archived: {stamp}", "",
        "Metafy-hosted streams are signed links that expire within hours; where ffmpeg was available they were",
        "saved to videos/. YouTube/Vimeo/Twitch videos are never downloaded; they are kept as links.", ""]
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
                host = esc(v["host"] or "video")
                label = f"{esc(v['label'])}: " if v["label"] else ""
                parts.append(f"<li><span class='mfa-host'>{host}</span>{label}{video_status_html(v)}</li>")
                md.append(f"- [{describe_video(v)}] {v['label'] + ': ' if v['label'] else ''}<{v['url']}>")
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
         "pdf": pdf_file, "theme": theme, "changes": changes,
         "sections": [{"title": c["title"], "url": c["url"], "hash": c["hash"], "flag": c.get("flag", ""),
                       "videos": c["videos"]} for c in chapters]},
        indent=2, ensure_ascii=False), encoding="utf-8")


def render_pdf(pw, out_dir: Path, pdf_path: Path, title: str, paper: str) -> None:
    """Render the saved guide.html to PDF with a separate headless browser (no login needed).

    Page size, margins, background and the footer (title, page x / y) all come from the @page
    rules in the HTML, which is what lets the dark theme cover the whole sheet.
    """
    browser = launch_or_install(lambda: pw.chromium.launch(headless=True),
                                fallback=lambda: pw.chromium.launch(headless=True, channel="chrome"))
    try:
        page = browser.new_page()
        page.goto((out_dir / "guide.html").as_uri(), wait_until="load", timeout=120_000)
        page.pdf(path=str(pdf_path), format=paper, print_background=True, prefer_css_page_size=True)
    finally:
        browser.close()
