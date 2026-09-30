"""The unattended resource trail logs the real interval capture count."""

from collections import deque

from rev80.monitor import controller as controller_mod
from rev80.monitor.controller import MonitorController
from test_monitor_burst_cap import _feed, _session


def test_resource_trail_logs_the_capture_count(tmp_path, monkeypatch):
    infos: list[str] = []

    class _Log:
        def info(self, msg, *args):
            infos.append(msg % args if args else msg)

        def __getattr__(self, name):
            return lambda *a, **k: None

    session = _session(tmp_path)
    ctrl = MonitorController()
    cache: deque = deque(maxlen=64)
    ctrl.start(session, None)
    try:
        _feed(ctrl, cache, 1)             # the first frame is an interval capture
        assert ctrl._capture_count == 1
        monkeypatch.setattr(controller_mod, 'log', _Log())
        ctrl._last_trail_mono = float('-inf')
        ctrl._log_resource_trail(0.0)
    finally:
        ctrl.stop()
    trail = [m for m in infos if m.startswith('monitor trail')]
    assert trail, infos
    assert 'captures 1' in trail[0], trail[0]
