"""
Runtime-safe path resolution for vibechecker.

In development:  uses project-relative paths (current working directory).
Frozen (PyInstaller):  uses sys._MEIPASS for bundled resources and
    ~/Documents/vibechecker/ for user-writable data and logs.
"""

import sys
from pathlib import Path


def _is_frozen() -> bool:
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def resource_path(relative: str) -> Path:
    """Return the absolute path to a bundled resource file (e.g. logging.yaml).

    In a frozen app the file lives under sys._MEIPASS.
    In development it lives next to this file's package root.
    """
    if _is_frozen():
        return Path(sys._MEIPASS) / relative  # type: ignore[attr-defined]
    return Path(__file__).parent / relative


def _user_dir() -> Path:
    """Return ~/Documents/vibechecker, creating it if necessary."""
    base = Path.home() / 'Documents' / 'vibechecker'
    base.mkdir(parents=True, exist_ok=True)
    return base


def data_dir() -> Path:
    """Return the directory used for saved .h5 data files."""
    if _is_frozen():
        d = _user_dir() / 'data'
    else:
        d = Path('DEVDATA')
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_dir() -> Path:
    """Return the directory used for log files."""
    if _is_frozen():
        d = _user_dir() / 'logs'
    else:
        d = Path('log')
    d.mkdir(parents=True, exist_ok=True)
    return d
