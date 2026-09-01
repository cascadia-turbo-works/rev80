"""
Runtime-safe path resolution for rev80.

Bundled resources (e.g. logging.yaml, assets/fonts/*.otf): resolved relative
    to this package's own directory — correct whether the package is an
    editable checkout, a normal (non-editable) pip install, or bundled into
    sys._MEIPASS when frozen (PyInstaller). Anything resolved this way must
    ship as package data (see pyproject.toml's [tool.setuptools.package-data]
    and build/rev80.spec's `datas`).
User-writable data (saved snapshots, monitor sessions): always
    ~/Documents/Rev80/data, whether running from source or frozen. The
    project-relative ./DEVDATA directory is test scratch space only (see
    tests/), not touched by this module.
Logs: project-relative ./log in development, ~/Documents/Rev80/logs when
    frozen.
"""

import sys
from pathlib import Path


def _is_frozen() -> bool:
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def resource_path(relative: str) -> Path:
    """Return the absolute path to a bundled resource file (e.g. logging.yaml).

    In a frozen app the file lives under sys._MEIPASS. Otherwise it's
    resolved relative to this package's own install location — this is
    package-data, so it must physically live under src/rev80/ to be found
    both in an editable checkout and in a normal (non-editable) pip install.
    """
    if _is_frozen():
        return Path(sys._MEIPASS) / relative  # type: ignore[attr-defined]
    return Path(__file__).parent / relative


def project_path(relative: str) -> Path:
    """Absolute path to a repo-root build artifact that is NOT package data.

    Distinct from resource_path(): that resolves inside the installed package,
    which is correct for files shipped as package-data (logging.yaml, the icon
    font) and therefore present in a non-editable pip install. Some things are
    neither — `drivers/` holds PicoSDK DLLs collected at the repo root by
    build/collect_pico_dlls.py and bundled by build/rev80.spec as a top-level
    `drivers/` directory in the frozen app. Resolving those through
    resource_path() looks for src/rev80/drivers, which never exists, and the
    caller silently degrades (audit X-06).
    """
    if _is_frozen():
        return Path(sys._MEIPASS) / relative  # type: ignore[attr-defined]
    return Path(__file__).parent.parent.parent / relative


def _user_dir() -> Path:
    """Return ~/Documents/Rev80, creating it if necessary."""
    base = Path.home() / 'Documents' / 'Rev80'
    base.mkdir(parents=True, exist_ok=True)
    return base


def data_dir() -> Path:
    """Return the directory used for saved .h5 data files (snapshots, monitor sessions).

    Always ~/Documents/Rev80/data, in development and frozen builds alike.
    """
    d = _user_dir() / 'data'
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
