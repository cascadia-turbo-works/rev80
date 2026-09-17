#!/usr/bin/bash

# Put CommitMono Nerd Font where the package expects it.
#
# Two copies of this font exist in the tree, deliberately:
#   assets/fonts/          — tracked in git (2.2 MB), the source of truth
#   src/rev80/assets/fonts — gitignored; what package_data and rev80.spec
#                            actually bundle (see resource_path() in _paths.py)
#
# So the normal path is a local copy, not a download. The download is only a
# fallback for a tree where the tracked copy has been removed. That ordering
# matters for CI: it keeps the release build off the network, and Git Bash on
# GitHub's Windows runners has no guaranteed `unzip`. This script has no
# `set -e` and returns the status of its last command, so a failed download
# would otherwise pass silently and ship a font-less installer.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FONT_DIR="$SCRIPT_DIR/../src/rev80/assets/fonts"
FONT_FILE="$FONT_DIR/CommitMonoNerdFont-Regular.otf"
TRACKED_FONT="$SCRIPT_DIR/../assets/fonts/CommitMonoNerdFont-Regular.otf"
FONT_URL="https://github.com/ryanoasis/nerd-fonts/releases/download/v3.4.0/CommitMono.zip"

if [[ -f "$FONT_FILE" ]]; then
    echo "[1/5] Font already present — skipping."
    echo
    exit 0
fi

mkdir -p "$FONT_DIR"

if [[ -f "$TRACKED_FONT" ]]; then
    echo "[1/5] Copying font from tracked assets/fonts/..."
    cp "$TRACKED_FONT" "$FONT_FILE" || { echo "ERROR: font copy failed."; exit 1; }
    echo
    exit 0
fi

echo "[1/5] Tracked copy missing — downloading CommitMono Nerd Font..."
TMP_ZIP=$(mktemp /tmp/CommitMono.XXXXXX.zip)
curl -L --fail --progress-bar "$FONT_URL" -o "$TMP_ZIP" || {
    echo "ERROR: font download failed."; rm -f "$TMP_ZIP"; exit 1; }
unzip -j "$TMP_ZIP" "CommitMonoNerdFont-Regular.otf" -d "$FONT_DIR/" || {
    echo "ERROR: font extraction failed (is 'unzip' installed?)."; rm -f "$TMP_ZIP"; exit 1; }
rm -f "$TMP_ZIP"
echo
