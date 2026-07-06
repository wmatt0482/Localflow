#!/bin/bash
# Build LocalFlow.app — a standalone macOS app you can drag into
# /Applications. Double-click this file (or run ./build_app.command).
set -e
cd "$(dirname "$0")"

if [ "$(uname)" != "Darwin" ]; then
    echo "This build script must run on macOS."
    exit 1
fi

[ -x .venv/bin/python ] || python3 -m venv .venv
echo "Installing build dependencies..."
./.venv/bin/pip install --quiet --editable ".[macapp]"

echo "Building LocalFlow.app (takes a few minutes the first time)..."
./.venv/bin/pyinstaller --noconfirm --clean packaging/LocalFlow.spec

echo
echo "Done! Built: dist/LocalFlow.app"
echo "Drag it into /Applications, then launch it from Spotlight."
echo "To start it automatically at login: System Settings > General >"
echo "Login Items > add LocalFlow."
open dist 2>/dev/null || true
