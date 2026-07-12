#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE_NAME="BazaarPlusPlus"
PACKAGE_DIR="$ROOT/.build/package"
STAGE="$PACKAGE_DIR/$PACKAGE_NAME"
VERSION="$(node -p "JSON.parse(require('fs').readFileSync('$ROOT/package.json', 'utf8')).version")"

cd "$ROOT"
pnpm run check
pnpm run test
pnpm run build

rm -rf "$PACKAGE_DIR"
mkdir -p "$STAGE/dist"
cp "$ROOT/dist/index.js" "$STAGE/dist/index.js"
cp "$ROOT/main.py" "$ROOT/package.json" "$ROOT/plugin.json" "$ROOT/LICENSE" "$ROOT/README.md" "$ROOT/README_en.md" "$STAGE/"
cp -R "$ROOT/backend" "$STAGE/backend"

cd "$PACKAGE_DIR"
zip -qr "BazaarPlusPlus-${VERSION}.zip" "$PACKAGE_NAME"
python3 -B "$ROOT/tests/packaging/bundle_smoke.py" "$PACKAGE_DIR/BazaarPlusPlus-${VERSION}.zip"
echo "Created $PACKAGE_DIR/BazaarPlusPlus-${VERSION}.zip"
