"""Tests for vibechecker.config — OS-aware paths and per-device YAML persistence."""

import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

import vibechecker.config as cfg
from vibechecker.sample import AcquisitionSettings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _isolated_config(tmp_path, platform='linux', xdg=None, appdata=None):
    """Patch sys.platform and env vars to point config_dir at tmp_path."""
    env = {}
    if platform == 'win32':
        env['APPDATA'] = str(tmp_path)
    else:
        env['XDG_CONFIG_HOME'] = str(tmp_path) if xdg is None else xdg
        if appdata is not None:
            env['APPDATA'] = appdata
    return (
        patch.object(sys, 'platform', platform),
        patch.dict(os.environ, env, clear=False),
    )


# ---------------------------------------------------------------------------
# config_dir()
# ---------------------------------------------------------------------------

class TestConfigDir:
    def test_linux_uses_xdg(self, tmp_path):
        p1, p2 = _isolated_config(tmp_path, platform='linux')
        with p1, p2:
            result = cfg.config_dir()
        assert result == tmp_path / 'vibechecker'

    def test_windows_uses_appdata(self, tmp_path):
        p1, p2 = _isolated_config(tmp_path, platform='win32', appdata=str(tmp_path))
        with p1, p2:
            result = cfg.config_dir()
        assert result == tmp_path / 'vibechecker'

    def test_linux_fallback_when_no_xdg(self, monkeypatch):
        monkeypatch.setattr(sys, 'platform', 'linux')
        monkeypatch.delenv('XDG_CONFIG_HOME', raising=False)
        result = cfg.config_dir()
        assert result == Path.home() / '.config' / 'vibechecker'


# ---------------------------------------------------------------------------
# sanitize_serial()
# ---------------------------------------------------------------------------

class TestSanitizeSerial:
    def test_slash_replaced(self):
        assert '/' not in cfg.sanitize_serial('CMY12/345')

    def test_colon_replaced(self):
        assert ':' not in cfg.sanitize_serial('AB:12:34')

    def test_backslash_replaced(self):
        assert '\\' not in cfg.sanitize_serial('AB\\12')

    def test_space_replaced(self):
        assert ' ' not in cfg.sanitize_serial('AB 12')

    def test_safe_serial_unchanged(self):
        assert cfg.sanitize_serial('CMY12-345') == 'CMY12-345'

    def test_produces_valid_filename(self):
        name = cfg.sanitize_serial('CMY12/345:AB\\CD EF')
        assert Path(name).name == name   # no path separators


# ---------------------------------------------------------------------------
# device_config_path() / default_config_path()
# ---------------------------------------------------------------------------

class TestConfigPaths:
    def test_device_path_sanitizes_serial(self, tmp_path):
        with patch('vibechecker.config.config_dir', return_value=tmp_path / 'vibechecker'):
            path = cfg.device_config_path('CMY12/345')
        assert '/' not in path.stem
        assert path.parent.name == 'devices'
        assert path.suffix == '.yaml'

    def test_default_path_is_devices_default(self, tmp_path):
        with patch('vibechecker.config.config_dir', return_value=tmp_path / 'vibechecker'):
            path = cfg.default_config_path()
        assert path.name == 'default.yaml'
        assert path.parent.name == 'devices'


# ---------------------------------------------------------------------------
# ensure_default_config()
# ---------------------------------------------------------------------------

class TestEnsureDefaultConfig:
    def test_creates_default_yaml(self, tmp_path):
        with patch('vibechecker.config.config_dir', return_value=tmp_path / 'vc'):
            cfg.ensure_default_config()
            default = tmp_path / 'vc' / 'devices' / 'default.yaml'
            assert default.exists()
            data = yaml.safe_load(default.read_text())
            assert 'acquisition' in data
            assert 'channels' in data

    def test_idempotent(self, tmp_path):
        with patch('vibechecker.config.config_dir', return_value=tmp_path / 'vc'):
            cfg.ensure_default_config()
            cfg.ensure_default_config()   # second call should not raise
            assert (tmp_path / 'vc' / 'devices' / 'default.yaml').exists()

    def test_does_not_overwrite_existing(self, tmp_path):
        vc = tmp_path / 'vc'
        devices = vc / 'devices'
        devices.mkdir(parents=True)
        default = devices / 'default.yaml'
        default.write_text('custom: true\n')
        with patch('vibechecker.config.config_dir', return_value=vc):
            cfg.ensure_default_config()
        assert 'custom' in default.read_text()


# ---------------------------------------------------------------------------
# load_device_config() — fallback chain
# ---------------------------------------------------------------------------

