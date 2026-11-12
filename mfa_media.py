"""Images and videos: fetching, deduplicating, shrinking, and saving streams with ffmpeg."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import mimetypes
import re
import shutil
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from mfa_common import log

try:
    from PIL import Image
except ImportError:  # image shrinking is optional
    Image = None

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif")
MUX_ID_RE = re.compile(r"stream\.mux\.com/([\w]+)\.m3u8", re.I)
# Sub-resources of a stream we already have (renditions, segments): never worth listing.
MEDIA_NOISE_RE = re.compile(r"edgemv\.mux\.com|/rendition\.m3u8|\.(ts|m4s|aac|vtt)(\?|$)|/chunk", re.I)


# ----------------------------------------------------------------------------- videos

def video_host(url: str) -> str:
    """'YouTube', 'Vimeo', 'Twitch', 'Metafy' or the bare hostname. Mirrors hostOf() in js/extract.js."""
    h = urlsplit(url).hostname or ""
    if re.search(r"(^|\.)(youtube\.com|youtu\.be|youtube-nocookie\.com)$", h, re.I):
        return "YouTube"
    if re.search(r"(^|\.)vimeo\.com$", h, re.I):
        return "Vimeo"
    if re.search(r"(^|\.)twitch\.tv$", h, re.I):
        return "Twitch"
    if re.search(r"(^|\.)(mux\.com|metafy\.gg|videodelivery\.net|cloudflarestream\.com)$", h, re.I):
        return "Metafy"
    return h


def is_media_url(url: str) -> bool:
    """A stream or media file ffmpeg can save, as opposed to a YouTube/Vimeo page."""
    s = urlsplit(url)
    return bool(re.search(r"\.(m3u8|mpd|mp4|webm|mov)$", s.path, re.I) or MUX_ID_RE.search(url))


def never_download(v: dict) -> bool:
    """YouTube, Vimeo and Twitch videos are never downloaded, by design: they are stable links,
    and pulling them would need a different tool. Only Metafy's own streams are saved."""
    return v.get("host") in ("YouTube", "Vimeo", "Twitch") or bool(re.search(r"googlevideo\.com|youtu", v["url"], re.I))


def link_expiry(url: str) -> dt.datetime | None:
    """When a signed stream link stops working: Mux JWT 'exp' or a plain expires= parameter."""
    q = parse_qs(urlsplit(url).query)
    try:
        if "token" in q and q["token"][0].count(".") == 2:
            payload = q["token"][0].split(".")[1]
            payload += "=" * (-len(payload) % 4)
            exp = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
            return dt.datetime.fromtimestamp(int(exp)) if exp else None
        if "expires" in q:
            return dt.datetime.fromtimestamp(int(q["expires"][0]))
    except Exception:
        pass
    return None


def merge_videos(data_videos: list[dict], sniffed: list[str], ignore: list[str] = ()) -> list[dict]:
    """Add streams seen on the wire that the DOM did not expose, minus renditions/segments/duplicates."""
    videos = [dict(v, host=v.get("host") or video_host(v["url"])) for v in data_videos]
    known = {v["url"] for v in videos}
    known_mux = {m.group(1) for v in videos if (m := MUX_ID_RE.search(v["url"]))}
    skip = {u.split("?")[0] for u in ignore}
    for s in dict.fromkeys(sniffed):
        if MEDIA_NOISE_RE.search(s) or s in known or s.split("?")[0] in skip:
            continue
        if (m := MUX_ID_RE.search(s)) and m.group(1) in known_mux:
            continue
        m = re.search(r"/(?:embed|video)/([\w-]{6,})", s)
        if m and any(m.group(1) in k for k in known):
            continue  # the same embed, already listed as a normal link
        if any(s.split("?")[0] in k for k in known):
            continue
        videos.append({"url": s, "label": "", "kind": "stream", "host": video_host(s)})
        known.add(s)
        if (m := MUX_ID_RE.search(s)):
            known_mux.add(m.group(1))
    for v in videos:
        exp = link_expiry(v["url"])
        if exp:
            v["expires"] = exp.isoformat(timespec="minutes")
    return videos


