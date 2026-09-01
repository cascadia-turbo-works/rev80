"""HDF5 persistence for tachometer channels (measurement file v5).

Decision D-2: a tach channel stores its **edge times**, not its waveform.
~30 float64 per second against 41666 is a factor of ~1400, which matters most
on exactly the long unattended sessions where the tach channel would otherwise
dominate the file. What is given up is re-thresholding after capture; what is
kept is everything that makes RPM a *view* on stored data -- pulses_per_rev is
a post-hoc divisor on the intervals, and a shaft-angle vector, if ever wanted,
is an interpolation of those same edge times.
"""

import h5py
from datetime import datetime

import numpy as np
import pytest

import rev80 as vc
from rev80 import simulation as sim
from rev80 import tach

RUNNING_RATE = 29.37
RPM = RUNNING_RATE * 60.0


class _LiveStream:
    active = True


def _collector(tmp_path, streaming=True):
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq = 1000.0
    cfg.binsize = 0.5
    cfg.enabled_channels = [0, 1]
    cfg.channel_roles = {1: 'tachometer'}
    dc = vc.DataCollector(config=cfg)
    dc.init_trend_channels()
    if streaming:
        dc.sensor = object()
        dc.stream = _LiveStream()
    return dc


def _feed(dc, seed=5, rel_time=0.0):
    cfg = dc.config
    blocks = sim.GenerateMachineWithTach(
        sim._RawRateView(cfg), running_rate=RUNNING_RATE, severity=1.0, seed=seed)
    dc.receive_data({
        'data': np.column_stack([blocks[0], blocks[1]]),
        'channels': [0, 1], 'status': 'OKAY',
        'timestamp': datetime(2026, 9, 1), 'rel_time': rel_time,
        'samplerate': cfg.raw_samplerate, 'overflow_mask': 0, 'degraded': False,
    })


def _saved(tmp_path, frames=3):
    dc = _collector(tmp_path)
    for i in range(frames):
        _feed(dc, seed=5 + i, rel_time=float(i))
        dc.process_samples()
    path = tmp_path / 'tach.h5'
    dc.save_data(path)
    return dc, path


# --- file layout ---------------------------------------------------------

def test_measurement_file_is_version_5(tmp_path):
    _, path = _saved(tmp_path)
    with h5py.File(path, 'r') as f:
        assert int(f['metadata'].attrs['version']) == 5


def test_tach_channel_stores_edge_times_not_a_waveform(tmp_path):
    """The whole point of D-2. A waveform here would be ~1400x larger."""
    _, path = _saved(tmp_path)
    with h5py.File(path, 'r') as f:
        cg = f['frames/0/1']
        assert 'edge_times' in cg
        assert 'data' not in cg, 'a tach channel must not store its waveform'
        assert f['frames/0/0']['data'].size > 1000, 'vibration still stores its waveform'
        assert cg['edge_times'].size < 100


def test_tach_channel_metadata_records_role_and_calibration(tmp_path):
    _, path = _saved(tmp_path)
    with h5py.File(path, 'r') as f:
        assert f['metadata/channels/1'].attrs['role'] == 'tachometer'
        assert f['metadata/channels/0'].attrs['role'] == 'vibration'
        assert int(f['metadata/channels/1'].attrs['tach_pulses_per_rev']) == 1


def test_per_frame_rpm_is_stored_as_a_cross_check(tmp_path):
    _, path = _saved(tmp_path)
    with h5py.File(path, 'r') as f:
        cg = f['frames/0/1']
        assert float(cg.attrs['rpm']) == pytest.approx(RPM, rel=5e-3)
        assert cg.attrs['quality'] == tach.QUALITY_OK


def test_rpm_trend_is_persisted(tmp_path):
    _, path = _saved(tmp_path, frames=3)
    with h5py.File(path, 'r') as f:
        assert f['tach_trend/1/rpm'].size == 3
        assert np.allclose(f['tach_trend/1/rpm'][:], RPM, rtol=5e-3)


# --- round trip ----------------------------------------------------------

def test_reloaded_rpm_matches_what_was_stored(tmp_path):
    """Replay must reproduce what the live display showed."""
    dc, path = _saved(tmp_path)
    live = dc.current_rpm()

    dc2 = vc.DataCollector(config=vc.AcquisitionSettings())
    dc2.load_data(path)
    assert dc2.current_rpm() == pytest.approx(live, rel=1e-9)


