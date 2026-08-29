"""Regression tests for GUI._on_sb_save_config (session browser "Save Config").

Background: gui.py called h5py.File() in _on_sb_save_config but never imported
h5py at module scope — the three other users each did a function-local import
and this one did not. The resulting NameError was swallowed by a broad
`except Exception` and logged as "failed to patch {session_h5}", so the button
was silently dead code and the error message misdirected the user toward disk
permissions. These tests pin both the import and the narrowed except clause.
"""

import h5py
import pytest

import rev80.gui as gui_module
from rev80.collector import DataCollector
from rev80.gui import GUI
from rev80.sample import AcquisitionSettings
from rev80.scope_sensor import ScopeSensor


def test_gui_module_imports_h5py_at_module_scope():
    """gui.py must bind h5py at module scope — several methods use it directly."""
    assert hasattr(gui_module, 'h5py'), (
        'rev80.gui must import h5py at module scope; _on_sb_save_config '
        'references h5py.File() outside any function-local import'
    )
    assert gui_module.h5py is h5py


def _make_gui_stub(session_h5, tmp_path):
    """Build a GUI with only the attributes _on_sb_save_config touches.

    GUI() itself needs a DPG context for anything visual, so bypass __init__
    and wire up just the collector/session state the method reads.
    """
    app = object.__new__(GUI)
    cfg = AcquisitionSettings()
    cfg.enabled_channels = [0]
    app.collector = DataCollector(config=cfg)
    app.collector.scope_sensors = {
        0: ScopeSensor(name='PCB 352C33', engineering_units='g', sensitivity=10.2)
    }
    app._current_session_h5 = session_h5
    # _on_sb_save_config ends by reprocessing the trend, which needs live DPG
    # widgets. Stub it out — this test is about the h5 patch, not the replot.
    app._on_sb_reprocess = lambda *a, **k: None
    return app


def test_save_config_writes_metadata_groups(tmp_path):
    """The happy path actually patches the file — it used to be a no-op NameError."""
    session_h5 = tmp_path / 'session.h5'
    with h5py.File(session_h5, 'w') as f:
        f.require_group('metadata')

    app = _make_gui_stub(session_h5, tmp_path)
    app._on_sb_save_config()

    with h5py.File(session_h5, 'r') as f:
        assert 'metadata/channels/0' in f, 'channel metadata was not written'
        ch = f['metadata/channels/0']
        assert ch.attrs['scope_sensor_id']
        # The sensor library group must carry the datasheet sensitivity under
        # the canonical 'sensitivity' key that ScopeSensor.to_dict() emits.
        ss_grp = f['metadata/scope_sensors']
        (sensor_id,) = list(ss_grp.keys())
        assert ss_grp[sensor_id].attrs['sensitivity'] == pytest.approx(10.2)
        assert ss_grp[sensor_id].attrs['engineering_units'] == 'g'


def test_save_config_reports_io_failure_without_crashing(tmp_path):
    """A genuine I/O failure is still caught and logged, not raised."""
    missing = tmp_path / 'nope' / 'session.h5'   # parent dir does not exist
    app = _make_gui_stub(missing, tmp_path)
    app._on_sb_save_config()   # must not raise — OSError is handled


def test_save_config_does_not_swallow_programming_errors(tmp_path):
    """The except clause is narrow: non-IO exceptions propagate.

    The old bare `except Exception` hid NameError/AttributeError bugs behind a
    disk-failure message. Anything that is not OSError/KeyError must surface.
    """
    session_h5 = tmp_path / 'session.h5'
    with h5py.File(session_h5, 'w') as f:
        f.require_group('metadata')

    app = _make_gui_stub(session_h5, tmp_path)

    class Boom:
        def get(self, _ch):
            raise RuntimeError('simulated programming error')

    app.collector.scope_sensors = Boom()

    with pytest.raises(RuntimeError, match='simulated programming error'):
        app._on_sb_save_config()
