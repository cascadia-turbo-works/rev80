"""
_pico_loader.py  —  Ensure the bundled PicoScope DLLs are findable on Windows.

Call `ensure_pico_dlls_loadable()` once at startup (before importing picosdk).
In a frozen PyInstaller app the DLLs live in the `drivers/` sub-directory of
sys._MEIPASS.  In development they live in the project-root `drivers/` folder.

On Python 3.8+ the PATH trick alone is not sufficient on Windows because Python
ignores PATH for DLL resolution.  os.add_dll_directory() must be called instead.
"""

import os
import sys
from pathlib import Path


def _drivers_dir() -> Path | None:
    """Return the directory that contains the bundled PicoScope DLLs, or None."""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # PyInstaller frozen: DLLs are next to the extracted files
        candidate = Path(sys._MEIPASS) / 'drivers'  # type: ignore[attr-defined]
    else:
        # Development: project root / drivers/
        candidate = Path(__file__).parent.parent / 'drivers'
    return candidate if candidate.is_dir() else None


def ensure_pico_dlls_loadable() -> bool:
    """Add the DLL directory to the Windows DLL search path.

    Returns True if the directory was found and registered, False otherwise.
    Safe to call on Linux/macOS (no-op).
    """
    if os.name != 'nt':
        return True  # Not Windows — DLLs not needed

    drivers = _drivers_dir()
    if drivers is None:
        return False

    # Python 3.8+: DLL search is isolated from PATH; must use add_dll_directory
    if hasattr(os, 'add_dll_directory'):
        os.add_dll_directory(str(drivers))

    # Also add to PATH for older ctypes / LoadLibrary usage in picosdk
    env_path = os.environ.get('PATH', '')
    if str(drivers) not in env_path:
        os.environ['PATH'] = str(drivers) + os.pathsep + env_path

    return True
