"""Render docs/demo/session.txt (a condensed, path-sanitised real run) as docs/demo.gif.

    .venv/bin/python docs/demo/render.py

Lines starting with '$ ' are typed out; lines starting with '~' are 'waiting' lines that hold a
little longer. Only Pillow is needed.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
COLS, ROWS, CW, LH, PAD, BAR = 106, 30, 9, 20, 16, 34
BG, FG, DIM, PROMPT, OK, BLUE = "#1b1e28", "#d7dae0", "#8a90a0", "#7ee787", "#7ee787", "#79b8ff"


def font(size: int):
    for cand in ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/SFNSMono.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "C:/Windows/Fonts/consola.ttf"):
        try:
            return ImageFont.truetype(cand, size)
        except OSError:
            continue
    return ImageFont.load_default()


F = font(15)
W, H = COLS * CW + 2 * PAD, BAR + ROWS * LH + PAD


def colour(line: str) -> str:
    if line.startswith("$ "):
        return FG
    if "video saved" in line or line.startswith("  saved:") or line.startswith("Done"):
        return OK
    if line.startswith("  - ") or "downloading" in line:
        return BLUE
    if line.startswith("      ...") or line.startswith("[") or "using the" in line:
        return DIM
    return FG


def frame(lines: list[str], cursor: bool) -> Image.Image:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, BAR), fill="#2a2e3a")
    for i, c in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        d.ellipse((14 + i * 22, 10, 28 + i * 22, 24), fill=c)
    d.text((W / 2 - 60, 8), "metafy-archiver", font=F, fill=DIM)
    shown = lines[-ROWS:]
    for r, line in enumerate(shown):
        y = BAR + 6 + r * LH
        if line.startswith("$ "):
            d.text((PAD, y), "❯", font=F, fill=PROMPT)
            d.text((PAD + 2 * CW, y), line[2:][:COLS - 2], font=F, fill=FG)
        else:
            d.text((PAD, y), line[:COLS], font=F, fill=colour(line))
    if cursor and shown:
        last = shown[-1]
        x = PAD + (2 * CW if last.startswith("$ ") else 0) + min(len(last[2:] if last.startswith("$ ") else last), COLS) * CW
        d.rectangle((x + 2, BAR + 6 + (len(shown) - 1) * LH + 2, x + CW, BAR + 6 + (len(shown) - 1) * LH + LH - 4), fill=FG)
    return im


def main() -> None:
    src = [ln.rstrip("\n") for ln in (HERE / "session.txt").read_text(encoding="utf-8").splitlines()]
    frames: list[tuple[Image.Image, int]] = []
    lines: list[str] = []
    for raw in src:
        wait = raw.startswith("~")
        line = raw[1:] if wait else raw
        if line.startswith("$ "):
            cmd = line[2:]
            for i in range(0, len(cmd) + 1, 3):
                frames.append((frame(lines + ["$ " + cmd[:i]], True), 45))
            lines.append(line)
            frames.append((frame(lines, False), 500))
            continue
        lines.append(line)
        hold = 900 if wait else (260 if line.startswith("  - ") else 140)
        frames.append((frame(lines, False), hold))
    frames.append((frame(lines, False), 4000))
    imgs = [f.quantize(colors=48, method=Image.Quantize.MEDIANCUT) for f, _ in frames]
    imgs[0].save(HERE.parent / "demo.gif", save_all=True, append_images=imgs[1:],
                 duration=[d for _, d in frames], loop=0, optimize=True)
    print(f"wrote {HERE.parent / 'demo.gif'} ({len(frames)} frames, {(HERE.parent / 'demo.gif').stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
