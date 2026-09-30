# Event Logging

import faulthandler
import os
import platform
import subprocess
import sys
import threading
from pathlib import Path

import logging.config
import yaml

from rev80._paths import log_dir


def setup_logging(debug: bool = False) -> None:
    """Load logging configuration and direct file handlers to the correct log dir."""
    config_file = Path(__file__).parent / 'logging.yaml'
    if not config_file.exists():
        raise FileNotFoundError(f"Logging config not found: {config_file}")
    with open(config_file, "r") as f:
        config = yaml.safe_load(f)

    # rename main logger to match package name
    if isinstance(__package__, str):
        config['loggers'][__package__] = config['loggers']['main']
        del config['loggers']['main']

    # Redirect file handlers to the runtime-safe log directory
    _log_dir = log_dir()
    for handler in config.get("handlers", {}).values():
        fname = handler.get("filename")
        if fname:
            # Keep only the basename of the YAML filename (e.g. "log/main.log")
            # and put it in log_dir(), ~/Documents/Rev80/logs/
            handler["filename"] = str(_log_dir / os.path.basename(fname))

    if debug:
        config['handlers']['console']['level'] = logging.DEBUG

    # setup config
    logging.config.dictConfig(config)

def get_logger(name:str=''):
    """Return a sublogger under the __package__ namespace."""
    
    tag = [] 
    if isinstance(__package__, str):
        tag.append(__package__)
    else:
        tag.append('main')

    if name:
        tag.append(name)

    logname = '.'.join(tag)
    
    return logging.getLogger(logname)

baselog = get_logger()


def exception_handler(exc_type, exc, tb):
    """Capture any unhandled MAIN-THREAD exception to the log."""
    baselog.error("Unhandled exception in main thread:", exc_info=(exc_type, exc, tb))


def thread_exception_handler(args) -> None:
    """Log an unhandled exception from a background thread.

    The acquisition, simulation, writer and worker threads run off the main
    thread. The default hook writes to stderr, which a desktop launcher
    discards; a dead acquisition thread can leave is_streaming True.
    """
    if args.exc_type is SystemExit:
        return
    name = args.thread.name if args.thread is not None else 'unknown'
    baselog.error(
        "Unhandled exception in thread %r — that thread is now dead; anything "
        "waiting on it will hang rather than fail", name,
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def fault_log_path() -> Path:
    """File that receives a native traceback if the interpreter hard-crashes."""
    return log_dir() / 'faulthandler.log'


_hooks_installed = False
_fault_file = None


def install_excepthooks() -> None:
    """Send every crash that can be caught to the log directory. Idempotent.

    sys.excepthook (main thread), threading.excepthook (other threads), and
    faulthandler to faulthandler.log (SIGSEGV, for example in the driver). An
    OOM kill is SIGKILL and cannot be caught; resource_snapshot() is the only
    trail for it.
    """
    global _hooks_installed, _fault_file
    if _hooks_installed:
        return
    sys.excepthook = exception_handler
    threading.excepthook = thread_exception_handler
    try:
        path = fault_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _fault_file = open(path, 'a', buffering=1)          # noqa: SIM115 — lives for the process
        faulthandler.enable(file=_fault_file, all_threads=True)
    except OSError as exc:
        baselog.warning('Could not enable faulthandler: %s', exc)
    _hooks_installed = True


# ---------------------------------------------------------------------------
# Resource trail
# ---------------------------------------------------------------------------

def _rss_bytes() -> int:
    """Resident set size, in bytes. Linux/proc first, then a portable fallback."""
    try:
        with open('/proc/self/statm') as fh:
            return int(fh.read().split()[1]) * os.sysconf('SC_PAGE_SIZE')
    except (OSError, IndexError, ValueError):
        pass
    import resource
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports kB, macOS bytes.
    return ru * 1024 if sys.platform.startswith('linux') else ru


def resource_snapshot() -> dict:
    """Memory and thread counts for the periodic monitor-mode trail.

    An OOM kill leaves nothing in the log, so only a trail written before it
    shows the cause. This function never raises.
    """
    try:
        rss_mb = _rss_bytes() / (1024 * 1024)
    except Exception:                                        # noqa: BLE001
        rss_mb = 0.0
    try:
        n_threads = threading.active_count()
    except Exception:                                        # noqa: BLE001
        n_threads = 0
    return {'rss_mb': round(rss_mb, 1), 'threads': n_threads}


def format_resource_snapshot(snap: dict, **extra) -> str:
    parts = [f"RSS {snap.get('rss_mb', 0.0):.1f} MB",
             f"threads {snap.get('threads', 0)}"]
    parts += [f'{k} {v}' for k, v in extra.items()]
    return ' | '.join(parts)


# ---------------------------------------------------------------------------
# Build identity
# ---------------------------------------------------------------------------

def repo_root_or_none() -> Path | None:
    """The repo root when running from a source checkout, else None."""
    root = Path(__file__).resolve().parent.parent.parent
    return root if (root / '.git').exists() else None


def resolve_version(stamped: str) -> str:
    """Live `git describe` in a source checkout, else the stamped value.

    setuptools_scm writes _version.py at build or install time, so in an
    editable checkout it does not follow later commits. In a checkout, git is
    the source; in an installed or frozen build there is no git, and the
    stamped value is used.
    """
    root = repo_root_or_none()
    if root is None:
        return stamped
    try:
        out = subprocess.run(
            ['git', 'describe', '--tags', '--long', '--always'],
            capture_output=True, text=True, timeout=5, cwd=root,
        )
    except (OSError, subprocess.SubprocessError):
        return stamped
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else stamped

def log_system_info():
    '''
    Log platform specific info to log.
    '''

    sysinfo = f'''.
    ======== SYSTEM INFORMATION =======
    || OS:               {platform.system()} {platform.release()}
    || Machine:          {platform.machine()}
    || Processor:        {platform.processor()}
    || Python version:   {platform.python_version()}
    || Executable path:  {sys.executable}
    ===================================
    '''

    baselog.debug(sysinfo)
