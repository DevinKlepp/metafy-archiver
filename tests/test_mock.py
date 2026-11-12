"""End-to-end test against the mock guide site in tests/fixture.

Run with pytest, or directly:  .venv/bin/python tests/test_mock.py
Needs the Playwright Chromium build (`.venv/bin/playwright install chromium`).
"""
from __future__ import annotations

import json
import shutil
import struct
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

FIXTURE = Path(__file__).resolve().parent / "fixture"


def png(width: int, height: int, rgb=(40, 120, 200)) -> bytes:
    """A solid-colour PNG, built by hand so the fixture needs no binary files."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    row = b"\x00" + bytes(rgb) * width
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b""))


class Handler(SimpleHTTPRequestHandler):
    """Serve /guides/view/x as guides/view/x.html, like a real site with extension-less URLs."""

    def translate_path(self, path: str) -> str:
        p = super().translate_path(path).rstrip("/")
        if not Path(p).suffix and Path(p + ".html").exists():
            return p + ".html"
        if path.rstrip("/") == "/library":
            return str(Path(self.directory) / "library.html")
        return p

    def log_message(self, *a):  # keep test output quiet
        pass


def serve(root: Path) -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(root)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_archive(tmp_path: Path) -> None:
    site = tmp_path / "site"
    shutil.copytree(FIXTURE, site)
    (site / "img").mkdir()
    (site / "img" / "banner.png").write_bytes(png(200, 120))  # /img/missing.png deliberately absent
    srv, origin = serve(site)
    out = tmp_path / "out"
    out.mkdir()
    args = Namespace(selector=None, max_pages=50, delay=0, paper="Letter", match=None)

    from playwright.sync_api import sync_playwright
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
                res = ma.archive_guide(ctx, page, base, out, args)
                assert res, base
                ma.render_pdf(pw, res["dir"], res["pdf"], res["title"], args.paper)
                results[base.rsplit("/", 1)[-1]] = res
        finally:
            ctx.close()
            srv.shutdown()

    main = results["mock-guide-abc123"]
    src = json.loads((main["dir"] / "source.json").read_text())
    # Title, author, sections in sidebar order with sidebar labels (not the fixed "REMOVE" h1).
    assert main["title"] == "Mock Guide"
    assert src["author"] == "Mock Coach (@mockcoach)"
    assert [s["title"] for s in src["sections"]] == ["Mock Guide", "1. Intro", "2. Matchups"], src["sections"]
    # PDF is named after the guide with a timestamp and recorded in source.json.
    assert main["pdf"].exists() and main["pdf"].stat().st_size > 1000
    assert main["pdf"].name.startswith("Mock Guide - 20") and main["pdf"].name.endswith(".pdf")
    assert src["pdf"] == main["pdf"].name
    # Images: banner saved once (deduplicated), missing one replaced by a visible note.
    assert len(list((main["dir"] / "images").glob("*.png"))) == 1
    html = (main["dir"] / "guide.html").read_text()
    assert "mfa-missing" in html and "/img/missing.png" in html and "MFAIMG_" not in html
    # Videos: embed normalised to a watch URL with the start time, plain link picked up too.
    vids = {v["url"] for s in src["sections"] for v in s["videos"]}
    assert "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s" in vids, vids
    assert "https://youtu.be/abcdefghijk" in vids
    assert "youtube.com/watch?v=dQw4w9WgXcQ" in (main["dir"] / "videos.md").read_text()
    # Cover page carries the author and section count.
    assert "By Mock Coach" in html and "3 sections" in html
    # Same title, different guide: separate folder, nothing overwritten.
    other = results["mock-guide-xyz789"]
    assert other["dir"] != main["dir"] and other["dir"].name == "Mock Guide (mock-guide-xyz789)"
    assert (main["dir"] / "source.json").exists() and (other["dir"] / "source.json").exists()
    assert not list(out.glob(".partial-*"))

    # A re-run keeps the earlier PDF as a version and refreshes the rest.
    import datetime as dt
    older = main["dir"] / ma.pdf_name("Mock Guide", dt.datetime(2020, 1, 1, 9, 0))
    older.write_bytes(b"%PDF-old")
    assert older.exists()
    assert ma.resolve_out_dir(out, "Mock Guide", f"{origin}/guides/view/mock-guide-abc123") == main["dir"]
    assert ma.previous_pdf({"dir": main["dir"].name, "pdf": f"{main['dir'].name}/{main['pdf'].name}"}, out) == main["pdf"]
    assert ma.previous_pdf(str(main["dir"]), out) is not None  # legacy absolute-path state entry
    assert ma.previous_pdf({"pdf": "nope/nope.pdf"}, out) is None


if __name__ == "__main__":
    d = Path(tempfile.mkdtemp(prefix="mfa-test-"))
    try:
        test_archive(d)
        print("OK")
    finally:
        shutil.rmtree(d, ignore_errors=True)
