#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${VERSION:-v0.1.0-alpha.1}"
APP_NAME="Data Boundary"
PKG_NAME="Data-Boundary-${VERSION#v}"
RELEASE_ROOT="$ROOT/release/github"
SOURCE_STAGE="$RELEASE_ROOT/$PKG_NAME"
ASSETS_DIR="$RELEASE_ROOT/assets"
DMG_PATH="$ROOT/dist/${APP_NAME}.dmg"

rm -rf "$RELEASE_ROOT"
mkdir -p "$SOURCE_STAGE" "$ASSETS_DIR"

copy_dir() {
  local src="$1"
  local dst="$2"
  if [[ -d "$src" ]]; then
    rsync -a \
      --exclude '.DS_Store' \
      --exclude '__pycache__' \
      --exclude '*.pyc' \
      --exclude '.pytest_cache' \
      --exclude '.memsearch' \
      --exclude '.playwright-mcp' \
      --exclude 'build' \
      --exclude 'dist' \
      --exclude 'release' \
      --exclude 'tasks' \
      --exclude '111.md' \
      --exclude '111.pdf' \
      --exclude '*.png' \
      --exclude 'app/data/index.html' \
      --exclude 'app/data/datause.v03.bak.html' \
      "$src/" "$dst/"
  fi
}

copy_dir "$ROOT/backend" "$SOURCE_STAGE/backend"
copy_dir "$ROOT/docs" "$SOURCE_STAGE/docs"
copy_dir "$ROOT/scripts" "$SOURCE_STAGE/scripts"
copy_dir "$ROOT/.github" "$SOURCE_STAGE/.github"

for file in .gitignore LICENSE README.md SECURITY.md PRIVACY.md CHANGELOG.md; do
  if [[ -f "$ROOT/$file" ]]; then
    cp "$ROOT/$file" "$SOURCE_STAGE/$file"
  fi
done

chmod +x "$SOURCE_STAGE/scripts/package_macos_dmg.sh" || true
chmod +x "$SOURCE_STAGE/scripts/prepare_github_release.sh" || true

if [[ -f "$DMG_PATH" ]]; then
  cp "$DMG_PATH" "$ASSETS_DIR/${APP_NAME}.dmg"
  (
    cd "$ASSETS_DIR"
    shasum -a 256 "${APP_NAME}.dmg" > SHA256SUMS.txt
  )
else
  echo "Warning: DMG not found at $DMG_PATH. Run scripts/package_macos_dmg.sh first." >&2
fi

(
  cd "$RELEASE_ROOT"
  zip -qr "$PKG_NAME-source.zip" "$PKG_NAME"
  shasum -a 256 "$PKG_NAME-source.zip" >> "$ASSETS_DIR/SHA256SUMS.txt"
)

python3 - "$RELEASE_ROOT" <<'PY'
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
disallowed_names = {".DS_Store", ".pytest_cache", "__pycache__"}
disallowed_dirs = {".memsearch", ".playwright-mcp", "build", "dist", "tasks"}
offenders = []
for path in root.rglob("*"):
    parts = set(path.parts)
    if path.name in disallowed_names or parts & disallowed_dirs:
        offenders.append(path.as_posix())

secret_patterns = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}"),
    re.compile(r'"api_key"\s*:\s*"[^"<>\s][^"]{12,}"'),
]
secret_hits = []
for path in root.rglob("*"):
    if not path.is_file():
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    for pattern in secret_patterns:
        if pattern.search(text):
            secret_hits.append(path.as_posix())
            break

if offenders or secret_hits:
    if offenders:
        print("Disallowed release files:", *sorted(offenders), sep="\n", file=sys.stderr)
    if secret_hits:
        print("Possible secrets:", *sorted(secret_hits), sep="\n", file=sys.stderr)
    raise SystemExit(1)
PY

echo "$RELEASE_ROOT"
