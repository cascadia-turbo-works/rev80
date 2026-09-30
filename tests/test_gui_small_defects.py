"""Three small GUI defects, tested without a DPG context.

- The automatic envelope band stays in the anti-alias-protected band.
- The degraded-rate warning compares the measured raw rate with the
  nominal raw rate, not with the display rate.
- The monitor storage estimate uses decimal units and does not count a
  tachometer channel as a waveform.
"""

import numpy as np
import pytest

import rev80.gui as gui_module
from rev80.gui import (
    GUI,
    degraded_rate_text,
    envelope_search_fmax,
    monitor_storage_estimate,
)
from rev80.sample import AcquisitionSettings
from rev80.util import UI_Elements as ui

RAW_FS = 25600.0


# ---------------------------------------------------------------------------
# Envelope band search
# ---------------------------------------------------------------------------

def test_envelope_search_fmax_is_the_protected_band_top():
    assert envelope_search_fmax(RAW_FS) == pytest.approx(10000.0)


class _BandDpg:
    """ENV_BAND_LO and ENV_BAND_HI are 0: the GUI selects the band."""

    @staticmethod
    def get_value(tag):
        return 0.0


def test_auto_band_is_at_or_below_the_protected_band(monkeypatch):
    """Put the most energy in the guard band, above 10 kHz."""
    monkeypatch.setattr(gui_module, 'dpg', _BandDpg)
    app = GUI.__new__(GUI)
    app._env_auto_band = {}
    rng = np.random.default_rng(1)
    n = int(RAW_FS)
    t = np.arange(n) / RAW_FS
    signal = 0.01 * rng.standard_normal(n) + np.sin(2 * np.pi * 11500.0 * t)
    lo, hi = app._env_band_for(signal, RAW_FS, ch=0)
    assert lo < hi <= RAW_FS / 2.56


# ---------------------------------------------------------------------------
# Degraded-rate warning
# ---------------------------------------------------------------------------

def test_degraded_text_uses_the_raw_rate():
    cfg = AcquisitionSettings()
    cfg.maxfreq = 2000.0          # display rate 5120 Hz
    text = degraded_rate_text(25000.0, cfg)
    assert f"{cfg.raw_samplerate:.0f}" in text
    assert f"{cfg.samplerate:.0f}" not in text
    assert "25000" in text


def test_degraded_text_without_a_measured_rate():
    assert degraded_rate_text(None, AcquisitionSettings()) == "⚠ rate degraded"


# ---------------------------------------------------------------------------
# Monitor storage estimate
# ---------------------------------------------------------------------------

def _cfg_with(vibration: int, tach: int = 0) -> AcquisitionSettings:
    cfg = AcquisitionSettings()
    n = vibration + tach
    cfg.enabled_channels = list(range(n))
    cfg.channel_roles = {ch: 'tachometer' for ch in range(vibration, n)}
    return cfg


def test_estimate_uses_decimal_units():
    text, _ = monitor_storage_estimate(_cfg_with(4), interval_s=5, burst_s=120, pre_s=30)
    assert 'GiB' not in text and 'MiB' not in text and 'KiB' not in text
    assert 'GB/year' in text or 'MB/year' in text


def test_estimate_values_are_decimal():
    cfg = _cfg_with(1)
    block_bytes = cfg.raw_blocksize * 8 * 0.5
    text, per_year = monitor_storage_estimate(cfg, interval_s=3600, burst_s=10, pre_s=0)
    assert per_year == pytest.approx(365 * 24 * block_bytes)
    assert f"~{per_year / 1e6:.0f} MB/year" in text


def test_estimate_does_not_count_a_tach_channel_as_a_waveform():
    _, vib_only = monitor_storage_estimate(_cfg_with(2), 600, 120, 30)
    _, with_tach = monitor_storage_estimate(_cfg_with(2, tach=1), 600, 120, 30)
    assert with_tach == vib_only


def test_estimate_updates_the_widget(monkeypatch):
    """_on_monitor_config_change writes the text of monitor_storage_estimate."""
    store = {
        ui.MON_DLG_ESTIMATE: '',
        ui.MON_DLG_INTERVAL: '1 h',
        ui.MON_DLG_BURST_DUR: 120.0,
        ui.MON_DLG_PRE_BUFFER: 30.0,
    }

    class _Dpg:
        @staticmethod
        def does_item_exist(tag):
            return tag in store

        @staticmethod
        def get_value(tag):
            return store[tag]

        @staticmethod
        def set_value(tag, value):
            store[tag] = value

        @staticmethod
        def configure_item(tag, **kw):
            pass

    class _Collector:
        config = _cfg_with(2, tach=1)

    monkeypatch.setattr(gui_module, 'dpg', _Dpg)
    app = GUI.__new__(GUI)
    app.collector = _Collector()
    app._on_monitor_config_change()
    expected, _ = monitor_storage_estimate(_Collector.config, 3600, 120.0, 30.0)
    assert store[ui.MON_DLG_ESTIMATE].endswith(expected)
