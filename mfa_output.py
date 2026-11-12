"""Writing guide.html, videos.md, source.json and rendering the PDF."""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from pathlib import Path

CSS = """
@page { margin: 18mm 16mm; }
* { box-sizing: border-box; }
body { font: 11.5pt/1.55 -apple-system, "Helvetica Neue", Arial, sans-serif; color: #1a1a1a;
       max-width: 820px; margin: 0 auto; padding: 0 12px; overflow-wrap: anywhere; }
h1, h2, h3, h4 { line-height: 1.25; break-after: avoid; margin: 1.4em 0 .5em; }
h1 { font-size: 22pt; } h2 { font-size: 16pt; } h3 { font-size: 13pt; }
img, svg { max-width: 100%; max-height: 120mm; width: auto; height: auto; display: block; margin: 10px 0; break-inside: avoid; }
a { color: #1a55c4; }
pre, code { font: 9.5pt/1.4 Menlo, monospace; background: #f3f3f3; }
pre { padding: 10px; white-space: pre-wrap; }
table { border-collapse: collapse; margin: 12px 0; width: 100%; }
td, th { border: 1px solid #bbb; padding: 5px 8px; text-align: left; vertical-align: top; }
blockquote { border-left: 3px solid #999; margin: 12px 0; padding: 2px 14px; color: #444; }
.mfa-cover { padding: 60px 0 20px; }
.mfa-cover h1 { font-size: 30pt; margin: 0 0 12px; }
.mfa-meta { color: #555; font-size: 10pt; line-height: 1.7; }
.mfa-changes { border: 1px solid #d9c36a; background: #fdf8e3; padding: 8px 12px; margin: 14px 0; font-size: 10pt; }
.mfa-toc li { margin: 3px 0; }
.mfa-toc .mfa-flag { font-size: 8.5pt; font-weight: 600; color: #8a6d00; margin-left: 6px; }
.mfa-chapter { break-before: page; }
.mfa-chapter-src { color: #666; font-size: 9pt; margin-top: -4px; }
.mfa-video { border: 1px solid #9ab; border-left: 5px solid #1a55c4; background: #f2f6fc;
             padding: 8px 12px; margin: 12px 0; font-size: 10.5pt; break-inside: avoid; }
.mfa-video img { max-height: 220px; width: auto; }
.mfa-saved { color: #1d6b2f; font-weight: 600; }
.mfa-gone { color: #933; }
.mfa-missing { border: 1px dashed #c66; color: #933; background: #fff5f5; padding: 8px 12px;
               margin: 10px 0; font-size: 9.5pt; }
.mfa-comment { border-left: 3px solid #cbd; background: #fafafa; padding: 6px 12px; margin: 8px 0;
               font-size: 10pt; break-inside: avoid; }
.mfa-comment time { color: #777; font-size: 9pt; margin-left: 6px; }
.mfa-vlist { font-size: 10pt; }
.mfa-vlist li { margin: 4px 0; }
.mfa-host { display: inline-block; font-size: 8.5pt; font-weight: 600; padding: 0 6px; border-radius: 3px;
            background: #e4e9f2; color: #345; margin-right: 6px; vertical-align: middle; }
"""


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
    updated = [c["title"] for u, c in new.items() if u in old and old[u].get("hash") and old[u]["hash"] != c["hash"]]
    for c in chapters:
        c["flag"] = "new" if c["url"] not in old else ("updated" if c["title"] in updated else "")
    return {"since": prev.get("archived", "?"), "new": added, "updated": updated, "removed": removed}


def changes_text(ch: dict | None) -> str:
    if not ch:
        return ""
    since = ch["since"].replace("T", " ")
    parts = [f"{len(ch[k])} {k}" for k in ("new", "updated", "removed") if ch[k]]
    return f"Changes since {since}: " + (", ".join(parts) if parts else "none")


def write_outputs(out_dir: Path, title: str, author: str, base: str, chapters: list[dict],
                  now: dt.datetime, pdf_file: str, changes: dict | None = None) -> None:
    esc = html.escape
    stamp = now.strftime("%Y-%m-%d %H:%M")
    n = len(chapters)
    n_videos = sum(len(c["videos"]) for c in chapters)
    n_saved = sum(1 for c in chapters for v in c["videos"] if v.get("file"))
    parts = [
        f"<!doctype html><html><head><meta charset='utf-8'><title>{esc(title)}</title><style>{CSS}</style></head><body>",
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
         "pdf": pdf_file, "changes": changes,
         "sections": [{"title": c["title"], "url": c["url"], "hash": c["hash"], "videos": c["videos"]} for c in chapters]},
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
