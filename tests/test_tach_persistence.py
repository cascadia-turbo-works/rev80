"""HDF5 persistence for tachometer channels (measurement file v5).

A tachometer channel stores edge times, not the waveform: about 30 float64 per
second against 25600 samples per second at 1 ppr and 30 Hz (a factor of about
850). Re-thresholding after capture is not possible. RPM stays a view on stored
data, because pulses_per_rev is a divisor applied to the stored intervals.
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
    """The tach channel group has edge_times and no 'data' dataset.

    Here a 2 s block is 51200 samples against about 59 edge times.
    """
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
    """The reloaded rpm equals the live rpm, so replay shows what the live display showed."""
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
    """After load, a new pulses_per_rev changes the rpm by that factor.

    RPM is a view on the stored edge times, not a value fixed at capture.
    """
    _, path = _saved(tmp_path)
    dc2 = vc.DataCollector(config=vc.AcquisitionSettings())
    dc2.load_data(path)
    before = dc2.current_rpm()
    dc2.set_tach_settings(1, tach.TachSettings(pulses_per_rev=2))
    assert dc2.current_rpm() == pytest.approx(before / 2.0, rel=1e-6)


def test_reinterpreting_at_a_ppr_the_block_cannot_support_withholds_the_rate(tmp_path):
    """A ppr that the stored edges cannot support gives rpm None.

    The frames hold about 59 edges in a 2 s block at 1 ppr. As a 60-line
    encoder, those edges are 0.97 of a revolution, which is under MIN_REVS.
    """
    _, path = _saved(tmp_path)
    dc2 = vc.DataCollector(config=vc.AcquisitionSettings())
    dc2.load_data(path)
    assert dc2.current_rpm() is not None
    dc2.set_tach_settings(1, tach.TachSettings(pulses_per_rev=60))
    assert dc2.current_rpm() is None


def test_reloaded_tach_trend_is_restored(tmp_path):
    _, path = _saved(tmp_path, frames=3)
    dc2 = vc.DataCollector(config=vc.AcquisitionSettings())
    dc2.load_data(path)
    _, rpms = dc2.get_rpm_trend()[1]
    assert len(rpms) == 3


def test_a_file_with_no_tach_still_round_trips(tmp_path):
    """A file with no tachometer channel round-trips unchanged."""
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
    """A v4 file has no role attribute, so every channel loads as 'vibration'.

    v4 files contain no tachometer channels.
    """
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
    """A file version newer than this build logs a warning.

    A build that misreads a newer layout could, for example, restore a tach
    channel as a vibration channel and compute an overall on a square wave.
    """
    _, path = _saved(tmp_path)
    with h5py.File(path, 'r+') as f:
        f['metadata'].attrs['version'] = 99
    dc2 = vc.DataCollector(config=vc.AcquisitionSettings())
    with caplog.at_level('WARNING'):
        dc2.load_data(path)
    assert any('version' in r.message.lower() for r in caplog.records)


# --- duty cycle ----------------------------------------------------------

def test_pulse_widths_and_duty_are_persisted(tmp_path):
    """The tach group stores pulse_widths and a duty_cycle attribute.

    Surface velocity from reflector size and duty is tracked as R46 in
    doc/PROGRESS.md.
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
