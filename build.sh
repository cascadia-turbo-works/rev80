#!/usr/bin/env bash
# build.sh  —  Full Vibechecker Windows build pipeline (runs in Git Bash)
#
# Prerequisites:
#   - 64-bit Python 3.10+ in PATH
#   - pip install pyinstaller
#   - PicoSDK installed (for DLL collection step)
#   - Inno Setup 6.x installed
#
# Usage:
#   ./build.sh              # full build: DLLs + PyInstaller + Inno Setup
#   ./build.sh dlls         # DLL collection only
#   ./build.sh pyinstaller  # PyInstaller only (skip DLL collection)
#   ./build.sh installer    # Inno Setup only (requires dist/ to exist)

set -euo pipefail

STEP="${1:-all}"

# Locate iscc.exe — try PATH first, then common install locations.
# $LOCALAPPDATA is a Windows-style path in Git Bash; convert with cygpath.
find_iscc() {
    if command -v iscc &>/dev/null; then
        echo "iscc"
        return
    fi
    local localappdata_unix=""
    if [[ -n "${LOCALAPPDATA:-}" ]]; then
        localappdata_unix=$(cygpath "$LOCALAPPDATA" 2>/dev/null || echo "")
    fi
    local candidates=(
        "$localappdata_unix/Programs/Inno Setup 6/iscc.exe"
        "/c/Program Files (x86)/Inno Setup 6/iscc.exe"
        "/c/Program Files/Inno Setup 6/iscc.exe"
    )
    for c in "${candidates[@]}"; do
        if [[ -n "$c" && -f "$c" ]]; then
            echo "$c"
            return
        fi
    done
    echo ""
}

echo
echo "============================================================"
echo "  Vibechecker Windows Build Pipeline"
echo "============================================================"
echo

# ── Preflight checks ─────────────────────────────────────────────────────────
if [[ "$STEP" == "all" || "$STEP" == "installer" ]]; then
    ISCC="$(find_iscc)"
    if [[ -z "$ISCC" ]]; then
        echo "ERROR: iscc.exe not found. Install Inno Setup 6 from https://jrsoftware.org/isinfo.php"
        exit 1
    fi
    echo "Found Inno Setup: $ISCC"
    echo
fi

# ── Step 1: Collect PicoScope DLLs ──────────────────────────────────────────
if [[ "$STEP" == "all" || "$STEP" == "dlls" ]]; then
    echo "[1/3] Collecting PicoScope DLLs..."
    python build/collect_pico_dlls.py
    echo
fi

# ── Step 2: PyInstaller ──────────────────────────────────────────────────────
if [[ "$STEP" == "all" || "$STEP" == "pyinstaller" ]]; then
    echo "[2/3] Building executable with PyInstaller..."
    pyinstaller vibechecker.spec --noconfirm
    echo
fi

# ── Step 3: Inno Setup ───────────────────────────────────────────────────────
if [[ "$STEP" == "all" || "$STEP" == "installer" ]]; then
    echo "[3/3] Creating installer with Inno Setup..."
    "$ISCC" installer/vibechecker.iss
    echo
fi

echo "============================================================"
echo "  Build complete."
echo "  Installer: installer/Output/VibecheckerSetup-*.exe"
echo "============================================================"
