"""Tests for rev80.config — path helpers and YAML persistence."""

import sys
import os
from pathlib import Path
from unittest.mock import patch

import yaml

import rev80.config as cfg
from rev80.sample import AcquisitionSettings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _isolated_config(tmp_path, platform='linux'):
    """Patch sys.platform and XDG_CONFIG_HOME / APPDATA to point at tmp_path."""
    env = {}
    if platform == 'win32':
        env['APPDATA'] = str(tmp_path)
    else:
        env['XDG_CONFIG_HOME'] = str(tmp_path)
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
        assert result == tmp_path / 'rev80'

    def test_windows_uses_appdata(self, tmp_path):
        p1, p2 = _isolated_config(tmp_path, platform='win32')
        with p1, p2:
            result = cfg.config_dir()
        assert result == tmp_path / 'rev80'

    def test_linux_fallback_when_no_xdg(self, monkeypatch):
        monkeypatch.setattr(sys, 'platform', 'linux')
        monkeypatch.delenv('XDG_CONFIG_HOME', raising=False)
        result = cfg.config_dir()
        assert result == Path.home() / '.config' / 'rev80'


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
        assert Path(name).name == name


# ---------------------------------------------------------------------------
# device_filename() / device_config_path()
# ---------------------------------------------------------------------------

class TestDeviceFilename:
    def test_strips_picoscope_prefix(self):
        name = cfg.device_filename('PicoScope 4424A', 'JY123')
        assert name == 'picoscope-4424A-JY123.yaml'

    def test_sanitizes_serial(self):
        name = cfg.device_filename('PicoScope 4224A', 'JY/12:34')
        assert '/' not in name
        assert ':' not in name

    def test_simulated_sensor(self):
        name = cfg.device_filename('Simulated Vibration Sensor', '0000')
        assert name.startswith('picoscope-')
        assert '0000' in name

    def test_device_config_path_in_devices_dir(self, tmp_path):
        with patch('rev80.config.config_dir', return_value=tmp_path / 'vc'):
            path = cfg.device_config_path('PicoScope 4424A', 'JY123')
        assert path.parent.name == 'devices'
        assert path.suffix == '.yaml'
        assert 'JY123' in path.name


# ---------------------------------------------------------------------------
# ensure_defaults_config() / ensure_acquisition_config()
# ---------------------------------------------------------------------------

class TestEnsureConfigs:
    def test_creates_defaults_yaml(self, tmp_path):
        with patch('rev80.config.config_dir', return_value=tmp_path / 'vc'):
            cfg.ensure_defaults_config()
            path = tmp_path / 'vc' / 'devices' / 'picoscope-defaults.yaml'
            assert path.exists()
            data = yaml.safe_load(path.read_text())
            assert 'channel' in data

    def test_creates_acquisition_yaml(self, tmp_path):
        with patch('rev80.config.config_dir', return_value=tmp_path / 'vc'):
            cfg.ensure_acquisition_config()
            path = tmp_path / 'vc' / 'acquisition.yaml'
            assert path.exists()
            data = yaml.safe_load(path.read_text())
            assert 'acquisition' in data
            assert 'monitor' in data

    def test_ensure_idempotent(self, tmp_path):
        with patch('rev80.config.config_dir', return_value=tmp_path / 'vc'):
            cfg.ensure_defaults_config()
            cfg.ensure_defaults_config()
            cfg.ensure_acquisition_config()
            cfg.ensure_acquisition_config()

    def test_does_not_overwrite_existing(self, tmp_path):
        vc = tmp_path / 'vc'
        (vc / 'devices').mkdir(parents=True)
        (vc / 'devices' / 'picoscope-defaults.yaml').write_text('custom: true\n')
        with patch('rev80.config.config_dir', return_value=vc):
            cfg.ensure_defaults_config()
        assert 'custom' in (vc / 'devices' / 'picoscope-defaults.yaml').read_text()


# ---------------------------------------------------------------------------
# load_acquisition_config() / save_acquisition_config()
# ---------------------------------------------------------------------------

