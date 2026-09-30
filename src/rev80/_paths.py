"""
Runtime-safe path resolution for rev80.

Bundled resources (logging.yaml, assets/fonts/*.otf): relative to this
    package, or to sys._MEIPASS when frozen. They must ship as package data
    (pyproject.toml [tool.setuptools.package-data], build/rev80.spec `datas`).
User data (saved files, monitor sessions): always ~/Documents/Rev80/data.
    ./DEVDATA is test scratch space only; this module does not use it.
Logs: always ~/Documents/Rev80/logs, in every install. Never relative to
    the cwd: a desktop launcher runs with cwd $HOME and a systemd unit with
    cwd /, where mkdir('log') fails.
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

    Example: `drivers/`, the PicoSDK DLLs that build/collect_pico_dlls.py
    puts at the repo root and build/rev80.spec bundles at the top level of
    the frozen app. Do not use resource_path() for these: it looks in
    src/rev80/drivers, which does not exist, and the caller fails silently.
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
    """Return the directory used for log files.

    Always ~/Documents/Rev80/logs, like data_dir(). It must not depend on the
    current working directory (see the module docstring).
    """
    d = _user_dir() / 'logs'
    d.mkdir(parents=True, exist_ok=True)
    return d
