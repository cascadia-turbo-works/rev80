"""vibechecker.config — OS-aware configuration directory and per-device YAML persistence.

Config directory layout:
  Linux:   $XDG_CONFIG_HOME/vibechecker/   (default: ~/.config/vibechecker/)
  Windows: %APPDATA%/vibechecker/

  scope_sensors.yaml          — global IEPE sensor registry (all devices)
  devices/
    default.yaml              — template applied to unknown devices on first connect
    {sanitized_serial}.yaml   — per-device config (serial with /:\\ replaced by -)
"""

import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

import vibechecker

log = vibechecker.get_logger(__name__)

# ---------------------------------------------------------------------------
# Built-in defaults — used when no YAML exists at all
# ---------------------------------------------------------------------------

DEFAULT_CACHE_FRAMES: int = 32

_BUILTIN_DEFAULTS: dict[str, Any] = {
    'channels': {
        0: {'enabled': True,  'sensor_id': None, 'voltage_range': 7, 'coupling': 'AC'},
    },
    'siggen': None,
    'acquisition': {
        'maxfreq':          2000.0,
        'binsize':          2.0,
        'fft_window':       'hann',
        'welch_overlap':    0.5,
        'highpass_enabled': True,
        'highpass_fc':      10.0,
        'lowpass_enabled':  False,
        'lowpass_fc':       1000.0,
        'trend_max_points': 500,
        'cache_frames':     DEFAULT_CACHE_FRAMES,
    },
    'monitor': {
        'interval_s':       3600,
        'pre_buffer_s':     60,
        'burst_duration_s': 60,
        'max_burst_s':      600,
        'output_dir':       None,     # None → DEVDATA/monitor/
        'compression':      'gzip',
        'compression_level': 4,
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


def device_config_path(serial: str) -> Path:
    """Return the YAML path for a specific device serial number."""
    return config_dir() / 'devices' / f'{sanitize_serial(serial)}.yaml'


def default_config_path() -> Path:
    """Return the path to the default device template."""
    return config_dir() / 'devices' / 'default.yaml'


# ---------------------------------------------------------------------------
# Atomic YAML write (shared utility)
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
# Default config creation
# ---------------------------------------------------------------------------

def ensure_default_config() -> None:
    """Write devices/default.yaml with built-in defaults if it does not exist.
    """
    path = default_config_path()
    if not path.exists():
        log.info('Creating default device config: %s', path)
        _atomic_yaml_write(path, _BUILTIN_DEFAULTS)


# ---------------------------------------------------------------------------
# Load / save device config
# ---------------------------------------------------------------------------

def load_device_config(serial: str) -> dict[str, Any]:
    """Load config for *serial*, falling back to default.yaml, then built-ins.

    Returns a fully-populated dict with keys: 'channels', 'siggen', 'acquisition'.
    Missing keys are filled in from the built-in defaults so callers never need
    to handle absent keys.
    """
    for path in (device_config_path(serial), default_config_path()):
        if path.exists():
            try:
                with open(path) as f:
                    data = yaml.safe_load(f) or {}
                log.debug('Loaded device config from %s', path)
                return _merge_with_defaults(data)
            except Exception as exc:
                log.warning('Failed to read %s: %s', path, exc)
    log.debug('No device config found for %r — using built-in defaults', serial)
    return _deep_copy_defaults()


def save_device_config(serial: str, data: dict[str, Any]) -> None:
    """Atomically write the full device config for *serial*."""
    path = device_config_path(serial)
    _atomic_yaml_write(path, data)
    log.debug('Saved device config to %s', path)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _deep_copy_defaults() -> dict[str, Any]:
    import copy
    return copy.deepcopy(_BUILTIN_DEFAULTS)


def _merge_with_defaults(data: dict[str, Any]) -> dict[str, Any]:
    """Return *data* with any missing top-level and acquisition keys filled from built-ins."""
    import copy
    result = _deep_copy_defaults()

    # channels: merge by channel index, filling missing per-channel keys
    if 'channels' in data and isinstance(data['channels'], dict):
        for k, v in data['channels'].items():
            ch = int(k)
            if ch in result['channels'] and isinstance(v, dict):
                result['channels'][ch].update(v)
            elif isinstance(v, dict):
                result['channels'][ch] = v

    # siggen: take as-is (None or dict)
    if 'siggen' in data:
        result['siggen'] = data['siggen']

    # acquisition: fill missing keys from built-in defaults
    if 'acquisition' in data and isinstance(data['acquisition'], dict):
        acq = copy.deepcopy(_BUILTIN_DEFAULTS['acquisition'])
        acq.update(data['acquisition'])
        result['acquisition'] = acq

    # monitor: fill missing keys from built-in defaults
    if 'monitor' in data and isinstance(data['monitor'], dict):
        mon = copy.deepcopy(_BUILTIN_DEFAULTS['monitor'])
        mon.update(data['monitor'])
        result['monitor'] = mon

    return result
