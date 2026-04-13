#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
APP_NAME="${APP_NAME:-sni-forwarder}"

echo "Installing build dependencies..."
"$PYTHON_BIN" -m pip install -r requirements-build.txt

echo "Building Linux binary..."
"$PYTHON_BIN" -m PyInstaller \
  --clean \
  --noconfirm \
  --onefile \
  --name "$APP_NAME" \
  --add-data "config.json:." \
  main.py

chmod +x "dist/$APP_NAME"
echo "Build finished: dist/$APP_NAME"