def test_role_survives_the_round_trip(tmp_path):
    _, path = _saved(tmp_path)
    dc2 = vc.DataCollector(config=vc.AcquisitionSettings())
    dc2.load_data(path)
    assert dc2.config.role_for(1) == 'tachometer'
    assert dc2.config.tach_channels == [1]


def test_rpm_recomputes_when_pulses_per_rev_changes_after_load(tmp_path):
    """RPM is a view on stored data, not a value baked in at capture -- and
    edge times are enough to prove it, because ppr is a post-hoc divisor.
    """
    _, path = _saved(tmp_path)
    dc2 = vc.DataCollector(config=vc.AcquisitionSettings())
    dc2.load_data(path)
    before = dc2.current_rpm()
    dc2.set_tach_settings(1, tach.TachSettings(pulses_per_rev=2))
    assert dc2.current_rpm() == pytest.approx(before / 2.0, rel=1e-6)


def test_reloaded_tach_trend_is_restored(tmp_path):
    _, path = _saved(tmp_path, frames=3)
    dc2 = vc.DataCollector(config=vc.AcquisitionSettings())
    dc2.load_data(path)
    _, rpms = dc2.get_rpm_trend()[1]
    assert len(rpms) == 3


def test_a_file_with_no_tach_still_round_trips(tmp_path):
    """The overwhelming majority of files. Nothing above may disturb them."""
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq, cfg.binsize = 1000.0, 0.5
    cfg.enabled_channels = [0]
    dc = vc.DataCollector(config=cfg)
    dc.receive_data({
        'data': sim.GenerateBearingVibration(sim._RawRateView(cfg), seed=1)[:, None],
        'channels': [0], 'status': 'OKAY', 'timestamp': datetime(2026, 9, 1),
        'rel_time': 0.0, 'samplerate': cfg.raw_samplerate,
        'overflow_mask': 0, 'degraded': False,
    })
    path = tmp_path / 'plain.h5'
    dc.save_data(path)
    dc2 = vc.DataCollector(config=vc.AcquisitionSettings())
    dc2.load_data(path)
    assert dc2.config.role_for(0) == 'vibration'
    assert dc2.current_rpm() is None
    assert len(dc2.process_samples()) == 1


# --- version handling ----------------------------------------------------

def test_a_v4_file_loads_with_every_channel_as_vibration(tmp_path):
    """Files written before roles existed carry none, which is correct: they
    contain no tachometer channels."""
    _, path = _saved(tmp_path)
    with h5py.File(path, 'r+') as f:
        f['metadata'].attrs['version'] = 4
        for ch in ('0', '1'):
            del f[f'metadata/channels/{ch}'].attrs['role']
    dc2 = vc.DataCollector(config=vc.AcquisitionSettings())
    dc2.load_data(path)
    assert dc2.config.role_for(0) == 'vibration'
    assert dc2.config.role_for(1) == 'vibration'


def test_a_newer_file_version_warns_rather_than_misreading(tmp_path, caplog):
    """An older build reading a v5 file took the `version >= 4` branch and
    restored the tach as a vibration channel -- computing a bogus overall on a
    square wave and trending it. The guard is worth having on its own.
    """
    _, path = _saved(tmp_path)
    with h5py.File(path, 'r+') as f:
        f['metadata'].attrs['version'] = 99
    dc2 = vc.DataCollector(config=vc.AcquisitionSettings())
    with caplog.at_level('WARNING'):
        dc2.load_data(path)
    assert any('version' in r.message.lower() for r in caplog.records)


# --- duty cycle (R46 prerequisite, rolled into v5) ------------------------

def test_pulse_widths_and_duty_are_persisted(tmp_path):
    """Duty turns a reflector's physical size into a shaft diameter, and hence
    a surface velocity (R46). Rolled into v5 rather than a new version: the
    format has not shipped and no real-world file contains a TachResult yet.
    """
    import h5py as _h5
    _, path = _saved(tmp_path)
    with _h5.File(path, 'r') as f:
        cg = f['frames/0/1']
        assert 'pulse_widths' in cg
        assert cg['pulse_widths'].size > 0
        assert 0.0 < float(cg.attrs['duty_cycle']) < 1.0


def test_duty_survives_the_round_trip(tmp_path):
    dc, path = _saved(tmp_path)
    live = dc.current_frame()[1].tach.duty_cycle
    dc2 = vc.DataCollector(config=vc.AcquisitionSettings())
    dc2.load_data(path)
    reloaded = dc2.current_frame()[1].tach.duty_cycle
    assert reloaded == pytest.approx(live, rel=1e-9)
