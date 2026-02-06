#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

APP_NAME="Aliux"

# ---- Architecture (auto) ------------------------------------
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|aarch64) : ;;
  amd64) ARCH="x86_64" ;;
  arm64) ARCH="aarch64" ;;
  *)
    echo "ERREUR: architecture non supportée: $ARCH"
    exit 1
    ;;
esac

# ---- Version depuis aliux.py --------------------------------
# Attendu: APP_VERSION = "x.y.z"
APP_VERSION="$(
  python3 - <<'PY'
import re
from pathlib import Path
txt = Path("aliux.py").read_text(encoding="utf-8", errors="replace")
m = re.search(r'^\s*APP_VERSION\s*=\s*"([^"]+)"\s*$', txt, re.M)
print(m.group(1) if m else "0.0.0")
PY
)"

BUILD_DIR="$ROOT_DIR/build"
DIST_DIR="$ROOT_DIR/dist"
RELEASES_DIR="$ROOT_DIR/releases"
APPDIR="$BUILD_DIR/${APP_NAME}.AppDir"

mkdir -p "$BUILD_DIR" "$RELEASES_DIR"

# ---- Venv de build ------------------------------------------
if [[ ! -d ".venv-build" ]]; then
  python3 -m venv .venv-build
fi

# shellcheck disable=SC1091
source .venv-build/bin/activate

python -m pip install -U pip wheel setuptools
python -m pip install -U pyinstaller

if [[ -f "requirements.txt" ]]; then
  python -m pip install -r requirements.txt
fi

# ---- Nettoyage sorties précédentes --------------------------
rm -rf "$DIST_DIR" "$BUILD_DIR/pyinstaller" "$APPDIR"
mkdir -p "$BUILD_DIR/pyinstaller"

# ---- Build PyInstaller (onedir) ------------------------------
pyinstaller \
  --noconfirm \
  --clean \
  --onedir \
  --name "$APP_NAME" \
  --distpath "$DIST_DIR" \
  --workpath "$BUILD_DIR/pyinstaller" \
  --add-data "assets:assets" \
  --hidden-import "PIL.ImageTk" \
  --hidden-import "PIL._tkinter_finder" \
  aliux.py

# ---- Construction AppDir ------------------------------------
mkdir -p "$APPDIR/usr/bin"
cp -a "$DIST_DIR/$APP_NAME" "$APPDIR/usr/bin/$APP_NAME"

# AppRun (fallback sans readlink -f obligatoire)
cat > "$APPDIR/AppRun" <<'SH'
#!/bin/sh
set -eu

if command -v realpath >/dev/null 2>&1; then
  HERE="$(dirname "$(realpath "$0")")"
else
  HERE="$(cd "$(dirname "$0")" && pwd)"
fi

exec "$HERE/usr/bin/Aliux/Aliux" "$@"
SH
chmod +x "$APPDIR/AppRun"

# Desktop entry (racine AppDir)
cat > "$APPDIR/aliux.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Aliux
Comment=Installateur AppImage local
Exec=Aliux %U
Icon=aliux
Terminal=false
Categories=Utility;
StartupNotify=true
DESKTOP

# ---- Icône ---------------------------------------------------
# On utilise assets/aliuxico.png
if [[ -f "assets/aliuxico.png" ]]; then
  # icône à la racine (classique AppImage)
  cp -a "assets/aliuxico.png" "$APPDIR/aliux.png"

  # icône aussi dans hicolor (meilleure compatibilité menus)
  mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"
  cp -a "$APPDIR/aliux.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/aliux.png"
else
  echo "ERREUR: assets/aliuxico.png introuvable"
  exit 1
fi

# ---- Récupération appimagetool -------------------------------
APPIMAGETOOL="$BUILD_DIR/appimagetool-${ARCH}.AppImage"
if [[ ! -f "$APPIMAGETOOL" ]]; then
  if ! command -v curl >/dev/null 2>&1; then
    echo "ERREUR: curl est requis (ex: sudo apt install -y curl)"
    exit 1
  fi
  echo "Téléchargement appimagetool..."
  curl -L -o "$APPIMAGETOOL" \
    "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"
  chmod +x "$APPIMAGETOOL"
fi

# ---- Génération AppImage -------------------------------------
OUT="$RELEASES_DIR/${APP_NAME}-${APP_VERSION}-linux-${ARCH}.AppImage"
rm -f "$OUT"

ARCH="$ARCH" "$APPIMAGETOOL" "$APPDIR" "$OUT"

# ---- SHA256 ---------------------------------------------------
(
  cd "$RELEASES_DIR"
  sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256"
)

echo
echo "OK -> $OUT"
echo "OK -> $OUT.sha256"

# ---- Archive tar.gz de l’AppImage + SHA256 -------------------
TAR="$RELEASES_DIR/${APP_NAME}-${APP_VERSION}-linux-${ARCH}.tar.gz"
(
  cd "$RELEASES_DIR"
  tar -czf "$(basename "$TAR")" "$(basename "$OUT")"
  sha256sum "$(basename "$TAR")" > "$(basename "$TAR").sha256"
)

echo "OK -> $TAR"
echo "OK -> $TAR.sha256"
