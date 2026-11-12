#!/bin/sh
# One-time setup for macOS / Linux: creates a private Python environment in .venv,
# installs the dependencies and the browser the archiver drives. Safe to run again.
# Plain POSIX sh on purpose: works with dash, bash, zsh or busybox, so no particular shell is needed.
set -eu
cd "$(dirname "$0")"

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 or newer is needed. Install it from https://www.python.org/downloads/ (or 'brew install python') and run this again." >&2
  exit 1
fi

echo "Using $($PY --version) at $(command -v "$PY")"
if [ ! -x .venv/bin/python ]; then
  # A failed attempt leaves a half-made .venv behind; clear it so the next run starts clean.
  if ! "$PY" -m venv .venv; then
    rm -rf .venv
    echo "" >&2
    echo "Could not create the Python environment. On Debian or Ubuntu the venv module is a separate package:" >&2
    echo "  sudo apt install python3-venv" >&2
    echo "then run this again." >&2
    exit 1
  fi
fi
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
.venv/bin/python -m playwright install chromium
chmod +x archive

# Make sure the browser actually starts: on a fresh Linux it usually needs system libraries.
if ! .venv/bin/python - <<'PY' 2>/tmp/mfa-browser-check.log
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    p.chromium.launch(headless=True).close()
PY
then
  echo "" >&2
  echo "The browser was downloaded but could not start (details in /tmp/mfa-browser-check.log)." >&2
  if [ "$(uname -s)" = Linux ]; then
    echo "On Linux this means missing system libraries. Install them with:" >&2
    echo "  sudo .venv/bin/python -m playwright install-deps chromium" >&2
    echo "then run ./setup.sh again." >&2
  fi
  exit 1
fi

cat <<EOF

Setup complete. To archive a guide:

  ./archive "https://metafy.gg/guides/view/<guide>"

A browser window opens; log in to Metafy the first time, then press Enter in this terminal.
To archive everything you have bought, run ./archive with no arguments.
EOF
