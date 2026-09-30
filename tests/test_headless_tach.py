"""rev80-headless runs a tachometer channel.

Covers the shared role decision, --channels against the roles, the tach summary
lines, the channel roles in a monitor session, and the simulated tach source.
"""

import pytest

import rev80 as vc
from rev80 import tach
from rev80.config import channel_role_state
from rev80.headless import _apply_channel_config, _apply_overrides


class _Args:
    """The two `run()` arguments `_apply_overrides` reads."""

    def __init__(self, channels=None, maxfreq=None, binsize=None):
        self.channels = channels
        self.maxfreq = maxfreq
        self.binsize = binsize


def _device_cfg(**overrides):
    """A two-channel device file: 0 vibration, 3 tachometer."""
    cfg = {
        "channels": {
            0: {"enabled": True, "role": "vibration", "coupling": "AC",
                "voltage_range": 6, "channel_name": "Motor DE"},
            3: {"enabled": True, "role": "tachometer", "coupling": "DC",
                "voltage_range": 9, "channel_name": "Keyphasor",
                "tach": {"pulses_per_rev": 1, "polarity": "rising",
                         "threshold_mode": "adaptive", "min_amplitude_mv": 1500.0}},
        }
    }
    cfg["channels"][3].update(overrides)
    return cfg


def _config():
    c = vc.AcquisitionSettings()
    c.maxfreq, c.binsize = 1000.0, 1.0
    return c


# --- the shared loader ----------------------------------------------------

def test_role_state_is_shared_by_both_front_ends():
    """channel_role_state() decides what a `channels/{ch}` block means.

    Both front ends call it, so they cannot disagree on a default.
    """
    role, settings, enabled = channel_role_state(
        {"role": "tachometer", "enabled": False, "tach": {"pulses_per_rev": 6}})
    assert role == 'tachometer'
    assert settings.pulses_per_rev == 6
    assert enabled is True, 'claiming a channel as the tach enables it'

    role, settings, enabled = channel_role_state({"role": "vibration", "enabled": True})
    assert role == 'vibration'
    assert settings is None
    assert enabled is True


def test_an_unknown_role_falls_back_to_vibration_rather_than_raising():
    """An unknown role becomes 'vibration'; the loader does not raise."""
    role, settings, _ = channel_role_state({"role": "flowmeter", "enabled": True})
    assert role == 'vibration'
    assert settings is None


# --- headless accepts a tach channel --------------------------------------

def test_tach_channel_is_enabled_and_carries_its_calibration():
    config = _config()
    tach_settings = _apply_channel_config(config, _device_cfg())

    assert config.role_for(3) == 'tachometer'
    assert 3 in config.enabled_channels, 'refusing it is what R44 removed'
    assert config.tach_channels == [3]
    assert config.vibration_channels == [0]

    assert set(tach_settings) == {3}
    assert tach_settings[3].min_amplitude_mv == 1500.0, 'from the device file'


def test_a_tach_role_channel_with_no_calibration_block_says_so(caplog):
    """`tach: null` on a claimed channel gives the default TachSettings and a
    warning that names the missing calibration."""
    with caplog.at_level('WARNING'):
        settings = _apply_channel_config(_config(), _device_cfg(tach=None))
    assert settings[3] == tach.TachSettings(), 'usable defaults, not a refusal'
    assert any('calibration' in r.message for r in caplog.records)


def test_vibration_channels_are_untouched_by_the_tach_path():
    """With no tachometer role, the tach path changes nothing."""
    config = _config()
    cfg = {"channels": {0: {"enabled": True, "role": "vibration"},
                        1: {"enabled": False, "role": "vibration"}}}
    assert _apply_channel_config(config, cfg) == {}
    assert config.enabled_channels == [0]
    assert config.tach_channels == []


# --- --channels must reconcile against the roles --------------------------

def test_channels_override_that_drops_the_tach_says_so(caplog):
    """`--channels` that leaves out the tach channel logs a warning.

    Without the tach, every capture records rpm=NaN and the speed gate fails
    closed, so nothing is trended.
    """
    config = _config()
    _apply_channel_config(config, _device_cfg())
    with caplog.at_level('WARNING'):
        _apply_overrides(config, _Args(channels=['0', '1']))

    assert config.enabled_channels == [0, 1]
    assert config.tach_channels == [], 'the override is honoured, not overridden'
    assert any('tach' in r.message.lower() for r in caplog.records), (
        'dropping the speed reference must be stated')


def test_channels_override_keeping_the_tach_is_silent(caplog):
    config = _config()
    _apply_channel_config(config, _device_cfg())
    with caplog.at_level('WARNING'):
        _apply_overrides(config, _Args(channels=['0', '3']))

    assert config.enabled_channels == [0, 3]
    assert config.tach_channels == [3]
    assert not [r for r in caplog.records if 'tach' in r.message.lower()]


