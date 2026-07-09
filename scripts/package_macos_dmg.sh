#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
APP_NAME="Data Boundary"
DIST="$ROOT/dist"
BUILD="$ROOT/build"
DMG_DIR="$BUILD/dmg-root"
DMG_PATH="$DIST/${APP_NAME}.dmg"
PKG_DATA_ROOT="$BUILD/package-data"

cd "$BACKEND"

rm -rf "$BUILD" "$DIST/${APP_NAME}.app" "$DMG_PATH"
mkdir -p "$DIST" "$DMG_DIR" "$PKG_DATA_ROOT/data" "$PKG_DATA_ROOT/privacy"

cp "$BACKEND/app/data/datause.html" "$PKG_DATA_ROOT/data/datause.html"
cp "$BACKEND/app/privacy/source_registry.json" "$PKG_DATA_ROOT/privacy/source_registry.json"
rsync -a \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  "$BACKEND/app/domain_packs/" "$PKG_DATA_ROOT/domain_packs/"

python3 -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "$APP_NAME" \
  --distpath "$DIST" \
  --workpath "$BUILD/pyinstaller" \
  --specpath "$BUILD" \
  --collect-submodules webview \
  --collect-submodules uvicorn \
  --add-data "$PKG_DATA_ROOT/data:app/data" \
  --add-data "$PKG_DATA_ROOT/domain_packs:app/domain_packs" \
  --add-data "$PKG_DATA_ROOT/privacy/source_registry.json:app/privacy" \
  app/desktop_entry.py

APP_PATH="$DIST/${APP_NAME}.app"
if [[ ! -d "$APP_PATH" ]]; then
  echo "Expected app bundle not found: $APP_PATH" >&2
  exit 1
fi

# Ad-hoc sign so macOS treats the local build as a coherent app bundle.
codesign --force --deep --sign - "$APP_PATH" >/dev/null

cp -R "$APP_PATH" "$DMG_DIR/"
ln -s /Applications "$DMG_DIR/Applications"

hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$DMG_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH" >/dev/null

echo "$DMG_PATH"
