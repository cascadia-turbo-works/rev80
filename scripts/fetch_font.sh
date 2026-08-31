#!/usr/bin/bash

# Font is gitignored; download on first build and cache locally.
# Resolve paths relative to this script's own location so it works
# regardless of the caller's CWD (repo root or scripts/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FONT_DIR="$SCRIPT_DIR/../src/rev80/assets/fonts"
FONT_FILE="$FONT_DIR/CommitMonoNerdFont-Regular.otf"
FONT_URL="https://github.com/ryanoasis/nerd-fonts/releases/download/v3.4.0/CommitMono.zip"
if [[ ! -f "$FONT_FILE" ]]; then
    echo "[1/5] Downloading CommitMono Nerd Font..."
    mkdir -p "$FONT_DIR"
    TMP_ZIP=$(mktemp /tmp/CommitMono.XXXXXX.zip)
    curl -L --fail --progress-bar "$FONT_URL" -o "$TMP_ZIP"
    unzip -j "$TMP_ZIP" "CommitMonoNerdFont-Regular.otf" -d "$FONT_DIR/"
    rm "$TMP_ZIP"
    echo
else
    echo "[1/5] Font already present — skipping download."
    echo
fi