def ffmpeg_ok(exe: str) -> bool:
    """Playwright ships a stripped-down ffmpeg with no HTTPS/HLS; make sure this one can do the job."""
    try:
        protos = subprocess.run([exe, "-hide_banner", "-protocols"], capture_output=True, text=True, timeout=20).stdout
        demux = subprocess.run([exe, "-hide_banner", "-demuxers"], capture_output=True, text=True, timeout=20).stdout
        muxers = subprocess.run([exe, "-hide_banner", "-muxers"], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return False
    return (re.search(r"^\s*https\s*$", protos, re.M) is not None and re.search(r"\bhls\b", demux) is not None
            and re.search(r"\bmp4\b", muxers) is not None)


def find_ffmpeg(override: str | None) -> str | None:
    """--ffmpeg, then PATH, then the static build from the imageio-ffmpeg package."""
    cands = [override] if override else []
    if (p := shutil.which("ffmpeg")):
        cands.append(p)
    try:
        import imageio_ffmpeg
        cands.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass
    for c in cands:
        if c and Path(c).exists() and ffmpeg_ok(c):
            return c
    return None


def download_video(ffmpeg: str, url: str, dest: Path, referer: str) -> bool:
    """Save a stream (HLS/DASH/MP4) to dest as MP4 without re-encoding. Prints progress every 20 s.

    ffmpeg picks the highest-bandwidth variant of an HLS master playlist by default.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    cmd = [ffmpeg, "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1",
           "-headers", f"Referer: {referer}\r\nOrigin: {referer.rstrip('/')}\r\n", "-user_agent", UA,
           "-i", url, "-map", "0:v:0?", "-map", "0:a:0?", "-c", "copy", "-movflags", "+faststart", "-f", "mp4", str(part)]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except OSError as e:
        log(f"    video failed to start ffmpeg: {e}")
        return False
    t0 = last = time.time()
    footage = ""
    for line in proc.stdout:
        if line.startswith("out_time="):
            footage = line.split("=", 1)[1].strip().split(".")[0]
        if time.time() - last > 20:
            log(f"      ... {footage} of footage saved, {time.time() - t0:.0f}s elapsed")
            last = time.time()
    err = proc.stderr.read()
    rc = proc.wait()
    if rc != 0 or not part.exists() or part.stat().st_size < 10_000:
        log(f"    video failed (ffmpeg exit {rc}): {err.strip().splitlines()[-1][:160] if err.strip() else 'no output'}")
        part.unlink(missing_ok=True)
        return False
    part.rename(dest)
    log(f"    video saved: {dest.name} ({dest.stat().st_size / 1e6:.0f} MB, {footage or 'unknown length'}, {time.time() - t0:.0f}s)")
    return True


# ----------------------------------------------------------------------------- images

def shrink_image(path: Path, max_px: int) -> Path:
    """Downscale to max_px on the long side and re-encode for a sane PDF size. Returns the final path.

    Screenshots pasted into guides are often 3000 px PNGs of several MB each; they are what made
    a 23-section guide a 100 MB PDF. Chromium's PDF writer also cannot embed WebP and stores it as
    raw pixels, so WebP is always re-encoded. Mostly-opaque art with transparent corners (card
    images) is flattened onto the white page as JPEG; genuinely transparent graphics stay PNG.
    """
    if max_px <= 0 or Image is None or path.suffix.lower() in (".svg", ".gif", ".avif"):
        return path
    try:
        with Image.open(path) as im:
            fmt, (w, h) = im.format, im.size
            scale = min(1.0, max_px / max(w, h))
            big_png = fmt == "PNG" and path.stat().st_size > 300_000
            if scale == 1.0 and not big_png and fmt != "WEBP":
                return path
            im.load()
            img = im.copy()
        if scale < 1.0:
            img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
        if img.mode == "P":
            img = img.convert("RGBA" if "transparency" in img.info else "RGB")
        alpha = img.mode in ("RGBA", "LA") and img.getchannel("A").getextrema()[0] < 255
        if alpha:
            a = img.getchannel("A")
            opaque = a.histogram()[255] / (a.size[0] * a.size[1])
            if opaque >= 0.85:
                bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
                img = Image.alpha_composite(bg, img.convert("RGBA")).convert("RGB")
                alpha = False
        if fmt in ("PNG", "WEBP") and not alpha:
            out = path.with_suffix(".jpg")
            img.convert("RGB").save(out, "JPEG", quality=85, optimize=True, progressive=True)
        elif fmt in ("PNG", "WEBP"):
            out = path.with_suffix(".png")
            img.save(out, "PNG", optimize=True)
        elif fmt in ("JPEG", "MPO"):
            out = path
            img.convert("RGB").save(out, "JPEG", quality=85, optimize=True, progressive=True)
        else:
            return path
        if out != path:
            path.unlink()
        return out
    except Exception as e:
        log(f"    (image left as is: {path.name}: {str(e).splitlines()[0][:60]})")
        return path


def http_get(url: str, headers: dict) -> tuple[bytes, str]:
    """Plain urllib fetch (thread-safe, unlike the Playwright client). Returns (body, content-type)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, **headers})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read(), r.headers.get_content_type()


