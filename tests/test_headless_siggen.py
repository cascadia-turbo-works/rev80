"""Headless starts the signal generator from the device file, as the GUI does.

Without it, an AWG loopback (a test tachometer, a sensor check-out) works in
the GUI and is silent in headless.
"""
import re
from pathlib import Path

from rev80 import config as _cfg
from rev80.headless import _siggen_summary_line

HEADLESS_SRC = Path(__file__).parent.parent / 'src' / 'rev80' / 'headless.py'

SQUARE_30HZ = {
    'wave_type': 'PS4000A_SQUARE',
    'freq_hz':   30.0,
    'pktopk_uv': 2_000_000,
    'offset_uv': 0,
}


def test_headless_passes_the_siggen_config_to_the_stream():
    src = HEADLESS_SRC.read_text(encoding='utf-8')
    assert "collector.siggen_config = device_cfg.get('siggen')" in src
    assert re.search(
        r"collector\.connect_sensor\(sensor,\s*siggen_config=collector\.siggen_config\)",
        src)


def test_an_enabled_siggen_block_reaches_headless_as_a_config(tmp_path, monkeypatch):
    monkeypatch.setattr(_cfg, 'device_config_path',
                        lambda model, sn: tmp_path / f'{model}-{sn}.yaml')
    _cfg.save_device_config('4824A', 'X1', {'channels': {}, 'siggen': SQUARE_30HZ})
    assert _cfg.load_device_config('4824A', 'X1')['siggen'] == SQUARE_30HZ


def test_a_disabled_siggen_block_gives_none(tmp_path, monkeypatch):
    monkeypatch.setattr(_cfg, 'device_config_path',
                        lambda model, sn: tmp_path / f'{model}-{sn}.yaml')
    _cfg.save_device_config('4824A', 'X1', {'channels': {}, 'siggen': None})
    assert _cfg.load_device_config('4824A', 'X1')['siggen'] is None


def test_the_summary_states_the_generator_settings():
    line = _siggen_summary_line(SQUARE_30HZ)
    assert 'Square' in line
    assert '30 Hz' in line
    assert '2000 mV pk-pk' in line


def test_the_summary_says_nothing_when_the_generator_is_off():
    assert _siggen_summary_line(None) is None
