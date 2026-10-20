"""scripts/convert-0x copies a 0.x data file into the format Rev80 1.0 reads.

The 0.x files are made by the current writers and then taken back to the
0.x layout: the version number, and no `rev80_version`, `chart_layout_json`,
`orders_mv` or `orders_key`. A converted copy must load in this build with
the same frames and trend as the source and the default chart layout, and
the source must not change.
"""

import hashlib
import importlib.machinery
import importlib.util
from pathlib import Path

import h5py
import numpy as np
import pytest

import rev80 as vc
from rev80 import charts
from rev80.monitor import writer

from test_file_layout import _feed, _live
from test_monitor_session_load import N_CHANNELS, _make_collector, _make_session, _record_session
from pipeline_helpers import tick

_SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'convert-0x'


def _load_script():
    loader = importlib.machinery.SourceFileLoader('convert_0x', str(_SCRIPT))
    spec = importlib.util.spec_from_loader('convert_0x', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


cv = _load_script()


def _to_0x(h5, version):
    """Take a current file back to the 0.x layout at `version`."""
    with h5py.File(h5, 'a') as f:
        attrs = f['metadata'].attrs
        attrs['version' if 'version' in attrs else 'file_version'] = version
        for key in ('rev80_version', 'chart_layout_json'):
            if key in attrs:
                del attrs[key]

        def strip(_name, obj):
            for key in ('orders_mv', 'orders_key'):
                if key in obj.attrs:
                    del obj.attrs[key]
            if version <= 4 and 'role' in obj.attrs:
                del obj.attrs['role']
        f.visititems(strip)


def _sha(path):
    if path.is_dir():
        return {p.name: _sha(p) for p in sorted(path.iterdir())}
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _LiveStream:
    """Makes the collector count as streaming, so each tick adds a trend point."""
    active = True

    def stop(self):
        self.active = False

    def close(self):
        pass


def _measurement(tmp_path, version, tach=True):
    dc = _live()
    dc.sensor, dc.stream = object(), _LiveStream()
    if not tach:
        dc.config.enabled_channels = [0]
        dc.config.channel_roles = {}
        dc.init_trend_channels()
    for i in range(4):
        _feed(dc, i)
        tick(dc)
    path = tmp_path / 'run.h5'
    dc.save_data(path)
    _to_0x(path, version)
    return path


def _frames(h5, kind='measurement'):
    """{(frame, ch): data} of every vibration channel group with data."""
    out = {}
    with h5py.File(h5, 'r') as f:
        groups = f['frames'] if kind == 'measurement' else f['monitor']
        for k, fg in groups.items():
            for ch, cg in fg.items():
                if ch.isdigit() and 'data' in cg:
                    out[(k, ch)] = cg['data'][()]
    return out


# --- measurement files ------------------------------------------------------

@pytest.mark.parametrize('version', [5, 4])
def test_a_0x_measurement_converts_and_loads(tmp_path, version):
    src = _measurement(tmp_path, version, tach=(version == 5))
    sha = _sha(src)
    dest = cv.convert(src)
    assert dest == tmp_path / 'run.v6.h5'
    assert _sha(src) == sha                                  # source unchanged
    dc = vc.DataCollector()
    dc.load_data(dest)                                       # no FileVersionError
    # The same frames and trend as the source.
    frames = _frames(dest)
    assert frames.keys() == _frames(src).keys()
    for key, data in _frames(src).items():
        np.testing.assert_array_equal(frames[key], data)
    with h5py.File(src, 'r') as f:
        assert f['trend/0/orders'].shape == (4, 5)
        np.testing.assert_array_equal(dc.trend[0]['orders'], f['trend/0/orders'][()])
    # The default layout: channel 0 only (channel 1 is a tachometer), in the
    # record view of channel 0: its sensor's EU, g.
    assert dc.chart_set == charts.default_layout([0], lambda ch: ('g', '0-P'))
    with h5py.File(dest, 'r') as f:
        assert f['metadata'].attrs['rev80_version'].startswith('convert-0x')


def test_the_layout_follows_the_stored_target_unit(tmp_path):
    src = _measurement(tmp_path, 5)
    with h5py.File(src, 'a') as f:
        f['metadata/channels/0'].attrs['target_unit'] = 'in/s'
        f['metadata/channels/0'].attrs['amplitude_mode'] = 'RMS'
    dc = vc.DataCollector()
    dc.load_data(cv.convert(src))
    assert [(c.unit, c.amplitude_mode) for c in dc.chart_set.charts] == [
        ('in/s', ''), ('in/s', 'RMS')]


def test_a_v3_measurement_is_refused_and_nothing_is_written(tmp_path):
    src = _measurement(tmp_path, 3)
    with pytest.raises(cv.ConvertError, match='Rev80 0.1.5, save it again'):
        cv.convert(src)
    assert sorted(p.name for p in tmp_path.iterdir()) == ['run.h5']


def test_a_current_file_is_not_converted(tmp_path):
    src = _measurement(tmp_path, 5)
    dest = cv.convert(src)
    with pytest.raises(cv.ConvertError, match='already version 6'):
        cv.convert(dest)


def test_an_existing_copy_is_not_overwritten(tmp_path):
    src = _measurement(tmp_path, 5)
    (tmp_path / 'run.v6.h5').write_bytes(b'keep me')
    with pytest.raises(cv.ConvertError, match='not overwritten'):
        cv.convert(src)
    assert (tmp_path / 'run.v6.h5').read_bytes() == b'keep me'


def test_out_directory(tmp_path):
    src = _measurement(tmp_path, 5)
    dest = cv.convert(src, tmp_path / 'converted')
    assert dest == tmp_path / 'converted' / 'run.v6.h5'
    vc.DataCollector().load_data(dest)


def test_a_failed_conversion_leaves_no_copy(tmp_path, monkeypatch):
    src = _measurement(tmp_path, 5)

    def boom(*_a, **_k):
        raise RuntimeError('simulated failure')
    monkeypatch.setattr(cv, 'default_layout_for', boom)
    with pytest.raises(RuntimeError):
        cv.convert(src)
    assert not (tmp_path / 'run.v6.h5').exists()


# --- monitor sessions --------------------------------------------------------

@pytest.fixture
def old_session(tmp_path):
    session = _make_session(tmp_path)
    _record_session(session, n_intervals=4, n_bursts=1)
    _to_0x(session.session_h5, 6)
    return session.session_dir


@pytest.mark.parametrize('give', ['dir', 'h5'])
def test_a_0x_session_converts_and_loads(old_session, give):
    sha = _sha(old_session)
    arg = old_session if give == 'dir' else old_session / 'session.h5'
    dest = cv.convert(arg)
    assert dest == old_session.parent / f'{old_session.name}.v{writer._FILE_VERSION}'
    assert _sha(old_session) == sha
    h5 = dest / 'session.h5'
    col = _make_collector()
    col.load_monitor_session(h5)
    with h5py.File(old_session / 'session.h5', 'r') as f:
        assert len(col.data['frame_cache']) == len(f['monitor'])
    for key, data in _frames(old_session / 'session.h5', 'session').items():
        np.testing.assert_array_equal(_frames(h5, 'session')[key], data)
    channels = list(range(N_CHANNELS))
    assert col.chart_set == charts.default_layout(channels, lambda ch: ('mV', '0-P'))
    # A burst of the converted session loads, with the session's layout.
    with h5py.File(h5, 'r') as f:
        burst_id = next(k for k in f['burst'].keys())
    col.load_monitor_burst(h5, burst_id)
    assert col.chart_set == charts.default_layout(channels, lambda ch: ('mV', '0-P'))


def test_an_older_session_version_is_refused(old_session):
    _to_0x(old_session / 'session.h5', 5)
    with pytest.raises(cv.ConvertError, match='Open it with Rev80 0.1.5'):
        cv.convert(old_session)


# --- command line -------------------------------------------------------------

def test_main_reports_each_path(tmp_path, capsys):
    good = _measurement(tmp_path, 5)
    missing = tmp_path / 'missing.h5'
    assert cv.main([str(good), str(missing)]) == 1
    out, err = capsys.readouterr()
    assert 'run.v6.h5' in out
    assert 'not converted' in err and 'missing.h5' in err
    assert cv.main([str(tmp_path / 'run.h5'), '--out', str(tmp_path / 'again')]) == 0
