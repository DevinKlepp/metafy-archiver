# metafy-archiver

Saves Metafy guides you've purchased as PDFs for offline reading.

For each guide it writes a folder under `guides/<guide title>/`:

| File | What it is |
| --- | --- |
| `<guide title> - 2026-11-11 2153.pdf` | Every section in one PDF, with video links inline and listed per section. Each run adds a new timestamped PDF; earlier ones are kept. |
| `guide.html` | Same content as a web page (uses `images/`) |
| `images/` | Every image from the guide |
| `videos.md` | All video links, grouped by section |
| `source.json` | Title, author, section titles, URLs and video links as data |

Videos are saved as links, not downloaded.

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
```

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
skipped on later runs; use `--force` to redo them (the previous PDF stays as an older version).

Useful options: `--match REGEX` (only some guides), `--paper A4`, `--delay SECONDS`,
`--selector CSS` (if the wrong part of the page is captured), `--login` (log in again),
`-o DIR` (output folder).

## Layout

- `metafy_archiver.py` crawls with a logged-in persistent Chrome profile, then renders the PDF
  with a separate clean headless Chromium so no session data leaks into the output.
- `js/` holds the scripts that run inside the page: `extract.js` turns a section into clean
  HTML plus image/video lists, `links.js` finds sibling sections (sidebar order wins),
  `scroll.js`/`expand.js` trigger lazy content, `login.js` guesses whether you are logged in.
- `tests/test_mock.py` runs the whole pipeline against the mock site in `tests/fixture/`:

```sh
.venv/bin/python tests/test_mock.py     # or: .venv/bin/python -m pytest tests
```

For personal backups of content you own access to. Don't redistribute the output.
