"""vibechecker.config — OS-aware configuration directory and YAML persistence.

Config directory layout:
  Linux:   $XDG_CONFIG_HOME/vibechecker/   (default: ~/.config/vibechecker/)
  Windows: %APPDATA%/vibechecker/

  acquisition.yaml             — acquisition + monitor settings (per software instance)
  scope_sensors.yaml           — global IEPE sensor registry (all devices)
  devices/
    picoscope-defaults.yaml    — per-channel prototype applied to new devices
    picoscope-<model>-<SN>.yaml — per-device channels + siggen config
"""

import copy
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

import vibechecker

log = vibechecker.get_logger(__name__)

# ---------------------------------------------------------------------------
# Built-in defaults
# ---------------------------------------------------------------------------

DEFAULT_CACHE_FRAMES: int = 32

# Template for a single channel — used by picoscope-defaults.yaml and new-device init.
# channel_name / target_unit are null so the app falls back to "Ch A", sensor EU, etc.
_BUILTIN_CHANNEL_TEMPLATE: dict[str, Any] = {
    'enabled':        False,
    'sensor_id':      None,
    'voltage_range':  6,      # ±1 V
    'coupling':       'AC',
    'channel_name':   None,
    'target_unit':    None,
    'amplitude_mode': '0-P',
}

# Siggen template — stored in picoscope-defaults.yaml and written on every device save
# so the user always has editable siggen settings even when the generator is off.
_BUILTIN_SIGGEN: dict[str, Any] = {
    'wave_type':  'PS4000A_SINE',
    'freq_hz':    1000.0,
    'pktopk_uv':  1_000_000,
    'offset_uv':  0,
}

# Device file defaults (channels + siggen only).
_BUILTIN_DEVICE: dict[str, Any] = {
    'channels': {0: {**copy.deepcopy(_BUILTIN_CHANNEL_TEMPLATE), 'enabled': True}},
    'siggen':   None,
}

# acquisition.yaml defaults.
_BUILTIN_ACQ: dict[str, Any] = {
    'acquisition': {
        'maxfreq':          1000.0,
        'binsize':          1.0,
        'fft_window':       'hann',
        'welch_overlap':    0.5,
        'highpass_enabled': True,
        'highpass_fc':      10.0,
        'lowpass_enabled':  False,
        'lowpass_fc':       1000.0,
        'trend_max_points': 5000,
        'cache_frames':     15,
    },
    'monitor': {
        'interval_s':        600,
        'pre_burst_s':       30,
        'burst_duration_s':  120,
        'max_burst_s':       600,
        'output_dir':        None,
        'compression':       'gzip',
        'compression_level': 4,
        'anomaly': {
            'enabled':    True,
            'hook_type':  'rms',
            'warmup':     10,
            'rms_pct':    10.0,
            'rms_n':      3,
            'rms_alpha':  0.97,
            'spec_pct':   50.0,
            'spec_alpha': 0.995,
            'spec_n':     10,
            'spec_fmin':  None,   # null = no lower limit
            'spec_fmax':  None,   # null = no upper limit
        },
    },
}


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def config_dir() -> Path:
    """Return the OS-appropriate vibechecker config directory (not created yet)."""
    if sys.platform == 'win32':
        base = Path(os.environ.get('APPDATA') or Path.home() / 'AppData' / 'Roaming')
    else:
        base = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    return base / 'vibechecker'


def sanitize_serial(serial: str) -> str:
    """Replace filesystem-unsafe characters in a PicoScope serial number."""
    for ch in r'/:\\ ':
        serial = serial.replace(ch, '-')
    return serial


def device_filename(model_name: str, serial_number: str) -> str:
    """Produce e.g. 'picoscope-4424A-JY123.yaml' from model_name and serial_number."""
    model = (model_name
             .replace('PicoScope ', '')
             .replace('picoscope ', '')
             .replace(' ', '-'))
    serial = sanitize_serial(serial_number)
    return f"picoscope-{model}-{serial}.yaml"


def device_config_path(model_name: str, serial_number: str) -> Path:
    """Return the YAML path for a specific device."""
    return config_dir() / 'devices' / device_filename(model_name, serial_number)


def defaults_channel_path() -> Path:
    """Return the path to the per-channel prototype file."""
    return config_dir() / 'devices' / 'picoscope-defaults.yaml'


def acquisition_config_path() -> Path:
    """Return the path to the instance-wide acquisition + monitor config."""
    return config_dir() / 'acquisition.yaml'


# ---------------------------------------------------------------------------
# Atomic YAML write
# ---------------------------------------------------------------------------

def _atomic_yaml_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix='.yaml.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Ensure-on-first-run helpers
# ---------------------------------------------------------------------------

def ensure_defaults_config() -> None:
    """Write devices/picoscope-defaults.yaml with built-in templates if absent."""
    path = defaults_channel_path()
    if not path.exists():
        log.info('Creating channel defaults: %s', path)
        _atomic_yaml_write(path, {
            'channel': copy.deepcopy(_BUILTIN_CHANNEL_TEMPLATE),
            'siggen':  {**copy.deepcopy(_BUILTIN_SIGGEN), 'enabled': False},
        })


def ensure_acquisition_config() -> None:
    """Write acquisition.yaml with built-in defaults if absent."""
    path = acquisition_config_path()
    if not path.exists():
        log.info('Creating acquisition config: %s', path)
        _atomic_yaml_write(path, copy.deepcopy(_BUILTIN_ACQ))


def ensure_config_dir() -> None:
    """Seed all config files that don't already exist. Safe to call on every startup."""
    ensure_defaults_config()
    ensure_acquisition_config()


# ---------------------------------------------------------------------------
# Acquisition config (acquisition.yaml)
# ---------------------------------------------------------------------------

