"""log_dir() must not depend on the current working directory.

It used to return the relative Path('log') in every non-frozen install. A
desktop entry after `pip install --user .` then logged to ~/log/, and
`rev80-headless` under systemd with no WorkingDirectory= ran mkdir('/log') and
raised PermissionError before logging started. Every install now logs to the
user directory, as data_dir() already did.
"""

from pathlib import Path

import pytest

from rev80 import _paths, logger


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    elsewhere = tmp_path / 'cwd'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    return home


def test_log_dir_is_under_user_dir_when_not_frozen(fake_home, monkeypatch):
    monkeypatch.setattr(_paths, '_is_frozen', lambda: False)
    d = _paths.log_dir()
    assert d.is_absolute()
    assert d == fake_home / 'Documents' / 'Rev80' / 'logs'
    assert d.is_dir()


def test_log_dir_is_under_user_dir_when_frozen(fake_home, monkeypatch):
    monkeypatch.setattr(_paths, '_is_frozen', lambda: True)
    assert _paths.log_dir() == fake_home / 'Documents' / 'Rev80' / 'logs'


def test_log_dir_does_not_depend_on_cwd(fake_home, tmp_path, monkeypatch):
    monkeypatch.setattr(_paths, '_is_frozen', lambda: False)
    first = _paths.log_dir()
    other = tmp_path / 'other'
    other.mkdir()
    monkeypatch.chdir(other)
    assert _paths.log_dir() == first
    assert not (other / 'log').exists()


def test_fault_log_follows_log_dir(fake_home, monkeypatch):
    monkeypatch.setattr(_paths, '_is_frozen', lambda: False)
    assert logger.fault_log_path() == (
        fake_home / 'Documents' / 'Rev80' / 'logs' / 'faulthandler.log')
