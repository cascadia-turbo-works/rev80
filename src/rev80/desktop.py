"""Linux desktop integration — .desktop launcher entry + icon under ~/.local/share/.

Not used on Windows: the frozen build gets a Start Menu shortcut from the
Inno Setup installer instead (see installer/rev80.iss). Driven by
`rev80 --install-desktop-entry` / `--uninstall-desktop-entry`.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import rev80
from rev80._paths import resource_path

log = rev80.get_logger("desktop")

_DESKTOP_FILE = Path.home() / '.local' / 'share' / 'applications' / 'rev80.desktop'
_ICON_THEME_DIR = Path.home() / '.local' / 'share' / 'icons' / 'hicolor'

_DESKTOP_ENTRY_TEMPLATE = """\
[Desktop Entry]
Type=Application
Name=Rev80
Comment=Industrial vibration analysis for PicoScope
Exec={exec_path}
Icon=rev80
Terminal=false
StartupWMClass=rev80
Categories=Science;Engineering;
"""


def _rev80_executable() -> Path:
    """Resolve the `rev80` console script for whatever environment is currently running.

    Checked next to the running interpreter first — this is where pip
    (--user, a venv, or a system install) places console scripts alongside
    python itself, so it correctly reflects the environment that was used
    to install rev80, not just whatever's first on PATH.
    """
    candidate = Path(sys.executable).parent / 'rev80'
    if candidate.exists():
        return candidate
    found = shutil.which('rev80')
    if found:
        return Path(found)
    raise FileNotFoundError(
        "Could not locate the 'rev80' console script. Is rev80 installed "
        "(pip install --user .) and its bin directory on PATH?"
    )


def _refresh_caches() -> None:
    """Best-effort cache refresh so the new entry/icon shows up without a re-login."""
    for cmd in (
        ['update-desktop-database', str(_DESKTOP_FILE.parent)],
        ['gtk-update-icon-cache', '-f', '-t', str(_ICON_THEME_DIR)],
    ):
        try:
            subprocess.run(cmd, check=False, capture_output=True)
        except FileNotFoundError:
            pass  # tool not installed — most desktop environments pick up the change anyway


def install() -> int:
    """Write a .desktop launcher entry and icon under ~/.local/share/. Returns exit code."""
    if sys.platform != 'linux':
        print("Desktop entry installation is only needed on Linux — Windows uses "
              "the Inno Setup installer instead.", file=sys.stderr)
        return 1

    try:
        exec_path = _rev80_executable()
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    # Raster PNGs, not the source SVG: Qt/KDE's SVG renderer doesn't render
    # this icon correctly (breaks in the launcher and taskbar), while a
    # plain hicolor PNG set at fixed sizes works everywhere.
    bundled_hicolor = resource_path('assets/icons/hicolor')
    icon_srcs = sorted(bundled_hicolor.rglob('rev80.png'))
    if not icon_srcs:
        print(f"ERROR: bundled icons not found under {bundled_hicolor} — reinstall rev80.",
              file=sys.stderr)
        return 1

    for src in icon_srcs:
        size_dir = src.parent.relative_to(bundled_hicolor)  # e.g. 48x48/apps
        dest = _ICON_THEME_DIR / size_dir / 'rev80.png'
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)

    _DESKTOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    _DESKTOP_FILE.write_text(_DESKTOP_ENTRY_TEMPLATE.format(exec_path=exec_path))
    _DESKTOP_FILE.chmod(0o755)

    _refresh_caches()

    print(f"Installed desktop entry: {_DESKTOP_FILE}")
    print(f"Installed icons:         {_ICON_THEME_DIR}/*/apps/rev80.png ({len(icon_srcs)} sizes)")
    print(f"Launcher runs:           {exec_path}")

    bin_dir = str(exec_path.parent)
    path_dirs = os.environ.get('PATH', '').split(os.pathsep)
    if bin_dir not in path_dirs:
        print(
            f"\nNote: {bin_dir} is not on your PATH. The desktop launcher will "
            f"still work, but running 'rev80' from a terminal won't until you add "
            f"it, e.g. in ~/.bashrc or ~/.profile:\n"
            f'  export PATH="{bin_dir}:$PATH"'
        )
    return 0


def uninstall() -> int:
    """Remove the .desktop entry and icon installed by install(). Returns exit code."""
    if sys.platform != 'linux':
        print("Desktop entry installation is only needed on Linux — Windows uses "
              "the Inno Setup installer instead.", file=sys.stderr)
        return 1

    removed = False
    paths = [_DESKTOP_FILE, *_ICON_THEME_DIR.glob('*/apps/rev80.png')]
    for path in paths:
        if path.exists():
            path.unlink()
            print(f"Removed {path}")
            removed = True
    if not removed:
        print("No desktop entry or icon found — nothing to do.")
    _refresh_caches()
    return 0