def load_acquisition_config() -> dict[str, Any]:
    """Load acquisition.yaml, filling missing keys from built-in defaults.

    Returns a dict with keys 'acquisition' and 'monitor'.
    """
    path = acquisition_config_path()
    data: dict[str, Any] = {}
    if path.exists():
        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            log.debug('Loaded acquisition config from %s', path)
        except Exception as exc:
            log.warning('Failed to read %s: %s — using built-in defaults', path, exc)
    return _merge_acquisition(data)


def save_acquisition_config(data: dict[str, Any]) -> None:
    """Atomically write acquisition + monitor settings to acquisition.yaml."""
    path = acquisition_config_path()
    _atomic_yaml_write(path, data)
    log.debug('Saved acquisition config to %s', path)


# ---------------------------------------------------------------------------
# Device config (devices/picoscope-<model>-<SN>.yaml)
# ---------------------------------------------------------------------------

def load_device_config(model_name: str, serial_number: str) -> dict[str, Any]:
    """Load channel + siggen config for the given device.

    Returns a dict with keys 'channels' (keyed by int channel index) and 'siggen'.
    Falls back to defaults if the file is absent or unreadable.
    """
    path = device_config_path(model_name, serial_number)
    if path.exists():
        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            log.debug('Loaded device config from %s', path)
            return _merge_device(data)
        except Exception as exc:
            log.warning('Failed to read %s: %s — using defaults', path, exc)
    log.debug('No device config for %r %r — using defaults', model_name, serial_number)
    return copy.deepcopy(_BUILTIN_DEVICE)


def save_device_config(model_name: str, serial_number: str, data: dict[str, Any]) -> None:
    """Atomically write channel + siggen config for the given device.

    Only 'channels' and 'siggen' keys are written; acquisition settings belong
    in acquisition.yaml. Siggen is always written as {enabled: bool, ...settings}
    so the user retains editable settings even when the generator is off.
    """
    path = device_config_path(model_name, serial_number)
    filtered: dict[str, Any] = {}
    if 'channels' in data:
        filtered['channels'] = data['channels']
    filtered['siggen'] = _siggen_for_yaml(data.get('siggen'))
    _atomic_yaml_write(path, filtered)
    log.debug('Saved device config to %s', path)


# ---------------------------------------------------------------------------
# Channel defaults / new-device initialisation
# ---------------------------------------------------------------------------

def load_defaults_channel() -> dict[str, Any]:
    """Load the single-channel template from picoscope-defaults.yaml."""
    path = defaults_channel_path()
    if path.exists():
        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            template = data.get('channel', {})
            merged = copy.deepcopy(_BUILTIN_CHANNEL_TEMPLATE)
            if isinstance(template, dict):
                merged.update(template)
            return merged
        except Exception as exc:
            log.warning('Failed to read %s: %s — using built-in template', path, exc)
    return copy.deepcopy(_BUILTIN_CHANNEL_TEMPLATE)


def new_device_channels(num_channels: int) -> dict[int, dict[str, Any]]:
    """Build a channels dict for a brand-new device using the defaults template.

    Channel 0 is enabled; all others default to disabled.
    """
    template = load_defaults_channel()
    channels = {ch: copy.deepcopy(template) for ch in range(num_channels)}
    channels[0]['enabled'] = True
    return channels


# ---------------------------------------------------------------------------
# Internal merge helpers
# ---------------------------------------------------------------------------

def _merge_acquisition(data: dict[str, Any]) -> dict[str, Any]:
    """Return data with missing acquisition/monitor keys filled from built-ins."""
    result = copy.deepcopy(_BUILTIN_ACQ)

    if 'acquisition' in data and isinstance(data['acquisition'], dict):
        acq = copy.deepcopy(_BUILTIN_ACQ['acquisition'])
        acq.update(data['acquisition'])
        result['acquisition'] = acq

    if 'monitor' in data and isinstance(data['monitor'], dict):
        mon = copy.deepcopy(_BUILTIN_ACQ['monitor'])
        mon_in = data['monitor']
        # Shallow merge top-level monitor keys, then deep-merge anomaly sub-dict.
        for k, v in mon_in.items():
            if k != 'anomaly':
                mon[k] = v
        if 'anomaly' in mon_in and isinstance(mon_in['anomaly'], dict):
            mon['anomaly'].update(mon_in['anomaly'])
        result['monitor'] = mon

    return result


def _merge_device(data: dict[str, Any]) -> dict[str, Any]:
    """Return device data with missing per-channel keys filled from built-in template.

    Siggen translation: YAML stores {enabled: bool, ...settings...}.
    In memory: None = disabled, dict-without-enabled = enabled.
    """
    result: dict[str, Any] = {'channels': {}, 'siggen': None}

    if 'channels' in data and isinstance(data['channels'], dict):
        for k, v in data['channels'].items():
            ch = int(k)
            merged = copy.deepcopy(_BUILTIN_CHANNEL_TEMPLATE)
            if isinstance(v, dict):
                merged.update(v)
            result['channels'][ch] = merged

    if 'siggen' in data:
        sg = data['siggen']
        if isinstance(sg, dict):
            enabled = sg.get('enabled', True)   # True default: old files have no flag
            result['siggen'] = None if not enabled else {
                k: v for k, v in sg.items() if k != 'enabled'
            }
        else:
            result['siggen'] = sg   # None from old format

    return result


def _siggen_for_yaml(siggen_config: dict | None) -> dict[str, Any]:
    """Convert in-memory siggen (None or settings-dict) to the YAML representation."""
    if siggen_config is None:
        return {**copy.deepcopy(_BUILTIN_SIGGEN), 'enabled': False}
    return {**siggen_config, 'enabled': True}
