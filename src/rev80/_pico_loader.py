"""
_pico_loader.py  —  Ensure the bundled PicoScope DLLs are findable on Windows.

Call `ensure_pico_dlls_loadable()` once at startup (before importing picosdk).
In a frozen PyInstaller app the DLLs live in the `drivers/` sub-directory of
sys._MEIPASS.  In development they live in the project-root `drivers/` folder.

On Python 3.8+ the PATH trick alone is not sufficient on Windows because Python
ignores PATH for DLL resolution.  os.add_dll_directory() must be called instead.
"""

import logging
import os
from pathlib import Path

from rev80._paths import resource_path

log = logging.getLogger(__name__)


def _drivers_dir() -> Path | None:
    """Return the directory that contains the bundled PicoScope DLLs, or None.

    Delegates to _paths.resource_path, which already resolves both cases
    correctly: sys._MEIPASS/drivers when frozen, <repo root>/drivers in
    development. This module previously duplicated that logic and got the
    development branch wrong by one level — Path(__file__).parent.parent
    resolves to src/, so it looked for src/drivers, which does not exist.
    The frozen branch was correct, so only development was affected: the
    function silently returned False, the bundled DLLs were never registered,
    and picosdk fell back to walking %PATH%.
    """
    candidate = resource_path('drivers')
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
        # Windows-only path, so this is a real problem worth surfacing rather
        # than a silent False: picosdk will fall back to walking %PATH% and
        # may load a different driver version, or none.
        log.warning('PicoScope drivers/ directory not found — bundled DLLs will '
                    'not be registered and picosdk will fall back to %PATH%.')
        return False

    # Python 3.8+: DLL search is isolated from PATH; must use add_dll_directory
    if hasattr(os, 'add_dll_directory'):
        os.add_dll_directory(str(drivers))

    # Also add to PATH for older ctypes / LoadLibrary usage in picosdk
    env_path = os.environ.get('PATH', '')
    if str(drivers) not in env_path:
        os.environ['PATH'] = str(drivers) + os.pathsep + env_path

    return True