class TestLoadDeviceConfig:
    def test_returns_full_schema(self, tmp_path):
        with patch('vibechecker.config.config_dir', return_value=tmp_path / 'vc'):
            data = cfg.load_device_config('ABC123')
        assert 'channels' in data
        assert 'siggen' in data
        assert 'acquisition' in data

    def test_builtin_defaults_when_no_files(self, tmp_path):
        with patch('vibechecker.config.config_dir', return_value=tmp_path / 'vc'):
            data = cfg.load_device_config('NOSUCHDEVICE')
        acq = data['acquisition']
        assert acq['maxfreq'] == cfg._BUILTIN_DEFAULTS['acquisition']['maxfreq']
        assert acq['fft_window'] == cfg._BUILTIN_DEFAULTS['acquisition']['fft_window']

    def test_loads_device_file_when_present(self, tmp_path):
        vc = tmp_path / 'vc'
        (vc / 'devices').mkdir(parents=True)
        device_data = {
            'acquisition': {'maxfreq': 5000.0, 'binsize': 1.0},
            'channels': {0: {'enabled': True, 'sensor_id': None,
                             'voltage_range': 7, 'coupling': 'AC'}},
            'siggen': None,
        }
        serial = 'TESTSERIAL'
        (vc / 'devices' / f'{serial}.yaml').write_text(
            yaml.dump(device_data))
        with patch('vibechecker.config.config_dir', return_value=vc):
            data = cfg.load_device_config(serial)
        assert data['acquisition']['maxfreq'] == 5000.0

    def test_falls_back_to_default_yaml(self, tmp_path):
        vc = tmp_path / 'vc'
        (vc / 'devices').mkdir(parents=True)
        default_data = {
            'acquisition': {'maxfreq': 8000.0, 'binsize': 2.0},
            'channels': {},
            'siggen': None,
        }
        (vc / 'devices' / 'default.yaml').write_text(yaml.dump(default_data))
        with patch('vibechecker.config.config_dir', return_value=vc):
            data = cfg.load_device_config('UNKNOWNSERIAL')
        assert data['acquisition']['maxfreq'] == 8000.0

    def test_missing_acquisition_keys_filled_from_builtin(self, tmp_path):
        vc = tmp_path / 'vc'
        (vc / 'devices').mkdir(parents=True)
        partial = {'acquisition': {'maxfreq': 3000.0}, 'channels': {}, 'siggen': None}
        (vc / 'devices' / 'PARTIAL.yaml').write_text(yaml.dump(partial))
        with patch('vibechecker.config.config_dir', return_value=vc):
            data = cfg.load_device_config('PARTIAL')
        # maxfreq overridden; fft_window comes from built-in
        assert data['acquisition']['maxfreq'] == 3000.0
        assert data['acquisition']['fft_window'] == cfg._BUILTIN_DEFAULTS['acquisition']['fft_window']


# ---------------------------------------------------------------------------
# save_device_config() — round-trip
# ---------------------------------------------------------------------------

class TestSaveDeviceConfig:
    def test_roundtrip(self, tmp_path):
        vc = tmp_path / 'vc'
        payload = {
            'channels': {0: {'enabled': True, 'sensor_id': None,
                             'voltage_range': 5, 'coupling': 'DC'}},
            'siggen': {'wave_type': 'PS4000A_SINE', 'freq_hz': 500.0,
                       'pktopk_uv': 1000000, 'offset_uv': 0},
            'acquisition': {'maxfreq': 4000.0, 'binsize': 0.5},
        }
        with patch('vibechecker.config.config_dir', return_value=vc):
            cfg.save_device_config('ROUNDTRIP', payload)
            data = cfg.load_device_config('ROUNDTRIP')
        assert data['channels'][0]['coupling'] == 'DC'
        assert data['siggen']['freq_hz'] == 500.0
        assert data['acquisition']['maxfreq'] == 4000.0

    def test_atomic_write_creates_parent_dirs(self, tmp_path):
        vc = tmp_path / 'vc'
        with patch('vibechecker.config.config_dir', return_value=vc):
            cfg.save_device_config('NEWDEV', {'channels': {}, 'siggen': None, 'acquisition': {}})
        assert (vc / 'devices' / 'NEWDEV.yaml').exists()




# ---------------------------------------------------------------------------
# AcquisitionSettings.from_dict() / .to_dict() round-trip
# ---------------------------------------------------------------------------

class TestAcquisitionSettingsSerialisation:
    def test_to_dict_contains_expected_keys(self):
        config = AcquisitionSettings()
        d = config.to_dict()
        for key in ('maxfreq', 'binsize', 'fft_window', 'welch_overlap',
                    'highpass_enabled', 'highpass_fc', 'lowpass_enabled', 'lowpass_fc',
                    'trend_max_points', 'trend_fmin', 'trend_fmax'):
            assert key in d, f'Missing key: {key}'

    def test_roundtrip_preserves_values(self):
        original = AcquisitionSettings()
        original.maxfreq = 5000.0
        original.binsize = 0.5
        original.fft_window = 'blackmanharris'
        original.welch_overlap = 0.75
        original.highpass_enabled = False
        original.highpass_fc = 20.0
        original.lowpass_enabled = True
        original.lowpass_fc = 2000.0
        original.trend_max_points = 200
        original.trend_fmin = 10.0
        original.trend_fmax = 1000.0

        restored = AcquisitionSettings.from_dict(original.to_dict())

        assert restored.maxfreq == 5000.0
        assert restored.binsize == 0.5
        assert restored.fft_window == 'blackmanharris'
        assert restored.welch_overlap == 0.75
        assert restored.highpass_enabled is False
        assert restored.highpass_fc == 20.0
        assert restored.lowpass_enabled is True
        assert restored.lowpass_fc == 2000.0
        assert restored.trend_max_points == 200
        assert restored.trend_fmin == 10.0
        assert restored.trend_fmax == 1000.0

    def test_from_dict_with_partial_dict_uses_defaults(self):
        restored = AcquisitionSettings.from_dict({'maxfreq': 8000.0})
        assert restored.maxfreq == 8000.0
        # All other fields should be the dataclass defaults
        assert isinstance(restored.fft_window, str)
        assert isinstance(restored.welch_overlap, float)

    def test_trend_fmax_none_roundtrip(self):
        config = AcquisitionSettings()
        config.trend_fmax = None
        restored = AcquisitionSettings.from_dict(config.to_dict())
        assert restored.trend_fmax is None
