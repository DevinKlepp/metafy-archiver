"""End-to-end test against the mock guide site in tests/fixture.

Run with pytest, or directly:  .venv/bin/python tests/test_mock.py
Needs the Playwright Chromium build (`.venv/bin/playwright install chromium`). Video download
assertions run only when a usable ffmpeg is found (the imageio-ffmpeg package provides one).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import zlib
from argparse import Namespace
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import metafy_archiver as ma  # noqa: E402
import mfa_media as mm  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixture"


def png(width: int, height: int, rgb=(40, 120, 200)) -> bytes:
    """A solid-colour PNG, built by hand so the fixture needs no binary files."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    row = b"\x00" + bytes(rgb) * width
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b""))


def make_clip(ffmpeg: str, dest: Path) -> bool:
    """A 3-second test-pattern MP4 with a tone, so the download path has something real to copy."""
    r = subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=10",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(dest)],
                       capture_output=True, text=True)
    return r.returncode == 0 and dest.exists() and dest.stat().st_size > 10_000


class Handler(SimpleHTTPRequestHandler):
    """Serve /guides/view/x as guides/view/x.html, like a real site with extension-less URLs."""

    def translate_path(self, path: str) -> str:
        p = super().translate_path(path).rstrip("/")
        if not Path(p).suffix and Path(p + ".html").exists():
            return p + ".html"
        return p

    def end_headers(self):  # the test edits pages between runs; the browser must not cache them
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *a):  # keep test output quiet
        pass


class QuietServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):  # ffmpeg probes then drops connections; not an error
        pass


