"""Unit tests for the image shrinking rules (no browser needed)."""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mfa_media as mm  # noqa: E402


def card(w: int, h: int, radius: int = 40) -> Image.Image:
    """Opaque art with transparent rounded corners, like a trading card image."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=(200, 40, 40, 255))
    return im


def noisy(w: int, h: int) -> Image.Image:
    """Incompressible RGB content, so a PNG of it is large."""
    import random
    random.seed(1)
    im = Image.new("RGB", (w, h))
    im.putdata([(random.randrange(256), random.randrange(256), random.randrange(256)) for _ in range(w * h)])
    return im


def run(tmp: Path) -> None:
    # 1. Big PNG gets downscaled and becomes JPEG.
    p = tmp / "wide.png"; noisy(2400, 300).save(p)
    out = mm.shrink_image(p, 1600)
    assert out.suffix == ".jpg" and not p.exists() and Image.open(out).size == (1600, 200), out

    # 2. Small flat PNG is left alone.
    p = tmp / "small.png"; Image.new("RGB", (200, 120), (10, 20, 30)).save(p)
    assert mm.shrink_image(p, 1600) == p and p.exists()

    # 3. Large-but-not-wide flat PNG (> 300 KB) is re-encoded as JPEG even without resizing.
    p = tmp / "heavy.png"; noisy(800, 600).save(p)
    assert p.stat().st_size > 300_000
    out = mm.shrink_image(p, 1600)
    assert out.suffix == ".jpg" and not p.exists(), out

    # 4. WebP is always re-encoded (Chromium stores WebP as raw pixels in PDFs).
    p = tmp / "photo.webp"; Image.new("RGB", (640, 360), (90, 120, 150)).save(p, "WEBP")
    out = mm.shrink_image(p, 1600)
    assert out.suffix == ".jpg" and not p.exists(), out

    # 5. Card art with transparent corners (mostly opaque) is flattened onto white as JPEG.
    p = tmp / "card.webp"; card(600, 837).save(p, "WEBP")
    out = mm.shrink_image(p, 1600)
    assert out.suffix == ".jpg", out
    corner = Image.open(out).getpixel((2, 2))
    assert all(c > 240 for c in corner), corner  # transparent corner became white

    # 6. A genuinely transparent graphic (mostly transparent) stays PNG.
    p = tmp / "logo.png"
    im = Image.new("RGBA", (400, 400), (0, 0, 0, 0)); ImageDraw.Draw(im).ellipse((150, 150, 250, 250), fill=(0, 0, 255, 255)); im.save(p)
    out = mm.shrink_image(p, 200)
    assert out.suffix == ".png" and Image.open(out).size == (200, 200) and Image.open(out).mode == "RGBA", out

    # 7. Oversized JPEG is resized in place.
    p = tmp / "shot.jpg"; Image.new("RGB", (3000, 2000), (5, 5, 5)).save(p, "JPEG")
    assert mm.shrink_image(p, 1600) == p and Image.open(p).size == (1600, 1067)

    # 8. max_px=0 disables everything; SVG/GIF are never touched.
    p = tmp / "x.png"; noisy(2400, 300).save(p)
    assert mm.shrink_image(p, 0) == p and Image.open(p).size == (2400, 300)
    p = tmp / "anim.gif"; Image.new("P", (2400, 300)).save(p)
    assert mm.shrink_image(p, 100) == p

    # 9. A corrupt file is left as is rather than crashing the run.
    p = tmp / "bad.png"; p.write_bytes(b"not an image")
    assert mm.shrink_image(p, 1600) == p and p.exists()


def test_shrink_image(tmp_path: Path) -> None:
    run(tmp_path)


if __name__ == "__main__":
    d = Path(tempfile.mkdtemp(prefix="mfa-img-"))
    try:
        run(d)
        print("OK")
    finally:
        shutil.rmtree(d, ignore_errors=True)
