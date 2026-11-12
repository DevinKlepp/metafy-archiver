![metafy-archiver](docs/logo.svg "metafy-archiver")

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776ab?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Platforms](https://img.shields.io/badge/platforms-macOS%20%7C%20Linux%20%7C%20Windows-555)](#installing)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://github.com/DevinKlepp/metafy-archiver/actions/workflows/test.yml/badge.svg)](https://github.com/DevinKlepp/metafy-archiver/actions/workflows/test.yml)

metafy-archiver keeps offline copies of the [Metafy](https://metafy.gg) guides you have paid for:
one PDF per guide with every section and image, and the Metafy-hosted videos saved alongside as
MP4. It drives a real browser window in which you log in to Metafy yourself, so it never asks for
your password and only ever sees what you can see. Everything it saves stays in a `guides/`
folder inside the project.

![Archiving a guide from the terminal](docs/demo.gif)

## Table of Contents

- [What you get](#what-you-get)
- [Before you start](#before-you-start)
- [Installing](#installing)
  - [macOS and Linux](#macos-and-linux)
  - [Windows](#windows)
- [Usage](#usage)
  - [One guide](#one-guide)
  - [Your whole library](#your-whole-library)
  - [Running again](#running-again)
  - [Stopping](#stopping)
- [Options](#options)
  - [Videos](#videos)
  - [Look and size](#look-and-size)
  - [All options](#all-options)
- [Troubleshooting](#troubleshooting)
- [How it works](#how-it-works)
- [Development](#development)
- [Security and privacy](#security-and-privacy)
- [License](#license)

## What you get

Each guide becomes a folder `guides/<guide title>/` inside the project folder:

| File | What it is |
| --- | --- |
| `<guide title> - 2026-11-11 2335.pdf` | The whole guide as one PDF: cover, table of contents, every section, every image, and a video list per section. |
| `videos/` | Metafy-hosted videos as MP4 (matchup videos, coaching recordings and so on). |
| `guide.html` | The same content as a web page. |
| `images/` | Every image, downscaled so the PDF stays a sensible size. |
| `videos.md` | Every video link, grouped by section, with its host and whether a copy was saved. |
| `source.json` | Titles, section URLs, author and video details as data. |

<p align="center">
  <img src="docs/cover.png" width="640" alt="PDF cover page with author, section count and table of contents">
</p>

Every video in the PDF is labelled with its host, and a downloaded one shows the saved file.
YouTube, Vimeo and Twitch videos are never downloaded; the PDF links to them instead.

<p align="center">
  <img src="docs/video-chapter.png" width="640" alt="A section with a Metafy-hosted video box pointing at the saved MP4">
</p>

The archiver also keeps two small things of its own in the project folder: `.browser-profile/`,
the browser's saved Metafy login, and `.state.json`, the list of guides already done.

## Before you start

You need:

- **Python 3.10 or newer.** Check with `python3 --version` on macOS and Linux, or `py --version`
  on Windows. If it is missing, install it from [python.org](https://www.python.org/downloads/);
  on Windows tick **Add python.exe to PATH** in the installer.
- **A Metafy account** with purchased guides.
- About **1 GB of free disk** per guide with videos. A guide without videos is around 15 MB.

Google Chrome is used if it is installed, with its own separate profile; your normal Chrome and
its logins are untouched. Without Chrome, a bundled Chromium is downloaded during setup.

## Installing

Download the project: the green **Code** button on GitHub, then **Download ZIP**, and unzip it
(the folder is called `metafy-archiver-main`). Or clone it:

```sh
git clone https://github.com/DevinKlepp/metafy-archiver.git
```

Then run the setup once from inside that folder. It installs Python packages, the browser and
ffmpeg into a private `.venv` folder in the project. Nothing is installed system-wide.

### macOS and Linux

Open Terminal, go into the folder, and run:

```sh
cd metafy-archiver-main      # or metafy-archiver, if you cloned it
sh setup.sh
```

On Linux the script tells you if a system package is missing (the Python venv module on Debian
and Ubuntu, or the browser's libraries) and prints the one command that installs it. Run that,
then `sh setup.sh` again.

### Windows

1. Open the unzipped folder in File Explorer.
2. Hold **Shift**, right-click an empty spot in the folder, and choose **Open PowerShell window
   here** (or **Open in Terminal**).
3. Run:

```powershell
.\setup.cmd
```

`setup.cmd` runs the setup in a way that works even though Windows marks files from a downloaded
ZIP as "from the internet". Keep this PowerShell window open: you will use it to run the archiver.

<details>
<summary>What the setup scripts do, for anyone who prefers to run the steps by hand</summary>

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
```

On Windows the paths are `.venv\Scripts\pip` and `.venv\Scripts\python`.
</details>

## Usage

Commands below are written for macOS and Linux. On Windows, type `.\archive` wherever you see
`./archive`, in the PowerShell window opened in the project folder.

### One guide

Copy the guide's address from your browser. Any page of the guide works, including one of its
sections:

```sh
./archive "https://metafy.gg/guides/view/its-a-miracle-i-eb05-lWda8lXM30b"
```

A browser window opens. The first time, log in to Metafy in that window, then go back to the
terminal and press Enter. The archiver then walks every section, downloads the images and the
Metafy-hosted videos, and writes the PDF. Leave both windows alone until it prints `Done`. A
20-section guide with five videos takes about three minutes; videos are the slow part.

### Your whole library

```sh
./archive
```

The browser opens on your purchased-guides page. Log in if asked, press Enter, and every guide you
own is archived in turn, so expect a few minutes per guide. "Load more" buttons are clicked for
you, and guides already done are skipped.

To do only some guides, give part of their address:

```sh
./archive --match enel
```

### Running again

Guides already archived are skipped. Add `--force` to archive one again: you get a new
timestamped PDF next to the old one, the saved videos are reused rather than downloaded again,
and the cover page lists which sections are new, updated or removed since last time.

### Stopping

Press **Ctrl+C**. The guide being archived at that moment is discarded and will be done again
next time; guides finished earlier in the run are kept.

## Options

Everything is a command-line option; there is no configuration file. `./archive --help` lists
them all, and the table under [All options](#all-options) is the reference. A few deserve a word.

### Videos

Metafy serves its videos as signed streams that stop working within hours, which is why the
archiver saves them during the run. By default a video is kept exactly as served, up to 720p.
Three ways to make the folder smaller:

- `--video-max-height 480` takes the 480p stream instead. Instant, since nothing is re-encoded.
- `--compress-videos` re-encodes at 30 frames per second with the commentary audio in mono. The
  result is about half the size with no visible loss. Videos already saved by an earlier run are
  re-encoded from the local copy, with no new download.
- `--compress-videos small` goes to about a third of the size, with slight softening.

Measured on an 8-minute 720p matchup video that Metafy serves at 47 MB: `--compress-videos` gives
24 MB and `small` about 16 MB, each taking roughly 20 seconds on a recent Mac. The compressed
files are plain H.264 MP4, which plays on anything.

> [!NOTE]
> YouTube, Vimeo and Twitch videos are never downloaded, by design. They are stable links and
> the PDF points at them.

### Look and size

PDFs use a dark theme in Metafy's own colours by default, which is how the guides look on the
site and is easier on the eyes on a screen. `--theme light` gives plain black-on-white pages for
printing.

Images are downscaled to 1600 px on the long side and re-encoded as JPEG, which turns a 100 MB
PDF into a 15 MB one with no visible difference. `--max-image-px 0` keeps the originals.

### All options

| Option | Effect |
| --- | --- |
| `--force` | archive guides again even though they were already done |
| `--match TEXT` | library mode: only guides whose address contains TEXT (a regular expression) |
| `--no-videos` | keep Metafy-hosted videos as links only |
| `--video-max-height PX` | stream quality to take, default 720 |
| `--compress-videos [LEVEL]` | re-encode videos: `normal` (the default level, half the size) or `small` (a third) |
| `--max-image-px N` | image size limit, default 1600; `0` keeps originals |
| `--theme light` | plain paper look instead of the default dark theme |
| `--paper A4` | PDF paper size, default Letter |
| `-o DIR` | output folder, default `guides/` |
| `--zip` | after each guide, also pack its folder into `guides/<title>.zip`, handy for copying to another device |
| `--login` | pause for a login even though one is saved |
| `--library-url URL` | the page that lists your purchased guides, if Metafy moves it |
| `--browser chromium` | use the bundled Chromium instead of your installed Google Chrome |
| `--headless` | no browser window; needs a login saved by an earlier run |
| `--delay SECONDS` | pause between pages, default 1.5 |
| `--max-pages N` | stop after N sections of one guide, default 300 |
| `--selector CSS` | which part of the page to capture, if the automatic choice is wrong |
| `--ffmpeg PATH` | use a specific ffmpeg |

## Troubleshooting

**Signing in**

- *Google sign-in refuses to work in the opened window.* Google sometimes blocks automated
  browsers. Log in with email and password or Discord instead.
- *A section comes out nearly empty, and the run warns about it.* Usually the login expired. Run
  again with `--login`. The guide is not marked as done until it comes out complete.

**Output**

- *Videos are kept as links only.* The run says ffmpeg was not found. Run the setup again, or
  install ffmpeg yourself (`brew install ffmpeg` on a Mac) and pass `--ffmpeg PATH`.
- *The wrong part of the page is captured.* Pass `--selector` with a CSS selector for the guide
  body, for example `--selector article`.
- *"No guide links found" in library mode.* Pass guide addresses directly. The run writes
  `guides/library-debug.html`; share it if you want library mode fixed.
- *Start over.* Delete `.browser-profile/` (the saved login) and `.state.json` (what is done).

**Windows**

- *`setup.ps1 is not digitally signed`.* Run `.\setup.cmd` instead; it handles this.
- *Odd characters in the terminal.* Cosmetic. Use Windows Terminal, or ignore it; files are
  unaffected.

**Linux**

- *"Could not create the Python environment".* Debian and Ubuntu ship the venv module separately:
  `sudo apt install python3-venv`, then `sh setup.sh` again.
- *"The browser was downloaded but could not start".* A fresh install lacks the browser's system
  libraries. Run `sudo .venv/bin/python -m playwright install-deps chromium` once, then
  `sh setup.sh` again. Tested on Ubuntu 26.04.

**macOS**

- *`./setup.sh: Permission denied`.* Run `sh setup.sh` instead.
- *Google Chrome is not installed.* Nothing to do; the bundled Chromium is used automatically.

## How it works

```
 your Chrome profile ──► visit each section ──► js/extract.js cleans the page
        (login)                │                        │
                               │                 images/  videos/ (ffmpeg, while the
                               │                 (parallel, deduplicated, downscaled)   stream links are valid)
                               ▼
                         guide.html ──► clean headless Chromium ──► <title> - <time>.pdf
```

- `metafy_archiver.py` opens a persistent browser profile so your login is remembered, finds the
  guide's sections from its sidebar, and visits each one.
- `js/extract.js` runs inside the page: it drops app chrome, keeps the content and images, turns
  video players into labelled boxes and reads the signed stream link from Metafy's Mux player.
- `mfa_media.py` downloads images in parallel and deduplicates them by content, shrinks them,
  and saves Metafy-hosted streams with ffmpeg.
- `mfa_output.py` writes `guide.html`, `videos.md` and `source.json`, then a separate clean
  headless Chromium renders the PDF so no session data can leak into it.

Metafy's page structure can change. If an archive looks wrong after a site redesign, the
heuristics in `js/extract.js` are where to look.

## Development

```sh
.venv/bin/python tests/test_images.py   # image shrinking rules, a second
.venv/bin/python tests/test_mock.py     # the whole pipeline against tests/fixture/, ten seconds
.venv/bin/ruff check .                  # lint (pip install ruff)
```

The mock test serves a small fake guide site, archives it twice (the second time with a section
inserted and one edited), really downloads a clip with ffmpeg, and re-encodes it. A GitHub
Actions workflow in `.github/workflows/test.yml` runs `sh setup.sh` and the same tests on every
push, inside Playwright's Ubuntu image, so the exact steps a new user follows are what is tested.
Keep that image's tag in step with the `playwright` pin in `requirements.txt`.

`setup.sh` and `archive` are plain POSIX `sh`, so they run under dash, bash, zsh or busybox.
`docs/demo.gif` is rendered from a real, path-sanitised run by `docs/demo/render.py`.

## Security and privacy

- Your Metafy login lives only in `.browser-profile/` on your machine. It is never written into
  the archive; the PDF is rendered by a separate browser with no session at all.
- The archiver sends requests only to Metafy and its media hosts, with the same cookies your
  browser would send them.
- Signed stream links recorded in `source.json` are short-lived playback tokens, not account
  credentials.

This is for personal backups of content you have bought. Don't redistribute the output; the
coaches who write these guides are paid per sale.

## License

[MIT](LICENSE).
