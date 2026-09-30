"""A session with compression 'none' writes uncompressed data.

rev80-headless --no-compress, monitor.compression: none in acquisition.yaml
and the GUI compression checkbox all give the session compression='none'.
h5py has no filter of that name, so the writer must not pass it on.
"""

from datetime import datetime, timezone

import h5py
import numpy as np
import pytest

from rev80.monitor.session import MonitorSession
from rev80.monitor.writer import MonitorWriterThread
from rev80.sample import VibeSample


def _sample(rel_time=0.0) -> VibeSample:
    return VibeSample(status='OKAY', _timestamp=datetime.now(timezone.utc),
                      samplerate=1000, unit='mV', overflow=False,
                      data=np.arange(64, dtype=np.float64), rel_time=rel_time)


def _session(tmp_path, compression, level=4) -> MonitorSession:
    return MonitorSession(
        session_id='nc', start_time=datetime.now(), interval_s=60.0,
        pre_buffer_frames=2, burst_duration_s=10.0, max_burst_s=60.0,
        session_dir=tmp_path / 'nc', compression=compression,
        compression_level=level,
    )


def _write(session) -> MonitorWriterThread:
    writer = MonitorWriterThread(session)
    writer.start()
    now = datetime.now().isoformat()
    assert writer.enqueue({'frames': [{0: _sample()}], 'results': [],
                           'trigger': 'interval', 'rel_time': 0.0,
                           'timestamp': now})
    assert writer.enqueue({'frames': [{0: _sample(0.0)}, {0: _sample(1.0)}],
                           'results': [], 'trigger': 'burst', 'rel_time': 1.0,
                           'timestamp': now, 'burst_id': 'b1',
                           'n_pretrigger_frames': 1})
    writer.stop()
    return writer


@pytest.mark.parametrize('compression', ['none', None])
def test_no_compression_writes_uncompressed_data(tmp_path, compression):
    session = _session(tmp_path, compression)
    writer = _write(session)
    assert writer.error is None, writer.error
    assert writer.monitor_count == 1 and writer.burst_count == 1

    with h5py.File(session.session_h5, 'r') as f:
        for path in ('monitor/0/0/data', 'burst/b1/0/0/data', 'burst/b1/1/0/data'):
            ds = f[path]
            assert ds.compression is None, path
            np.testing.assert_array_equal(ds[()], np.arange(64))


def test_gzip_level_reaches_the_file(tmp_path):
    session = _session(tmp_path, 'gzip', level=7)
    writer = _write(session)
    assert writer.error is None, writer.error
    with h5py.File(session.session_h5, 'r') as f:
        ds = f['monitor/0/0/data']
        assert ds.compression == 'gzip'
        assert ds.compression_opts == 7

