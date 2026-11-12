# metafy-archiver

Keep offline copies of the [Metafy](https://metafy.gg) guides you have paid for: one PDF per
guide with every section, every image, and the Metafy-hosted videos saved alongside as MP4.

It drives a real browser with your own Metafy login, so it only sees what you can see.
Nothing is uploaded anywhere; everything lands in a `guides/` folder on your computer.

## What you get

For each guide, a folder `guides/<guide title>/` containing:

| File | What it is |
| --- | --- |
| `<guide title> - 2026-11-11 2153.pdf` | The whole guide as one PDF: cover, table of contents, every section, images, and a video list per section. Re-runs add a new timestamped PDF and keep the old one. |
| `videos/` | Metafy-hosted videos as MP4 (the matchup videos, coaching recordings and so on). YouTube, Vimeo and Twitch videos are never downloaded; the PDF links to them instead. |
| `guide.html` | The same content as a web page you can open in a browser. |
| `images/` | Every image, downscaled so the PDF stays a sensible size. |
| `videos.md` | Every video link, grouped by section, with where it is hosted and whether a copy was saved. |
| `source.json` | Titles, section URLs, author and video details as data. |

Each video in the PDF is labelled with its host, for example "Metafy-hosted video" or
"YouTube video", and downloaded ones show the saved file name.

Running it again on a guide you already archived tells you what changed since last time
(new, updated or removed sections) on the cover page and in the table of contents.

## Setup

You need Python 3.10 or newer. Check with `python3 --version` (Mac/Linux) or `py --version`
(Windows); if it is missing, install it from [python.org](https://www.python.org/downloads/).

Download this project (the green "Code" button on GitHub, "Download ZIP", then unzip; or
`git clone`), open a terminal in the project folder, and run the setup once:

```sh
./setup.sh          # macOS / Linux
.\setup.ps1         # Windows, in PowerShell
```

It creates a private Python environment inside the folder, installs the dependencies and
downloads the browser it drives. Nothing is installed system-wide.

## Use

Archive one guide (any section URL of the guide works):

```sh
./archive "https://metafy.gg/guides/view/its-a-miracle-i-eb05-lWda8lXM30b"
```

On Windows use `.\archive` instead of `./archive`.

A browser window opens. The first time, log in to Metafy there, then press Enter in the
terminal. The archiver walks through every section, downloads images and Metafy-hosted
videos, and writes the PDF. A 20-section guide with five videos takes a few minutes; later
runs reuse the videos already saved.

Archive everything you have bought:

```sh
./archive
```

The browser opens on Metafy. Log in if needed, open the page that lists your purchased guides,
then press Enter. Every guide linked from that page is archived; ones already done are skipped.

### Options

| Option | Effect |
| --- | --- |
| `--force` | re-archive guides that were already done (earlier PDFs and videos are kept) |
| `--no-videos` | do not download Metafy-hosted videos, keep links only |
| `--match REGEX` | only archive guides whose URL matches, in library mode |
| `--max-image-px N` | image size limit, default 1600; `0` keeps originals (much bigger PDFs) |
| `--paper A4` | PDF paper size (default Letter) |
| `-o DIR` | output folder (default `guides/`) |
| `--login` | log in again even though a session is saved |
| `--browser chromium` | use the bundled Chromium instead of your installed Google Chrome |
| `--headless` | no browser window; only works once you are logged in |
| `--selector CSS` | if the wrong part of the page is captured |
| `--ffmpeg PATH` | use a specific ffmpeg |

`./archive --help` lists them all.

## Troubleshooting

- **Google sign-in refuses to work in the opened window.** Google sometimes blocks
  automated browsers. Log in with email and password or Discord instead.
- **"No guide links found" in library mode.** Pass guide URLs directly as shown above, and
  send the `guides/library-debug.html` file it writes if you want library mode fixed.
- **A section comes out nearly empty.** The run prints a warning for it. Usually the login
  has expired: run again with `--login`.
- **Videos are kept as links only.** The run says ffmpeg was not found. Re-run `./setup.sh`,
  or install ffmpeg yourself (`brew install ffmpeg` on a Mac).
- **Wrong part of the page captured.** Pass `--selector` with a CSS selector for the
  guide body, for example `--selector article`.
- **Start over.** Delete `.browser-profile/` (saved login) and `.state.json` (what is done).

## How it works

- `metafy_archiver.py` opens a persistent Chrome profile (so your login is remembered),
  finds the guide's sections from its sidebar, and visits each one.
- `js/extract.js` runs inside each page and turns the section into clean HTML: it drops
  app chrome, keeps images, turns video players into labelled boxes and reads the Mux
  player's signed stream link.
- `mfa_media.py` downloads images in parallel, deduplicates them by content, shrinks them,
  and saves Metafy-hosted streams with ffmpeg while their signed links are still valid
  (they expire within hours).
- `mfa_output.py` writes `guide.html`, `videos.md` and `source.json`, then a clean headless
  Chromium renders the PDF so no session data can leak into it.
- `tests/` runs the whole pipeline against a mock guide site, including a real ffmpeg
  download, in about ten seconds:

```sh
.venv/bin/python tests/test_images.py && .venv/bin/python tests/test_mock.py
```

Metafy's page structure can change; if an archive looks wrong after a site redesign, the
mock test will still pass but the heuristics in `js/extract.js` will need adjusting.

## Fair use

This is for personal backups of content you have bought. Your login stays on your machine.
Don't redistribute the output; the coaches who wrote these guides are paid per sale.

MIT licensed, see `LICENSE`.
