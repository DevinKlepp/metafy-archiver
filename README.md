# metafy-archiver

Saves Metafy guides you've purchased as PDFs for offline reading, including the videos.

For each guide it writes a folder under `guides/<guide title>/`:

| File | What it is |
| --- | --- |
| `<guide title> - 2026-11-11 2153.pdf` | Every section in one PDF, with video links inline and listed per section. Each run adds a new timestamped PDF; earlier ones are kept. |
| `videos/` | Metafy-hosted videos saved as MP4. Their stream links are signed and expire within hours, so they are downloaded during the run. YouTube/Vimeo/Twitch videos stay links. |
| `guide.html` | Same content as a web page (uses `images/` and `videos/`) |
| `images/` | Every image from the guide, downscaled to 1600 px for a sane PDF size |
| `videos.md` | All video links, grouped by section, with where each one is hosted and whether it was saved |
| `source.json` | Title, author, section titles, URLs and video details as data |

In the PDF every video box says where the video is hosted ("Metafy-hosted video" or
"YouTube video") and, for downloaded ones, names the saved file.

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
```

`requirements.txt` brings in Playwright (browser), Pillow (image shrinking) and imageio-ffmpeg
(a static ffmpeg for the video downloads). An `ffmpeg` on your PATH is used in preference.

## Use

```sh
# Everything in your library: a Chrome window opens, log in, open the page
# listing your purchased guides, then press Enter in the terminal.
.venv/bin/python metafy_archiver.py

# Specific guides (any section URL of the guide works)
.venv/bin/python metafy_archiver.py https://metafy.gg/guides/view/<guide-slug>
```

The login is kept in `.browser-profile/`, so you only log in once. If the saved session has
expired the script notices and pauses for you to log in again. Guides already archived are
skipped on later runs; use `--force` to redo them (the previous PDF stays as an older version,
and videos already saved are not downloaded again).

Useful options:

| Option | Effect |
| --- | --- |
| `--match REGEX` | only archive guides whose URL matches |
| `--no-videos` | keep Metafy-hosted videos as links only (they expire) |
| `--max-image-px N` | image size limit, default 1600; `0` keeps originals |
| `--paper A4` | PDF paper size |
| `--selector CSS` | if the wrong part of the page is captured |
| `--login` | log in again |
| `-o DIR` | output folder |
| `--ffmpeg PATH` | use a specific ffmpeg |

## Layout

- `metafy_archiver.py` crawls with a logged-in persistent Chrome profile, downloads images and
  Metafy-hosted streams as it goes, then renders the PDF with a separate clean headless Chromium
  so no session data leaks into the output.
- `js/` holds the scripts that run inside the page: `extract.js` turns a section into clean
  HTML plus image/video lists (and reads the Mux player's signed stream URL), `links.js` finds
  sibling sections (sidebar order wins), `scroll.js`/`expand.js` trigger lazy content,
  `login.js` guesses whether you are logged in.
- `tests/test_mock.py` runs the whole pipeline against the mock site in `tests/fixture/`,
  including a real ffmpeg download of a locally served clip:

```sh
.venv/bin/python tests/test_mock.py     # or: .venv/bin/python -m pytest tests
```

For personal backups of content you own access to. Don't redistribute the output.
