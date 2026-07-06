#!/bin/bash
# Double-clickable LocalFlow launcher (macOS; also runs on Linux).
#
# First run: creates a virtual environment in .venv and installs the app.
# Later runs: reuses it, and picks up any `git pull` automatically thanks
# to the editable install.
set -e
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    echo "First run — setting up a virtual environment..."
    python3 -m venv .venv
fi

./.venv/bin/pip install --quiet --editable . || {
    echo "Install failed — trying again with full output:"
    ./.venv/bin/pip install --editable .
}

exec ./.venv/bin/localflow "$@"