class ImageStore:
    """Downloads a guide's images into one folder, once each, deduplicated by URL and by content."""

    def __init__(self, ctx, img_dir: Path, max_px: int, workers: int = 6):
        self.ctx, self.dir, self.max_px, self.workers = ctx, img_dir, max_px, workers
        self.by_url: dict[str, str | None] = {}
        self.by_hash: dict[str, str] = {}
        self.n = 0

    def _headers(self, url: str, referer: str) -> dict:
        h = {"Referer": referer}
        try:
            cookies = self.ctx.cookies([url])
            if cookies:
                h["Cookie"] = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        except Exception:
            pass
        return h

    @staticmethod
    def _fetch(url: str, headers: dict) -> tuple[bytes, str] | str:
        """Body and type, or an error string. Runs in a worker thread, so no Playwright calls here."""
        try:
            return http_get(url, headers)
        except Exception as e:
            return str(e).splitlines()[0][:60]

    def _fallback(self, url: str, referer: str, why: str) -> tuple[bytes, str] | str:
        """The browser's own client (main thread only): copes with odd auth the plain fetch did not."""
        try:
            r = self.ctx.request.get(url, headers={"Referer": referer}, timeout=45_000)
            if r.ok:
                return r.body(), (r.headers.get("content-type") or "").split(";")[0].strip()
            return f"{why}; then {r.status}"
        except Exception as e:
            return f"{why}; then {str(e).splitlines()[0][:50]}"

    def _store(self, url: str, body: bytes, ctype: str) -> str:
        digest = hashlib.sha1(body).hexdigest()
        if digest in self.by_hash:
            return self.by_hash[digest]
        ext = Path(urlsplit(url).path).suffix.lower()
        if ext not in IMAGE_EXTS:
            ext = mimetypes.guess_extension(ctype or "") or ".img"
        self.n += 1
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"{self.n:03d}-{digest[:8]}{ext}"
        path.write_bytes(body)
        rel = f"images/{shrink_image(path, self.max_px).name}"
        self.by_hash[digest] = rel
        return rel

    def get_many(self, urls: list[str | None], referer: str) -> list[str | None]:
        """Local 'images/...' path for each URL (None where it failed), fetching new ones in parallel."""
        todo = list(dict.fromkeys(u for u in urls if u and u not in self.by_url))
        if todo:
            headers = {u: self._headers(u, referer) for u in todo}  # cookies: main thread only
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                results = list(pool.map(lambda u: self._fetch(u, headers[u]), todo))
            for u, res in zip(todo, results):  # store in order so numbering follows the page
                if isinstance(res, str):
                    res = self._fallback(u, referer, res)
                if isinstance(res, str):
                    log(f"    image failed ({res}): {u[:90]}")
                    self.by_url[u] = None
                else:
                    self.by_url[u] = self._store(u, *res)
        return [self.by_url.get(u) if u else None for u in urls]