def test_channels_override_naming_an_unconfigured_channel_does_not_invent_a_tach():
    """`--channels 0,3` with no device file makes no tachometer channel."""
    config = _config()
    _apply_overrides(config, _Args(channels=['0', '3']))
    assert config.enabled_channels == [0, 3]
    assert config.tach_channels == []


# --- the ppr limits headless cannot show live -----------------------------

def test_the_speed_floor_is_reported_for_the_configured_ppr():
    """The summary gives the slowest measurable shaft speed.

    A 1 Hz bin is a 1 s block, so the floor is 180 RPM at 1 ppr.
    """
    from rev80.headless import _tach_summary_lines

    config = _config()
    settings = _apply_channel_config(config, _device_cfg())
    text = "\n".join(_tach_summary_lines(config, settings))
    assert 'ch3' in text
    assert 'adaptive' in text
    assert '180' in text, 'the slowest measurable shaft, from the block length'


def test_no_tach_channel_means_no_tach_summary():
    from rev80.headless import _tach_summary_lines
    assert _tach_summary_lines(_config(), {}) == []


@pytest.mark.parametrize('binsize, floor', [(0.5, 90.0), (1.0, 180.0), (10.0, 1800.0)])
def test_the_reported_floor_tracks_the_block_length(binsize, floor):
    from rev80.headless import _tach_summary_lines

    config = _config()
    config.binsize = binsize
    settings = _apply_channel_config(config, _device_cfg())
    assert f'{floor:,.0f}' in "\n".join(_tach_summary_lines(config, settings))


# --- what an unattended session actually writes ---------------------------
#
# tests/test_monitor_tach_storage.py covers the channel-group layout.
# These tests check that the channel snapshot records the role.

def _tach_session(tmp_path):
    """Record a short monitor session from a coherent vibration+tach pair."""
    import time
    from datetime import datetime, timezone

    import numpy as np

    from rev80 import simulation as sim
    from rev80.monitor import MonitorController, MonitorSession
    from rev80.monitor.session import channel_snapshot_for

    cfg = vc.AcquisitionSettings()
    cfg.maxfreq, cfg.binsize = 1000.0, 2.0
    cfg.enabled_channels = [0, 1]
    cfg.channel_roles = {1: 'tachometer'}
    dc = vc.DataCollector(config=cfg)
    dc.init_trend_channels()

    session = MonitorSession(
        session_id='tach-session', start_time=datetime.now(timezone.utc),
        interval_s=0.05, pre_buffer_frames=2, burst_duration_s=0.2,
        max_burst_s=1.0, session_dir=tmp_path / 'tach-session',
        acq_snapshot=cfg.to_dict(),
        channel_snapshot=channel_snapshot_for(cfg, dc),
        sensor_snapshot={},
    )
    ctrl = MonitorController()
    ctrl.start(session)
    for i in range(4):
        blocks = sim.GenerateMachineWithTach(
            sim._RawRateView(cfg), running_rate=30.0, seed=i)
        dc.receive_data({
            'data': np.column_stack([blocks[0], blocks[1]]),
            'channels': [0, 1], 'status': 'OKAY',
            'timestamp': datetime(2026, 9, 21), 'rel_time': float(i) * 0.5,
            'samplerate': cfg.raw_samplerate, 'overflow_mask': 0,
            'degraded': False,
        })
        ctrl.on_results(dc.process_samples(), dc.data['frame_cache'])
        time.sleep(0.06)
    ctrl.stop()
    for _ in range(50):
        if session.session_h5.exists():
            break
        time.sleep(0.05)
    return session.session_h5


def test_a_monitor_session_records_the_channel_roles(tmp_path):
    """The session metadata records the role of each channel."""
    import h5py

    with h5py.File(_tach_session(tmp_path), 'r') as f:
        ch = f['metadata/channels']
        assert ch['0'].attrs['role'] == 'vibration'
        assert ch['1'].attrs['role'] == 'tachometer'
        assert int(ch['1'].attrs['tach_pulses_per_rev']) == 1


def test_the_channel_snapshot_builder_is_shared():
    """channel_snapshot_for() records role and tach calibration per channel."""
    from rev80.monitor.session import channel_snapshot_for

    cfg = vc.AcquisitionSettings()
    cfg.enabled_channels = [0, 1]
    cfg.channel_roles = {1: 'tachometer'}
    dc = vc.DataCollector(config=cfg)
    dc.set_tach_settings(1, tach.TachSettings(pulses_per_rev=6))

    snap = channel_snapshot_for(cfg, dc)
    assert snap['0']['role'] == 'vibration'
    assert snap['1']['role'] == 'tachometer'
    assert snap['1']['tach_pulses_per_rev'] == 6
    assert 'tach_pulses_per_rev' not in snap['0']


