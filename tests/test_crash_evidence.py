"""Every way the app can die must leave evidence in the log (audit H-07, S-01, S-02).

The reported symptom is "I return to find the app crashed but I have no
evidence". There are three distinct mechanisms, and each left a different
amount of nothing behind:

  * A background thread raises. `sys.excepthook` covers only the MAIN thread,
    so acquisition, simulation and writer thread deaths went to the default
    `threading.excepthook` -> stderr. Launched from a desktop entry, stderr
    goes nowhere. Nothing reaches log/.
  * The process is SIGKILLed by the OOM killer (S-02). No traceback, no atexit,
    no log line — the app simply vanishes.
  * A hard crash in the driver via ctypes (audit X-05). No Python traceback at
    all, because Python never regains control.

Nothing here can prevent those. What it can do is make sure the first is
logged, the second is *predictable* from a resource trail written before the
kill, and the third leaves a native traceback.
"""

import logging
import threading

import pytest

import rev80
from rev80 import logger as rev80_logger


def test_sys_excepthook_is_installed_by_setup():
    """Main-thread crashes already reached the log; keep it that way."""
    rev80_logger.install_excepthooks()
    import sys
    assert sys.excepthook is rev80_logger.exception_handler


def test_threading_excepthook_is_installed():
    """The gap: without this a dead worker thread leaves no trace at all."""
    rev80_logger.install_excepthooks()
    assert threading.excepthook is not threading.__excepthook__


def test_thread_exception_reaches_the_log(caplog):
    """A raising worker thread must produce a log record naming the thread."""
    rev80_logger.install_excepthooks()

    def boom():
        raise ValueError('worker exploded')

    with caplog.at_level(logging.ERROR):
        t = threading.Thread(target=boom, name='TestWorker')
        t.start()
        t.join()

    joined = '\n'.join(r.getMessage() for r in caplog.records)
    assert 'TestWorker' in joined
    assert any(r.exc_info for r in caplog.records), 'no traceback captured'


def test_thread_exception_log_names_the_exception(caplog):
    rev80_logger.install_excepthooks()

    def boom():
        raise KeyError('a-key')

    with caplog.at_level(logging.ERROR):
        t = threading.Thread(target=boom, name='KeyThread')
        t.start()
        t.join()

    text = '\n'.join(
        r.getMessage() + repr(r.exc_info[1] if r.exc_info else '')
        for r in caplog.records
    )
    assert 'KeyError' in text or 'a-key' in text


def test_installing_hooks_twice_is_safe():
    """setup_logging() may run more than once in a session (tests, --debug)."""
    rev80_logger.install_excepthooks()
    first = threading.excepthook
    rev80_logger.install_excepthooks()
    assert threading.excepthook is first


def test_faulthandler_is_enabled_with_a_file():
    """SIGSEGV is the one crash that leaves no Python traceback.

    A native traceback written to its own file is the only evidence that
    survives, and it is what distinguishes a driver-level crash (X-05) from
    an OOM kill, which leaves nothing at all.
    """
    import faulthandler
    rev80_logger.install_excepthooks()
    assert faulthandler.is_enabled()
    assert rev80_logger.fault_log_path().parent.is_dir()


# ---------------------------------------------------------------------------
# Resource trail — an OOM kill is SIGKILL, so the evidence must predate it
# ---------------------------------------------------------------------------

def test_resource_snapshot_reports_rss():
    snap = rev80_logger.resource_snapshot()
    assert snap['rss_mb'] > 0


def test_resource_snapshot_is_loggable_text():
    text = rev80_logger.format_resource_snapshot(rev80_logger.resource_snapshot())
    assert 'RSS' in text
    assert 'MB' in text


def test_resource_snapshot_never_raises(monkeypatch):
    """Diagnostics must not become a new crash source.

    This runs on Linux, Windows and a Raspberry Pi; if the platform will not
    give us memory numbers we log less, we do not take the app down.
    """
    monkeypatch.setattr(rev80_logger, '_rss_bytes', lambda: (_ for _ in ()).throw(OSError('nope')))
    snap = rev80_logger.resource_snapshot()
    assert snap['rss_mb'] == 0.0


# ---------------------------------------------------------------------------
# Version stamp — a log that cannot be tied to a build is not evidence
# ---------------------------------------------------------------------------

def test_version_is_reported():
    assert rev80.__version__


def test_version_matches_the_checkout_when_running_from_git():
    """The stamped _version.py goes stale whenever the git hook is not installed.

    It was 100 commits behind at one point, which makes a field report
    untraceable. In a source checkout the live `git describe` wins.
    """
    import subprocess
    try:
        described = subprocess.run(
            ['git', 'describe', '--tags', '--long', '--always'],
            capture_output=True, text=True, timeout=10,
            cwd=rev80_logger.repo_root_or_none() or '.',
        )
    except (OSError, subprocess.SubprocessError):
        pytest.skip('git not available')
    if described.returncode != 0:
        pytest.skip('not a git checkout')
    assert rev80.__version__ == described.stdout.strip()
