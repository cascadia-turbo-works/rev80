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

from rev80._paths import project_path

log = logging.getLogger(__name__)


def _drivers_dir() -> Path | None:
    """Return the directory that contains the bundled PicoScope DLLs, or None.

    Delegates to _paths.project_path: sys._MEIPASS/drivers when frozen,
    <repo root>/drivers in development. NOT resource_path — that resolves
    inside the installed package, which is right for package-data but wrong
    here: drivers/ holds DLLs collected at the repo root by
    build/collect_pico_dlls.py and bundled by build/rev80.spec as a top-level
    directory.

    This module originally duplicated the logic and got the development branch
    wrong by one level, looking for src/drivers, which does not exist (audit
    X-06). Routing it through resource_path fixed that, and then narrowing
    resource_path to package-data reintroduced it by the same shape — hence
    the separate function, and the regression test in
    tests/test_util_small_defects.py.
    """
    candidate = project_path('drivers')
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
