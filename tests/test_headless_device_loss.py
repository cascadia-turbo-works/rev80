"""Headless exits with EXIT_DEVICE_LOST when the stream cannot start or dies.

Before, a stream that gave up left the main loop waiting for frames for
ever: an unattended logger that stopped with no log line.
"""

import threading
from types import SimpleNamespace

import h5py

from rev80 import headless
from rev80.simulation import SimulatedSensor


def _args(tmp_path):
    return SimpleNamespace(
        device='sim', start_now=True, channels=None, interval=0.5, pre_buffer=1.0,
        burst_duration=1.0, output=str(tmp_path / 'out'), no_compress=False,
        maxfreq=None, binsize=None, debug=False)


def _isolated_config(tmp_path, monkeypatch):
    import rev80.config as cfg
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'cfg'))
    monkeypatch.setattr('signal.signal', lambda *a: None)
    cfg.ensure_config_dir()


def test_stream_that_dies_exits_with_device_lost(tmp_path, monkeypatch):
    _isolated_config(tmp_path, monkeypatch)
    original_start = SimulatedSensor.start

    def start_then_die(self):
        original_start(self)

        def die():
            self.fault = 'device lost: not back within 30 s'
            self._running = False
        threading.Timer(1.5, die).start()

    monkeypatch.setattr(SimulatedSensor, 'start', start_then_die)
    result = {}
    worker = threading.Thread(target=lambda: result.update(rc=headless.run(_args(tmp_path))),
                              daemon=True)
    worker.start()
    worker.join(timeout=20.0)
    assert not worker.is_alive(), 'headless did not notice the dead stream'
    assert result['rc'] == headless.EXIT_DEVICE_LOST

    files = list((tmp_path / 'out').glob('*/session.h5'))
    assert len(files) == 1
    with h5py.File(files[0], 'r'):          # closed and readable
        pass


def test_stream_that_does_not_start_exits_with_device_lost(tmp_path, monkeypatch):
    _isolated_config(tmp_path, monkeypatch)

    def fail(self):
        raise RuntimeError('PicoScope TEST/0001 not connected')

    from rev80.monitor.controller import MonitorController
    started = []
    monkeypatch.setattr(SimulatedSensor, 'start', fail)
    monkeypatch.setattr(MonitorController, 'start', lambda self, *a, **k: started.append(1))
    assert headless.run(_args(tmp_path)) == headless.EXIT_DEVICE_LOST
    assert started == []                # no session for a stream that never ran