def serve(root: Path) -> tuple[ThreadingHTTPServer, str]:
    srv = QuietServer(("127.0.0.1", 0), partial(Handler, directory=str(root)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_archive(tmp_path: Path) -> None:
    site = tmp_path / "site"
    shutil.copytree(FIXTURE, site)
    (site / "img").mkdir()
    (site / "img" / "banner.png").write_bytes(png(200, 120))  # /img/missing.png deliberately absent
    (site / "img" / "wide.png").write_bytes(png(2400, 300))
    (site / "img" / "banner-copy.png").write_bytes(png(200, 120))  # same bytes as banner.png
    (site / "media").mkdir()
    ffmpeg = ma.find_ffmpeg(None)
    have_clip = bool(ffmpeg) and make_clip(ffmpeg, site / "media" / "clip.mp4")
    srv, origin = serve(site)
    out = tmp_path / "out"
    out.mkdir()
    args = Namespace(selector=None, max_pages=50, delay=0, paper="Letter", match=None,
                     max_image_px=1600, no_videos=False, video_max_height=720, compress_videos=False)

    # The Mux URL in the fixture points at the real stream.mux.com; don't hit it from a test.
    real_download = ma.download_video
    attempted: list[str] = []

    def fake_download(exe, url, dest, referer, **kw):
        attempted.append(url)
        if "stream.mux.com" in url:
            return False
        return real_download(exe, url, dest, referer, **kw)
    ma.download_video = fake_download

    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(user_data_dir=str(tmp_path / "profile"), headless=True)
            page = ctx.new_page()
            try:
                page.goto(f"{origin}/library")
                assert ma.login_state(page) == "in"
                found = dict(ma.find_guides(page, args))
                assert set(found) == {f"{origin}/guides/view/mock-guide-abc123", f"{origin}/guides/view/mock-guide-xyz789"}, found

                results = {}
                for base in sorted(found):
                    args.theme = "light" if "xyz789" in base else "dark"  # cover both themes
                    res = ma.archive_guide(ctx, page, base, out, args, ffmpeg=ffmpeg)
                    assert res, base
                    ma.render_pdf(pw, res["dir"], res["pdf"], res["title"], args.paper)
                    results[base.rsplit("/", 1)[-1]] = res

                args.theme = "dark"
                # Snapshot the first run's outputs; the re-run below overwrites them.
                first = results["mock-guide-abc123"]["dir"]
                first_src, first_html = (first / "source.json").read_text(), (first / "guide.html").read_text()

                # The guide changes: one section edited, one inserted at the top (which renumbers the
                # rest). A re-run must report both, keep the earlier PDF, and reuse the saved video
                # under its new number instead of downloading it again.
                main_base = f"{origin}/guides/view/mock-guide-abc123"
                p2 = site / "guides/view/mock-guide-abc123/2-matchups.html"
                p2.write_text(p2.read_text().replace("Win rate", "Win percentage"))
                p1 = site / "guides/view/mock-guide-abc123/1-intro.html"  # only a comment's age changes: not an update
                p1.write_text(p1.read_text().replace("3 hours ago", "2 days ago"))
                root = site / "guides/view/mock-guide-abc123.html"
                root.write_text(root.read_text().replace("<ol>", '<ol><li><a href="/guides/view/mock-guide-abc123/0-preface">0. Preface</a></li>'))
                (site / "guides/view/mock-guide-abc123/0-preface.html").write_text(
                    root.read_text().replace("<h2>Mock Guide</h2>", "<h2>0. Preface</h2>").replace("Welcome.", "Brand new section."))
                rerun = ma.archive_guide(ctx, page, main_base, out, args, prev_dir=first, ffmpeg=ffmpeg)
                assert rerun and rerun["dir"] == first
                ch = rerun["changes"]
                assert ch and ch["new"] == ["0. Preface"] and ch["updated"] == ["2. Matchups"] and ch["removed"] == [], ch
                html2 = (rerun["dir"] / "guide.html").read_text()
                assert "Changes since" in html2 and "New: 0. Preface" in html2 and ">NEW<" in html2 and ">UPDATED<" in html2
                assert results["mock-guide-abc123"]["pdf"].exists()  # earlier PDF kept
                src2 = json.loads((first / "source.json").read_text())
                assert [s["title"] for s in src2["sections"]] == ["Mock Guide", "0. Preface", "1. Intro", "2. Matchups"]
                if have_clip:
                    assert (first / "videos/04-2. Matchups-1.mp4").exists() and not (first / "videos/03-2. Matchups-1.mp4").exists()
                    assert not any("clip.mp4" in u for u in attempted[2:]), attempted  # reused, not re-fetched
                    clip2 = next(v for s in src2["sections"] for v in s["videos"] if v.get("file"))
                    assert clip2["file"] == "videos/04-2. Matchups-1.mp4" and clip2["encoded"] == "copy"
                    # Asking for compression re-encodes the saved copy locally, still without a download.
                    n_attempts = len(attempted)
                    args.compress_videos = True
                    rerun3 = ma.archive_guide(ctx, page, main_base, out, args, prev_dir=first, ffmpeg=ffmpeg)
                    args.compress_videos = False
                    assert rerun3 and not any("clip.mp4" in u for u in attempted[n_attempts:])
                    src3 = json.loads((first / "source.json").read_text())
                    clip3 = next(v for s in src3["sections"] for v in s["videos"] if v.get("file"))
                    assert clip3["encoded"] == "x264" and (first / clip3["file"]).exists()
                    assert len(list((first / "videos").glob("*.mp4"))) == 1  # the uncompressed copy was replaced
                    (first / "source.json").write_text(json.dumps(src2))  # back to the second run's data for the checks below
            finally:
                ctx.close()
                srv.shutdown()
    finally:
        ma.download_video = real_download

    main = results["mock-guide-abc123"]
    src, html = json.loads(first_src), first_html  # the first run's outputs
    # Title, author, sections in sidebar order with sidebar labels (not the fixed "REMOVE" h1).
    assert main["title"] == "Mock Guide"
    assert src["author"] == "Mock Coach (@mockcoach)"
    assert [s["title"] for s in src["sections"]] == ["Mock Guide", "1. Intro", "2. Matchups"], src["sections"]
    # PDF is named after the guide with a timestamp and recorded in source.json.
    assert main["pdf"].exists() and main["pdf"].stat().st_size > 1000
    assert main["pdf"].name.startswith("Mock Guide - 20") and main["pdf"].name.endswith(".pdf")
    assert src["pdf"] == main["pdf"].name
    # Images: banner saved once (deduplicated), the wide PNG downscaled to a 1600 px JPEG,
    # the missing one replaced by a visible note.
    imgs = sorted(p.name for p in (main["dir"] / "images").iterdir())
    assert len(imgs) == 2 and any(n.endswith(".jpg") for n in imgs), imgs
    from PIL import Image
    jpg = next(p for p in (main["dir"] / "images").iterdir() if p.suffix == ".jpg")
    assert Image.open(jpg).size == (1600, 200)
    assert "mfa-missing" in html and "/img/missing.png" in html and "MFAIMG_" not in html and "MFAVID_" not in html
    # Videos: YouTube embed normalised with its start time; plain youtu.be link; Mux player turned into
    # a labelled Metafy-hosted box with its signed stream URL; the local clip downloaded; the
    # decorative autoplay loop ignored.
    vids = {v["url"]: v for s in src["sections"] for v in s["videos"]}
    assert "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s" in vids, vids
    assert vids["https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s"]["host"] == "YouTube"
    assert "https://youtu.be/abcdefghijk" in vids
    mux = vids["https://stream.mux.com/MOCKID123.m3u8?token=eyJhbGciOiJSUzI1NiJ9.eyJleHAiOjQxMDI0NDQ4MDB9.sig"]
    assert mux["host"] == "Metafy" and mux["label"] == "Rocks matchup", mux
    assert mux["expires"] == dt.datetime.fromtimestamp(4102444800).isoformat(timespec="minutes"), mux
    assert "Metafy-hosted video: Rocks matchup" in html and "YouTube video: Intro video" in html
    assert not any("deco.webm" in u for u in vids), vids
    assert "mfa-host'>Metafy<" in html and "mfa-host'>YouTube<" in html
    assert not any("youtu" in u for u in attempted), attempted  # YouTube is never downloaded
    if have_clip:
        clip = vids[f"{origin}/media/clip.mp4"]
        assert clip["file"] == "videos/03-2. Matchups-1.mp4" and clip["encoded"] == "copy", clip
        saved = list((main["dir"] / "videos").glob("*.mp4"))  # since renamed and re-encoded by the later runs
        assert len(saved) == 1 and saved[0].stat().st_size > 10_000, saved
        assert html.count("Saved copy: <a href='videos/03-2. Matchups-1.mp4'>") == 2  # box + section list
        assert f"{origin}/media/clip.mp4" not in html  # the dead link is not printed once saved
        assert mux["note"].startswith("download failed"), mux
        assert "download failed" in (main["dir"] / "videos.md").read_text()
        assert "download failed" in html and "stream.mux.com/MOCKID123" in html  # unsaved: link + reason
    else:
        print("NOTE: no usable ffmpeg, video download assertions skipped")
    # The same image under two URLs is stored once (content hash) and both tags point at it.
    assert html.count("images/") >= 3 and len(set(re.findall(r"images/[\w.-]+", html))) == 2
    # Markup clean-up: framework comments gone, Q&A thread as comment blocks, no div inside p,
    # the "Like" button dropped, no deep single-child div chains.
    assert "<!--" not in html.split("<section", 1)[1]
    assert html.count("class=\"mfa-comment\"") == 3 and "Like</button>" not in html and "<button" not in html
    assert "<p><div" not in html
    assert "<div><div><div>" not in html
    # Cover page carries the author, section and video counts; first archive has no change report.
    assert "By Mock Coach" in html and "3 sections" in html and "videos" in html
    assert src["changes"] is None and "Changes since" not in html
    # Themes: dark by default with Metafy's page colour and a CSS footer; light on request.
    assert "data-theme='dark'" in html and "--bg: #07070a" in html and 'counter(page) " / " counter(pages)' in html
    assert src["theme"] == "dark"
    other = results["mock-guide-xyz789"]
    other_html = (other["dir"] / "guide.html").read_text()
    assert "data-theme='light'" in other_html and "--bg: #ffffff" in other_html
    # Same title, different guide: separate folder, nothing overwritten.
    assert other["dir"] != main["dir"] and other["dir"].name == "Mock Guide (mock-guide-xyz789)"
    assert (main["dir"] / "source.json").exists() and (other["dir"] / "source.json").exists()
    assert not list(out.glob(".partial-*"))

    # State helpers: timestamped PDFs are found again, legacy entries still work.
    older = main["dir"] / ma.pdf_name("Mock Guide", dt.datetime(2020, 1, 1, 9, 0))
    older.write_bytes(b"%PDF-old")
    assert ma.resolve_out_dir(out, "Mock Guide", f"{origin}/guides/view/mock-guide-abc123") == main["dir"]
    entry = {"dir": main["dir"].name, "pdf": f"{main['dir'].name}/{main['pdf'].name}"}
    assert ma.previous_pdf(entry, out) == main["pdf"] and ma.previous_dir(entry, out) == main["dir"]
    assert ma.previous_pdf(str(main["dir"]), out) is not None  # legacy absolute-path state entry
    assert ma.previous_pdf({"pdf": "nope/nope.pdf"}, out) is None

    # Video variant selection and compression.
    master = ('#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=933900,RESOLUTION=1280x720,FRAME-RATE=60\nhi.m3u8\n'
              '#EXT-X-STREAM-INF:BANDWIDTH=441100,RESOLUTION=854x480\nmid.m3u8\n'
              '#EXT-X-STREAM-INF:BANDWIDTH=194700,RESOLUTION=480x270\nlo.m3u8\n')
    vs = mm.parse_variants(master)
    assert [v["height"] for v in vs] == [720, 480, 270] and vs[0]["fps"] == 60
    assert mm.choose_variant(vs, 720)["index"] == 0 and mm.choose_variant(vs, 480)["index"] == 1
    assert mm.choose_variant(vs, 100)["index"] == 2 and mm.choose_variant(vs[:1], 480) is None
    if have_clip:
        small = tmp_path / "small.mp4"
        assert ffmpeg and mm.download_video(ffmpeg, str((site / "media" / "clip.mp4").resolve()), small, "http://x/",
                                            max_height=160, compress=True)
        from PIL import Image as _I  # noqa: F401 (Pillow already required)
        info = subprocess.run([ffmpeg, "-hide_banner", "-i", str(small)], capture_output=True, text=True).stderr
        assert "214x160" in info or "212x160" in info, info  # scaled from 320x240 to 160 tall

    # Pure helpers.
    assert ma.hash_text("Based on 130+ ratings and 330+ purchases. Posted 13 hours ago. 4x Bonney") == \
        ma.hash_text("Based on 131+ ratings and 340+ purchases. Posted a day ago. 4x Bonney")
    assert ma.hash_text("4x Bonney") != ma.hash_text("3x Bonney")  # real edits still count
    assert ma.video_host("https://www.youtube.com/watch?v=x") == "YouTube"
    assert ma.video_host("https://stream.mux.com/abc.m3u8?token=t") == "Metafy"
    assert ma.video_host("https://cdn.metafy.gg/a.webm") == "Metafy"
    assert ma.is_media_url("https://stream.mux.com/abc.m3u8?token=t") and not ma.is_media_url("https://youtu.be/x")
    assert ma.link_expiry("https://x/y.m3u8?expires=1700000000") == dt.datetime.fromtimestamp(1700000000)
    assert ma.link_expiry("https://youtu.be/x") is None
    noise = ["https://manifest-oci.edgemv.mux.com/x/rendition.m3u8?cdn=edgemv", "https://stream.mux.com/MOCKID123.m3u8?token=other"]
    merged = ma.merge_videos([{"url": "https://stream.mux.com/MOCKID123.m3u8?token=t", "label": "", "kind": "stream", "host": "Metafy"}], noise)
    assert len(merged) == 1, merged


if __name__ == "__main__":
    d = Path(tempfile.mkdtemp(prefix="mfa-test-"))
    try:
        test_archive(d)
        print("OK")
    finally:
        shutil.rmtree(d, ignore_errors=True)
