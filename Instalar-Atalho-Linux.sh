#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APPLICATIONS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP_FILE="$APPLICATIONS_DIR/organizapdf.desktop"
mkdir -p "$APPLICATIONS_DIR"

cat >"$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=OrganizaPDF
Comment=Unir e separar arquivos PDF
Exec=$APP_DIR/OrganizaPDF-Linux.sh
Icon=$APP_DIR/src/organizapdf/assets/icon.svg
Terminal=true
Categories=Office;Utility;
StartupNotify=true
EOF

chmod +x "$APP_DIR/OrganizaPDF-Linux.sh" "$DESKTOP_FILE"
command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database "$APPLICATIONS_DIR" >/dev/null 2>&1 || true

echo "Atalho instalado no menu de aplicativos: OrganizaPDF"

