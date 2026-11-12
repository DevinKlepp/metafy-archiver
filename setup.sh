#!/usr/bin/env bash
# One-time setup for macOS / Linux: creates a private Python environment in .venv,
# installs the dependencies and the browser the archiver drives. Safe to run again.
set -euo pipefail
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
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
.venv/bin/python -m playwright install chromium
chmod +x archive

cat <<EOF

Setup complete. To archive a guide:

  ./archive "https://metafy.gg/guides/view/<guide>"

A browser window opens; log in to Metafy the first time, then press Enter in this terminal.
To archive everything you have bought, run ./archive with no arguments.
EOF
