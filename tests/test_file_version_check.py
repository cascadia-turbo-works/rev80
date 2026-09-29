"""Each file type is checked against its own version limit.

Measurement files are DataCollector._FILE_VERSION (5); monitor sessions are
monitor.writer._FILE_VERSION (6). The session loaders used to call
_restore_metadata, which compared every file with 5 only, so every load of a
current session logged "File version 6 is newer than this build supports (5)".
The warning must still fire for a file that really is newer than its type.
"""

import logging
from datetime import datetime

import h5py
import numpy as np
import pytest

from rev80.collector import DataCollector
from rev80.monitor import writer

from test_monitor_session_load import _make_collector, _make_session, _record_session

WARNING_TEXT = 'newer than this build supports'


def _newer_warnings(caplog):
    return [r for r in caplog.records
            if r.levelno >= logging.WARNING and WARNING_TEXT in r.getMessage()]


def _set_version(h5_path, version):
    with h5py.File(h5_path, 'a') as f:
        attrs = f['metadata'].attrs
        key = 'version' if 'version' in attrs else 'file_version'
        attrs[key] = version


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
    for i in range(2):
        dc.receive_data({
            'status': 'OKAY', 'overflow_mask': 0,
            'rel_time': float(i), 'timestamp': datetime.now(),
            'unit': ['mV'], 'channels': [0],
            'data': np.zeros((dc.config.raw_blocksize, 1)),
            'samplerate': dc.config.raw_samplerate, 'degraded': False,
        })
    target = tmp_path / 'measurement.h5'
    dc.save_data(target)
    with h5py.File(target, 'r') as f:
        assert int(f['metadata'].attrs['version']) == DataCollector._FILE_VERSION
    return target


def test_session_version_is_newer_than_measurement_version():
    # The premise of this file: if the two ever become equal, the tests
    # below no longer distinguish the two limits.
    assert writer._FILE_VERSION > DataCollector._FILE_VERSION


def test_current_session_loads_without_version_warning(session_h5, caplog):
    caplog.set_level(logging.WARNING)
    _make_collector().load_monitor_session(session_h5)
    assert _newer_warnings(caplog) == []


def test_newer_session_still_warns(session_h5, caplog):
    _set_version(session_h5, writer._FILE_VERSION + 1)
    caplog.set_level(logging.WARNING)
    _make_collector().load_monitor_session(session_h5)
    assert len(_newer_warnings(caplog)) == 1


def test_current_measurement_file_loads_without_version_warning(measurement_h5, caplog):
    caplog.set_level(logging.WARNING)
    DataCollector().load_data(measurement_h5)
    assert _newer_warnings(caplog) == []


def test_measurement_file_at_session_version_warns(measurement_h5, caplog):
    _set_version(measurement_h5, writer._FILE_VERSION)
    caplog.set_level(logging.WARNING)
    DataCollector().load_data(measurement_h5)
    assert len(_newer_warnings(caplog)) == 1