def test_neither_front_end_reimplements_the_role_decision():
    """gui.py and headless.py both call channel_role_state().

    This reads the source, because `_restore_channel_assignments` cannot run
    without a dearpygui context.
    """
    import inspect

    from rev80 import gui, headless

    for mod in (gui, headless):
        src = inspect.getsource(mod)
        assert 'channel_role_state(' in src, (
            f'{mod.__name__} must call the shared decision, not its own copy')
        assert "info.get('role')" not in src and 'info.get("role")' not in src, (
            f'{mod.__name__} is reading the role itself again')


# --- --channels persistence, which is sticky across restarts --------------

def test_channels_override_is_written_back_to_the_device_config():
    """`--channels` edits `devices/*.yaml`, so the selection survives a restart."""
    from rev80.headless import _persist_channel_override

    cfg = {"channels": {0: {"enabled": False, "role": "vibration"},
                        1: {"enabled": True, "role": "vibration"}}}
    assert _persist_channel_override(cfg, ['0']) is True
    assert cfg["channels"][0]["enabled"] is True
    assert cfg["channels"][1]["enabled"] is False


def test_persisting_an_override_leaves_a_tach_channels_flag_alone():
    """`_persist_channel_override` does not write `enabled` for a tach channel.

    The role owns that flag. `_apply_overrides` excludes the tach for one run.
    """
    from rev80.headless import _persist_channel_override

    cfg = {"channels": {0: {"enabled": True, "role": "vibration"},
                        3: {"enabled": True, "role": "tachometer",
                            "tach": {"pulses_per_rev": 1}}}}
    _persist_channel_override(cfg, ['0'])
    assert cfg["channels"][3]["enabled"] is True, 'the role owns this flag'


def test_an_override_that_changes_nothing_does_not_rewrite_the_file():
    from rev80.headless import _persist_channel_override

    cfg = {"channels": {0: {"enabled": True, "role": "vibration"}}}
    assert _persist_channel_override(cfg, ['0']) is False


# --- the accuracy ceiling a non-unity ppr runs into -----------------------

def test_a_high_ppr_summary_states_the_sampling_ceiling():
    """At 6 ppr, the summary gives the full-accuracy speed limit.

    The limit is raw_samplerate * 60 / (MIN_SAMPLES_PER_PULSE * ppr) RPM.
    """
    from rev80.headless import _tach_summary_lines

    config = _config()
    settings = _apply_channel_config(
        config, _device_cfg(tach={"pulses_per_rev": 6}))
    text = "\n".join(_tach_summary_lines(config, settings))
    assert 'Full accuracy' in text
    assert f'{tach.MIN_SAMPLES_PER_PULSE}' in text

    expected = config.raw_samplerate * 60.0 / (tach.MIN_SAMPLES_PER_PULSE * 6)
    assert f'{expected:,.0f}' in text


def test_one_pulse_per_rev_does_not_mention_a_ceiling_it_never_reaches():
    """At 1 ppr, the summary does not give the full-accuracy limit."""
    from rev80.headless import _tach_summary_lines

    config = _config()
    settings = _apply_channel_config(config, _device_cfg())
    assert 'Full accuracy' not in "\n".join(_tach_summary_lines(config, settings))


# --- the simulated tach, without which none of this is testable offline ---

def test_a_simulated_tach_channel_gets_a_pulse_train_not_an_accelerometer():
    """A simulated tach channel gets GenerateTachPulse as its source."""
    from rev80.sensor import _simulate_tach_sources
    from rev80.simulation import GenerateTachPulse

    cfg = vc.AcquisitionSettings()
    cfg.enabled_channels = [0, 1]
    cfg.channel_roles = {1: 'tachometer'}

    class _Stream:
        channel_sources: dict = {}

    stream = _Stream()
    _simulate_tach_sources(stream, cfg)
    assert stream.channel_sources[1][0] is GenerateTachPulse
    assert 0 in stream.channel_sources, 'the vibration channel keeps its own source'


def test_the_simulated_tach_is_coherent_with_the_vibration_channel():
    """The simulated tach speed (RPM) is 60 x the vibration shaft rate (Hz)."""
    from rev80.sensor import _simulate_tach_sources

    cfg = vc.AcquisitionSettings()
    cfg.enabled_channels = [0, 1]
    cfg.channel_roles = {1: 'tachometer'}

    class _Stream:
        channel_sources: dict = {}

    stream = _Stream()
    _simulate_tach_sources(stream, cfg)
    vib_rate_hz = stream.channel_sources[0][2]
    tach_rate_rpm = stream.channel_sources[1][1]
    assert tach_rate_rpm == pytest.approx(vib_rate_hz * 60.0)


def test_no_tach_role_leaves_the_simulator_tiling_as_before():
    """With no tach role, channel_sources stays empty."""
    from rev80.sensor import _simulate_tach_sources

    cfg = vc.AcquisitionSettings()
    cfg.enabled_channels = [0, 1]

    class _Stream:
        channel_sources: dict = {}

    stream = _Stream()
    _simulate_tach_sources(stream, cfg)
    assert stream.channel_sources == {}
