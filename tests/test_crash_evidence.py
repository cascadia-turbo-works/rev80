"""Every way the app can die leaves evidence in the log.

A worker-thread exception reaches the log through threading.excepthook. A
resource trail predates an OOM kill (SIGKILL). faulthandler writes a native
traceback for a driver-level crash (SIGSEGV).
"""

import logging
import threading

import pytest

import rev80
from rev80 import logger as rev80_logger


def test_sys_excepthook_is_installed_by_setup():
    """install_excepthooks() routes main-thread crashes to the log."""
    rev80_logger.install_excepthooks()
    import sys
    assert sys.excepthook is rev80_logger.exception_handler


def test_threading_excepthook_is_installed():
    """install_excepthooks() replaces the default threading.excepthook."""
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
    """faulthandler is enabled and its log directory exists.

    A SIGSEGV leaves no Python traceback. The native traceback file tells a
    driver-level crash from an OOM kill, which leaves nothing.
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
    """resource_snapshot() returns 0.0 MB when the platform gives no RSS.

    It does not raise, so a diagnostic cannot crash the app.
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
    """In a source checkout, __version__ is the live `git describe` output.

    setuptools_scm writes _version.py at install time, so it does not follow
    later commits in an editable checkout.
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