class TestAcquisitionConfig:
    def test_returns_builtin_defaults_when_no_file(self, tmp_path):
        with patch('rev80.config.config_dir', return_value=tmp_path / 'vc'):
            data = cfg.load_acquisition_config()
        assert data['acquisition']['maxfreq'] == cfg._BUILTIN_ACQ['acquisition']['maxfreq']
        assert 'monitor' in data

    def test_merges_missing_acquisition_keys(self, tmp_path):
        vc = tmp_path / 'vc'
        vc.mkdir(parents=True)
        (vc / 'acquisition.yaml').write_text(
            yaml.dump({'acquisition': {'maxfreq': 5000.0}})
        )
        with patch('rev80.config.config_dir', return_value=vc):
            data = cfg.load_acquisition_config()
        assert data['acquisition']['maxfreq'] == 5000.0
        assert data['acquisition']['fft_window'] == cfg._BUILTIN_ACQ['acquisition']['fft_window']

    def test_merges_anomaly_subkeys(self, tmp_path):
        vc = tmp_path / 'vc'
        vc.mkdir(parents=True)
        (vc / 'acquisition.yaml').write_text(
            yaml.dump({'monitor': {'anomaly': {'enabled': True, 'rms_pct': 15.0}}})
        )
        with patch('rev80.config.config_dir', return_value=vc):
            data = cfg.load_acquisition_config()
        assert data['monitor']['anomaly']['enabled'] is True
        assert data['monitor']['anomaly']['rms_pct'] == 15.0
        assert data['monitor']['anomaly']['rms_s'] == cfg._BUILTIN_ACQ['monitor']['anomaly']['rms_s']

    def test_roundtrip(self, tmp_path):
        vc = tmp_path / 'vc'
        with patch('rev80.config.config_dir', return_value=vc):
            original = cfg.load_acquisition_config()
            original['acquisition']['maxfreq'] = 8000.0
            original['monitor']['interval_s'] = 300
            cfg.save_acquisition_config(original)
            reloaded = cfg.load_acquisition_config()
        assert reloaded['acquisition']['maxfreq'] == 8000.0
        assert reloaded['monitor']['interval_s'] == 300


# ---------------------------------------------------------------------------
# load_device_config() / save_device_config()
# ---------------------------------------------------------------------------

class TestDeviceConfig:
    def test_returns_defaults_when_no_file(self, tmp_path):
        with patch('rev80.config.config_dir', return_value=tmp_path / 'vc'):
            data = cfg.load_device_config('PicoScope 4424A', 'JY999')
        assert 'channels' in data
        assert 'siggen' in data
        assert 'acquisition' not in data   # acquisition belongs in acquisition.yaml

    def test_loads_existing_file(self, tmp_path):
        vc = tmp_path / 'vc'
        (vc / 'devices').mkdir(parents=True)
        device_data = {
            'channels': {0: {'enabled': True, 'sensor_id': None,
                             'voltage_range': 5, 'coupling': 'DC',
                             'channel_name': 'Motor', 'target_unit': '', 'amplitude_mode': ''}},
            'siggen': None,
        }
        fname = cfg.device_filename('PicoScope 4424A', 'JY123')
        (vc / 'devices' / fname).write_text(yaml.dump(device_data))
        with patch('rev80.config.config_dir', return_value=vc):
            data = cfg.load_device_config('PicoScope 4424A', 'JY123')
        assert data['channels'][0]['coupling'] == 'DC'
        assert data['channels'][0]['channel_name'] == 'Motor'

    def test_roundtrip(self, tmp_path):
        vc = tmp_path / 'vc'
        payload = {
            'channels': {0: {'enabled': True, 'sensor_id': None,
                             'voltage_range': 5, 'coupling': 'DC',
                             'channel_name': '', 'target_unit': '', 'amplitude_mode': ''}},
            'siggen': {'wave_type': 'PS4000A_SINE', 'freq_hz': 500.0,
                       'pktopk_uv': 1_000_000, 'offset_uv': 0},
        }
        with patch('rev80.config.config_dir', return_value=vc):
            cfg.save_device_config('PicoScope 4424A', 'JY123', payload)
            data = cfg.load_device_config('PicoScope 4424A', 'JY123')
        assert data['channels'][0]['coupling'] == 'DC'
        assert data['siggen']['freq_hz'] == 500.0

    def test_save_strips_acquisition_key(self, tmp_path):
        vc = tmp_path / 'vc'
        payload = {
            'channels': {0: {'enabled': True}},
            'siggen': None,
            'acquisition': {'maxfreq': 9999.0},  # should be ignored
        }
        with patch('rev80.config.config_dir', return_value=vc):
            cfg.save_device_config('PicoScope 4424A', 'JY123', payload)
            fname = cfg.device_filename('PicoScope 4424A', 'JY123')
            raw = yaml.safe_load((vc / 'devices' / fname).read_text())
        assert 'acquisition' not in raw

    def test_creates_parent_dirs(self, tmp_path):
        vc = tmp_path / 'vc'
        with patch('rev80.config.config_dir', return_value=vc):
            cfg.save_device_config('PicoScope 4424A', 'NEW1', {'channels': {}, 'siggen': None})
        assert (vc / 'devices').exists()

    def test_missing_channel_keys_filled_from_template(self, tmp_path):
        vc = tmp_path / 'vc'
        (vc / 'devices').mkdir(parents=True)
        partial = {'channels': {0: {'coupling': 'DC'}}, 'siggen': None}
        fname = cfg.device_filename('PicoScope 4424A', 'PARTIAL')
        (vc / 'devices' / fname).write_text(yaml.dump(partial))
        with patch('rev80.config.config_dir', return_value=vc):
            data = cfg.load_device_config('PicoScope 4424A', 'PARTIAL')
        assert data['channels'][0]['coupling'] == 'DC'
        assert data['channels'][0]['voltage_range'] == cfg._BUILTIN_CHANNEL_TEMPLATE['voltage_range']


