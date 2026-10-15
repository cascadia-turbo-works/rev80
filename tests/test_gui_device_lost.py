"""The GUI shows a lost device and never calls the driver on it.

A stream that gave up (the scope was lost and did not come back), and a start
that failed, both end on the Device card as "Device lost" with the reason.
These tests use a GUI shell with no DPG context.
"""

from types import SimpleNamespace

from rev80.gui import GUI


class _Collector:
    def __init__(self, fault=None, streaming=False):
        self.stream = SimpleNamespace(fault=fault, active=streaming)
        self.sensor = object()
        self.start_error = None
        self.disconnects = 0
        self.device_lost_for_s = None

    @property
    def stream_fault(self):
        return getattr(self.stream, 'fault', None)

    @property
    def is_streaming(self):
        return bool(self.stream and self.stream.active)

    def disconnect_sensor(self):
        self.disconnects += 1
        self.stream = None
        self.sensor = None


def _app(collector):
    app = GUI.__new__(GUI)
    app.collector = collector
    app._monitor = None
    app._status_deadline = 123.0
    app._device_fault = None
    app._waiting_text = None
    shown = []
    app._set_stream_status = shown.append
    app._update_connection_summary = lambda: shown.append(('summary', app._device_fault))
    app._update_browse_label = lambda: None
    return app, shown


def test_a_stream_fault_disconnects_once_and_shows_the_reason():
    collector = _Collector(fault='device lost: not back within 30 s')
    app, shown = _app(collector)
    app._check_stream_fault()
    app._check_stream_fault()               # the next render tick: nothing more
    assert collector.disconnects == 1
    assert app._device_fault == 'device lost: not back within 30 s'
    assert shown == ['idle', ('summary', 'device lost: not back within 30 s')]
    assert app._status_deadline is None


def test_a_running_stream_is_left_alone():
    collector = _Collector(fault=None, streaming=True)
    app, shown = _app(collector)
    app._check_stream_fault()
    assert collector.disconnects == 0 and shown == []


def test_a_failed_start_shows_the_reason():
    collector = _Collector()
    app, shown = _app(collector)
    app._browse_context = {}
    app._autoscale_pending = False

    def start_stream():
        collector.start_error = 'PicoScope TEST/0001 not connected'
        collector.disconnect_sensor()

    collector.start_stream = start_stream
    collector.clear_trend = lambda: None
    app._start_stream()
    assert app._device_fault == 'PicoScope TEST/0001 not connected'
    assert shown[-2:] == ['idle', ('summary', 'PicoScope TEST/0001 not connected')]


def test_waiting_for_the_scope_shows_the_time_then_clears(monkeypatch):
    import rev80.gui as gui_module
    values = []
    monkeypatch.setattr(gui_module.dpg, 'does_item_exist', lambda tag: True)
    monkeypatch.setattr(gui_module.dpg, 'set_value', lambda tag, v: values.append(v))
    collector = _Collector(streaming=True)
    app, shown = _app(collector)
    app._set_device_status = lambda state: shown.append(('status', state))

    collector.device_lost_for_s = 65.2
    app._check_stream_fault()
    app._check_stream_fault()               # same second: no widget change
    assert values == ['Device lost — waiting 01:05']
    assert collector.disconnects == 0       # still streaming: no disconnect

    collector.device_lost_for_s = None      # the scope came back
    app._check_stream_fault()
    assert app._waiting_text is None
    assert shown[-1] == ('summary', None)
