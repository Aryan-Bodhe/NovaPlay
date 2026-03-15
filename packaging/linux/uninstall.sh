#!/usr/bin/env bash
set -euo pipefail

INSTALL_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/novaplay"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"

rm -rf "$INSTALL_HOME"
rm -f "$BIN_DIR/novaplay"
rm -f "$APPS_DIR/novaplay.desktop"
rm -f "$ICON_DIR/novaplay.svg"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" || true
fi

echo "NovaPlay uninstalled."