# ---------------------------------------------------------------------------
# new_device_channels()
# ---------------------------------------------------------------------------

class TestNewDeviceChannels:
    def test_returns_n_channels(self, tmp_path):
        with patch('rev80.config.config_dir', return_value=tmp_path / 'vc'):
            channels = cfg.new_device_channels(4)
        assert set(channels.keys()) == {0, 1, 2, 3}

    def test_each_channel_is_independent_copy(self, tmp_path):
        with patch('rev80.config.config_dir', return_value=tmp_path / 'vc'):
            channels = cfg.new_device_channels(2)
        channels[0]['coupling'] = 'DC'
        assert channels[1]['coupling'] != 'DC'

    def test_applies_defaults_template(self, tmp_path):
        vc = tmp_path / 'vc'
        (vc / 'devices').mkdir(parents=True)
        (vc / 'devices' / 'picoscope-defaults.yaml').write_text(
            yaml.dump({'channel': {'coupling': 'DC', 'voltage_range': 3,
                                   'enabled': True, 'sensor_id': None,
                                   'channel_name': '', 'target_unit': '',
                                   'amplitude_mode': ''}})
        )
        with patch('rev80.config.config_dir', return_value=vc):
            channels = cfg.new_device_channels(2)
        assert channels[0]['coupling'] == 'DC'
        assert channels[1]['voltage_range'] == 3


# ---------------------------------------------------------------------------
# AcquisitionSettings round-trip
# ---------------------------------------------------------------------------

class TestAcquisitionSettingsSerialisation:
    def test_to_dict_contains_expected_keys(self):
        d = AcquisitionSettings().to_dict()
        for key in ('maxfreq', 'binsize', 'fft_window', 'welch_overlap',
                    'highpass_enabled', 'highpass_fc',
                    'trend_max_points'):
            assert key in d, f'Missing key: {key}'

    def test_roundtrip_preserves_values(self):
        original = AcquisitionSettings()
        original.maxfreq = 5000.0
        original.binsize = 0.5
        original.fft_window = 'blackmanharris'
        original.welch_overlap = 0.75
        original.highpass_enabled = False
        original.highpass_fc = 20.0
        original.trend_max_points = 200

        restored = AcquisitionSettings.from_dict(original.to_dict())

        assert restored.maxfreq == 5000.0
        assert restored.binsize == 0.5
        assert restored.fft_window == 'blackmanharris'
        assert restored.welch_overlap == 0.75
        assert restored.highpass_enabled is False
        assert restored.highpass_fc == 20.0
        assert restored.trend_max_points == 200

    def test_from_dict_with_partial_dict_uses_defaults(self):
        restored = AcquisitionSettings.from_dict({'maxfreq': 8000.0})
        assert restored.maxfreq == 8000.0
        assert isinstance(restored.fft_window, str)
        assert isinstance(restored.welch_overlap, float)
