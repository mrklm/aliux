#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------
# Build Linux AppImage pour Aliux
# Sorties dans ./releases/
#
# Nettoyage après succès :
#   - build/
#   - dist/
#   - *.spec
#   - .venv-build
# ------------------------------------------------------------

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

APP_NAME="Aliux"

# ---- Helpers -------------------------------------------------
need_cmd() { command -v "$1" >/dev/null 2>&1; }
die() { echo "ERREUR: $*" >&2; exit 1; }
log() { echo "▶ $*"; }

cleanup_success() {
  log "Nettoyage après succès…"
  # Désactiver venv si actif (ne pas échouer si deactivate absent)
  if declare -F deactivate >/dev/null 2>&1; then
    deactivate || true
  fi

  rm -rf "$ROOT_DIR/build" "$ROOT_DIR/dist" "$ROOT_DIR/.venv-build"
  rm -f "$ROOT_DIR"/*.spec
  log "Nettoyage terminé."
}

SUCCESS=0
trap 'if [[ "$SUCCESS" -eq 1 ]]; then cleanup_success; fi' EXIT

# ---- Vérifications dépendances système ----------------------
need_cmd python3.12 || die "python3.12 est requis (ex: sudo apt install -y python3.12 python3.12-venv)"
need_cmd curl      || die "curl est requis (ex: sudo apt install -y curl)"
need_cmd objdump   || die "objdump est requis (paquet binutils) (ex: sudo apt install -y binutils)"

# Vérifier que le module venv est disponible (python3.12-venv)
python3.12 - <<'PY' >/dev/null 2>&1 || die "Le module venv manque pour python3.12 (installez python3.12-venv)"
import venv
PY

# ---- Architecture (auto) ------------------------------------
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|aarch64) : ;;
  amd64) ARCH="x86_64" ;;
  arm64) ARCH="aarch64" ;;
  *)
    die "architecture non supportée: $ARCH"
    ;;
esac

# ---- Version depuis aliux.py --------------------------------
# Attendu: APP_VERSION = "x.y.z"
APP_VERSION="$(
  python3.12 - <<'PY'
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

# ---- Venv de build (recréé à chaque build) -------------------
rm -rf .venv-build
python3.12 -m venv .venv-build
# shellcheck disable=SC1091
source .venv-build/bin/activate

# ---- Garde-fou: vérifier que pip vient du venv ---------------
python -m pip install -U pip setuptools wheel

PIP_PATH="$(python -c 'import pip, os; print(os.path.abspath(pip.__file__))')"
case "$PIP_PATH" in
  *"/.venv-build/"*) : ;;
  *)
    die "pip ne vient pas du venv (.venv-build). Chemin: $PIP_PATH"
    ;;
esac

# ---- Dépendances build ---------------------------------------
python -m pip install -U pyinstaller

# Runtime deps
if [[ -f "requirements.txt" ]]; then
  python -m pip install -r requirements.txt
fi

# ---- Nettoyage sorties précédentes ---------------------------
rm -rf "$DIST_DIR" "$BUILD_DIR/pyinstaller" "$APPDIR"
mkdir -p "$BUILD_DIR/pyinstaller"

# ---- Build PyInstaller (onedir) ------------------------------
# Remarque: --add-data sous Linux utilise ":" (et non ";").
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
  # Icône à la racine (classique AppImage)
  cp -a "assets/aliuxico.png" "$APPDIR/aliux.png"

  # Icône aussi dans hicolor (meilleure compatibilité menus)
  mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"
  cp -a "$APPDIR/aliux.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/aliux.png"
else
  die "assets/aliuxico.png introuvable"
fi

# ---- Récupération appimagetool -------------------------------
APPIMAGETOOL="$BUILD_DIR/appimagetool-${ARCH}.AppImage"
if [[ ! -f "$APPIMAGETOOL" ]]; then
  log "Téléchargement appimagetool (${ARCH})…"
  curl -L -o "$APPIMAGETOOL" \
    "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"
  chmod +x "$APPIMAGETOOL"
fi

# ---- Génération AppImage -------------------------------------
OUT="$RELEASES_DIR/${APP_NAME}-${APP_VERSION}-linux-${ARCH}.AppImage"
rm -f "$OUT"

# Tentative 1: exécuter appimagetool.AppImage directement.
# Si FUSE manque, fallback par extraction.
if ARCH="$ARCH" "$APPIMAGETOOL" "$APPDIR" "$OUT"; then
  :
else
  log "appimagetool.AppImage a échoué (souvent FUSE manquant). Fallback: extraction…"
  EXTRACT_DIR="$BUILD_DIR/appimagetool-extract"
  rm -rf "$EXTRACT_DIR"
  mkdir -p "$EXTRACT_DIR"

  (cd "$EXTRACT_DIR" && "$APPIMAGETOOL" --appimage-extract >/dev/null)
  ARCH="$ARCH" "$EXTRACT_DIR/squashfs-root/AppRun" "$APPDIR" "$OUT"
fi

# ---- SHA256 AppImage -----------------------------------------
(
  cd "$RELEASES_DIR"
  sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256"
)

# ---- Archive tar.gz de l’AppImage + SHA256 -------------------
TAR="$RELEASES_DIR/${APP_NAME}-${APP_VERSION}-linux-${ARCH}.tar.gz"
(
  cd "$RELEASES_DIR"
  tar -czf "$(basename "$TAR")" "$(basename "$OUT")"
  sha256sum "$(basename "$TAR")" > "$(basename "$TAR").sha256"
)

echo
echo "OK -> $OUT"
echo "OK -> $OUT.sha256"
echo "OK -> $TAR"
echo "OK -> $TAR.sha256"

# ---- Marquer succès (déclenche le nettoyage via trap) --------
SUCCESS=1
