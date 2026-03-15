#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INSTALL_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/novaplay"
APP_DIR="$INSTALL_HOME/app"
VENV_DIR="$INSTALL_HOME/venv"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
DESKTOP_FILE="$APPS_DIR/novaplay.desktop"
LAUNCHER="$BIN_DIR/novaplay"
DESKTOP_TEMPLATE="$ROOT_DIR/packaging/linux/novaplay.desktop.in"

if [[ ! -f "$ROOT_DIR/main.py" ]]; then
  echo "Error: run this installer from inside the NovaPlay repository."
  exit 1
fi

mkdir -p "$APP_DIR" "$BIN_DIR" "$APPS_DIR" "$ICON_DIR"

# Copy project files into a stable user-local install directory.
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.venv' \
    --exclude 'env' \
    "$ROOT_DIR/" "$APP_DIR/"
else
  rm -rf "$APP_DIR"
  mkdir -p "$APP_DIR"
  cp -a "$ROOT_DIR/." "$APP_DIR/"
  rm -rf "$APP_DIR/.git" "$APP_DIR/__pycache__"
fi

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip wheel
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"

cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "$APP_DIR"
exec "$VENV_DIR/bin/python" "$APP_DIR/main.py" "\$@"
EOF
chmod +x "$LAUNCHER"

cp -f "$APP_DIR/assets/icons/NovaPlay.svg" "$ICON_DIR/novaplay.svg"
sed "s|{{EXEC_PATH}}|$LAUNCHER|g" "$DESKTOP_TEMPLATE" > "$DESKTOP_FILE"
chmod +x "$DESKTOP_FILE"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" || true
fi

echo "NovaPlay installed successfully."
echo "Launch from app menu: NovaPlay"
echo "Or from terminal: novaplay"
