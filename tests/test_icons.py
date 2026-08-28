"""Tests for the icon font registry.

`assets/fonts/` is gitignored and populated by scripts/build.sh, so a fresh
clone — and every CI runner — has no font file. icons.load() previously passed
the nonexistent path straight to dpg.font(), which raised inside the context
manager and surfaced as an opaque SystemError that took down GUI construction
entirely (test_gui_build failed on any machine that had not run build.sh).
"""

import dearpygui.dearpygui as dpg
import pytest

import rev80.icons as icons


@pytest.fixture(autouse=True)
def _dpg_context():
    """Each test gets a fresh DPG context and a cleared font cache."""
    icons.reset()
    dpg.create_context()
    yield
    dpg.destroy_context()
    icons.reset()


def test_load_returns_none_when_font_missing(monkeypatch, tmp_path):
    """A missing font degrades to the default font instead of raising."""
    monkeypatch.setattr(icons, 'resource_path', lambda rel: tmp_path / rel)
    assert icons.load() is None


def test_load_missing_font_logs_warning(monkeypatch, tmp_path, caplog):
    """The fallback is not silent — it says what is missing and how to fix it."""
    monkeypatch.setattr(icons, 'resource_path', lambda rel: tmp_path / rel)
    with caplog.at_level('WARNING'):
        icons.load()
    assert any('Icon font not found' in r.message for r in caplog.records)


def test_load_returns_tag_when_font_present():
    """When the font is actually installed, load() registers and returns a tag."""
    font = icons.resource_path('assets/fonts/CommitMonoNerdFont-Regular.otf')
    if not font.is_file():
        pytest.skip('icon font not installed (run scripts/build.sh)')
    tag = icons.load()
    assert tag is not None
    assert icons.font_tag() == tag


def test_load_is_idempotent(monkeypatch, tmp_path):
    """Repeated calls with a missing font keep returning None, never raise."""
    monkeypatch.setattr(icons, 'resource_path', lambda rel: tmp_path / rel)
    assert icons.load() is None
    assert icons.load() is None


def test_font_tag_raises_before_successful_load(monkeypatch, tmp_path):
    """font_tag() is only valid after a load() that found the file."""
    monkeypatch.setattr(icons, 'resource_path', lambda rel: tmp_path / rel)
    icons.load()
    with pytest.raises(RuntimeError):
        icons.font_tag()
