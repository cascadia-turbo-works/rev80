"""Each file type is read at exactly the version this build writes.

Measurement files use DataCollector._FILE_VERSION (6). Monitor sessions use
monitor.writer._FILE_VERSION (7). An older or a newer file is refused with
FileVersionError before any state changes. The message names the file and
says what to do: open a 0.x file with Rev80 0.1.5 or convert a copy; update
Rev80 for a newer file.
"""

import hashlib
from datetime import datetime

import h5py
import numpy as np
import pytest

import rev80
from rev80.collector import DataCollector, FileVersionError, check_file_version
from rev80.monitor import writer

from test_monitor_session_load import _make_collector, _make_session, _record_session


def _set_version(h5_path, version, drop_writer=False):
    with h5py.File(h5_path, 'a') as f:
        attrs = f['metadata'].attrs
        key = 'version' if 'version' in attrs else 'file_version'
        attrs[key] = version
        if drop_writer:
            del attrs['rev80_version']


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _feed(dc, n, t0=0.0):
    for i in range(n):
        dc.receive_data({
            'status': 'OKAY', 'overflow_mask': 0,
            'rel_time': t0 + float(i), 'timestamp': datetime.now(),
            'unit': ['mV'], 'channels': [0],
            'data': np.zeros((dc.config.raw_blocksize, 1)),
            'samplerate': dc.config.raw_samplerate, 'degraded': False,
        })


@pytest.fixture
def session_h5(tmp_path):
    session = _make_session(tmp_path)
    _record_session(session, n_intervals=4, n_bursts=0)
    with h5py.File(session.session_h5, 'r') as f:
        assert int(f['metadata'].attrs['file_version']) == writer._FILE_VERSION
    return session.session_h5


@pytest.fixture
def measurement_h5(tmp_path):
    dc = DataCollector()
    dc.config.enabled_channels = [0]
    _feed(dc, 2)
    target = tmp_path / 'measurement.h5'
    dc.save_data(target)
    with h5py.File(target, 'r') as f:
        assert int(f['metadata'].attrs['version']) == DataCollector._FILE_VERSION
    return target


def test_the_two_types_have_their_own_versions():
    assert DataCollector._FILE_VERSION == 6
    assert writer._FILE_VERSION == 7


def test_current_files_load(session_h5, measurement_h5):
    col = _make_collector()
    col.load_monitor_session(session_h5)
    assert len(col.data['frame_cache']) > 0
    dc = DataCollector()
    dc.load_data(measurement_h5)
    assert len(dc.data['frame_cache']) == 2


# --- older files ----------------------------------------------------------

@pytest.mark.parametrize('version, convertible', [(5, True), (4, True), (3, False)])
def test_an_older_measurement_file_is_refused(measurement_h5, version, convertible):
    _set_version(measurement_h5, version, drop_writer=True)
    with pytest.raises(FileVersionError) as err:
        DataCollector().load_data(measurement_h5)
    msg = str(err.value)
    assert measurement_h5.name in msg
    assert f'version {version}' in msg and 'Rev80 0.x' in msg
    assert 'Rev80 0.1.5' in msg
    assert 'convert' in msg                       # directly, or after a save in 0.1.5
    assert ('save it again' in msg) is (not convertible)


@pytest.mark.parametrize('load', ['session', 'capture', 'burst'])
def test_an_older_session_is_refused_by_every_loader(session_h5, load):
    _set_version(session_h5, 6, drop_writer=True)
    col = _make_collector()
    call = {'session': lambda: col.load_monitor_session(session_h5),
            'capture': lambda: col.load_monitor_capture(session_h5, 0),
            'burst':   lambda: col.load_monitor_burst(session_h5, 'none')}[load]
    with pytest.raises(FileVersionError, match='Rev80 0.1.5, or convert a copy'):
        call()


# --- newer files ----------------------------------------------------------

def test_a_newer_session_is_refused(session_h5):
    _set_version(session_h5, writer._FILE_VERSION + 1)
    with h5py.File(session_h5, 'a') as f:
        f['metadata'].attrs['rev80_version'] = '1.4.0'
    with pytest.raises(FileVersionError) as err:
        _make_collector().load_monitor_session(session_h5)
    msg = str(err.value)
    assert 'written by Rev80 1.4.0' in msg and 'Update Rev80' in msg


def test_a_newer_measurement_file_is_refused(measurement_h5):
    _set_version(measurement_h5, DataCollector._FILE_VERSION + 1, drop_writer=True)
    with pytest.raises(FileVersionError, match='a newer Rev80.*Update Rev80'):
        DataCollector().load_data(measurement_h5)


# --- the wrong type -------------------------------------------------------

def test_a_session_given_to_the_measurement_loader_is_refused(session_h5):
    with pytest.raises(FileVersionError, match='is a monitor session'):
        DataCollector().load_data(session_h5)


def test_a_measurement_file_given_to_the_session_loader_is_refused(measurement_h5):
    with pytest.raises(FileVersionError, match='is a measurement file'):
        _make_collector().load_monitor_session(measurement_h5)


# --- a refusal changes nothing ---------------------------------------------

def test_a_refused_load_leaves_the_collector_unchanged(tmp_path, measurement_h5):
    dc = DataCollector()
    dc.config.enabled_channels = [0]
    _feed(dc, 3, t0=100.0)
    before = [id(fr) for fr in dc.data['frame_cache']]
    config_before = dc.config.to_dict()
    _set_version(measurement_h5, 5, drop_writer=True)
    with pytest.raises(FileVersionError):
        dc.load_data(measurement_h5)
    assert [id(fr) for fr in dc.data['frame_cache']] == before
    assert dc.config.to_dict() == config_before


def test_reprocess_never_writes_into_an_older_session(session_h5):
    _set_version(session_h5, 6, drop_writer=True)
    sha = _sha(session_h5)
    with pytest.raises(FileVersionError):
        _make_collector().reprocess_session_trend(session_h5)
    assert _sha(session_h5) == sha


def test_check_file_version_is_exported():
    assert rev80.check_file_version is check_file_version
    assert rev80.FileVersionError is FileVersionError
