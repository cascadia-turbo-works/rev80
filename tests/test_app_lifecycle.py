"""The app must always shut down cleanly, however it exits (audit S-01).

Two defects that compound, and together explain both halves of the reported
symptom — "I came back and the session was truncated, and then the scope
wouldn't connect until I replugged it":

  * GUI.cleanup() never called self._monitor.stop(), and the writer is a
    DAEMON thread. The interpreter kills daemons without unwinding, possibly
    mid-h5py.File(..., 'a'), with captures still queued and unwritten.
    MonitorController.stop() already flushes the partial burst and drains the
    writer correctly — it was simply never reached on app close.

  * GUI.run()'s loop body had no try/except and __main__.main() had no
    try/finally, so ANY exception in the render path skipped cleanup()
    entirely and ps4000aCloseUnit never ran. The next launch then gets
    PICO_NOT_FOUND until the USB is physically replugged.

Render-loop policy: log once per exception TYPE so a persistent fault cannot
flood the rotating log at frame rate (the S-09 failure mode), keep rendering
so a single bad frame does not end an overnight run, and after a run of
consecutive failures shut down cleanly THROUGH cleanup() rather than dying.
"""

import logging

import pytest

from rev80.gui import GUI


class _FakeMonitor:
    def __init__(self, recording=True):
        self.is_recording = recording
        self.stopped = 0

    def stop(self):
        self.stopped += 1


class _FakeCollector:
    def __init__(self):
        self.disconnected = 0

    def disconnect_sensor(self):
        self.disconnected += 1


def _app(monitor=None, collector=None):
    """A GUI shell with no DPG context, for lifecycle logic only."""
    app = GUI.__new__(GUI)
    app._monitor = monitor
    app.collector = collector or _FakeCollector()
    app._render_errors = {}
    app._consecutive_render_errors = 0
    app._cleaned_up = False
    return app


# ---------------------------------------------------------------------------
# cleanup() must stop the monitor
# ---------------------------------------------------------------------------

def test_cleanup_stops_a_recording_monitor(monkeypatch):
    monkeypatch.setattr('dearpygui.dearpygui.destroy_context', lambda: None)
    mon = _FakeMonitor(recording=True)
    app = _app(monitor=mon)
    app.cleanup()
    assert mon.stopped == 1, 'monitor not stopped — session truncated on close'


def test_cleanup_stops_the_monitor_before_closing_the_device(monkeypatch):
    """Order matters: the writer needs the session flushed before teardown."""
    monkeypatch.setattr('dearpygui.dearpygui.destroy_context', lambda: None)
    order = []
    mon, col = _FakeMonitor(), _FakeCollector()
    mon.stop = lambda: order.append('monitor')
    col.disconnect_sensor = lambda: order.append('device')
    app = _app(monitor=mon, collector=col)
    app.cleanup()
    assert order == ['monitor', 'device'], order


def test_cleanup_with_no_monitor_is_fine(monkeypatch):
    monkeypatch.setattr('dearpygui.dearpygui.destroy_context', lambda: None)
    app = _app(monitor=None)
    app.cleanup()
    assert app.collector.disconnected == 1


def test_cleanup_still_closes_the_device_if_the_monitor_raises(monkeypatch, caplog):
    """A failing monitor must not strand the scope — that is the whole point."""
    monkeypatch.setattr('dearpygui.dearpygui.destroy_context', lambda: None)
    mon = _FakeMonitor()
    mon.stop = lambda: (_ for _ in ()).throw(RuntimeError('writer wedged'))
    app = _app(monitor=mon)
    with caplog.at_level(logging.ERROR):
        app.cleanup()
    assert app.collector.disconnected == 1, 'device left open after a monitor failure'


def test_cleanup_is_idempotent(monkeypatch):
    """run()'s finally and an explicit call must not double-stop."""
    monkeypatch.setattr('dearpygui.dearpygui.destroy_context', lambda: None)
    mon = _FakeMonitor()
    app = _app(monitor=mon)
    app.cleanup()
    app.cleanup()
    assert app.collector.disconnected == 1
    assert mon.stopped == 1


# ---------------------------------------------------------------------------
# Render-loop guard
# ---------------------------------------------------------------------------

def test_render_error_is_logged_once_per_type(caplog):
    app = _app()
    app._render_errors = {}
    app._consecutive_render_errors = 0
    # Stay under the shutdown threshold: the give-up notice is a second,
    # deliberate record and is covered by its own test below.
    with caplog.at_level(logging.ERROR):
        for _ in range(GUI.MAX_CONSECUTIVE_RENDER_ERRORS - 1):
            app._handle_render_error(ValueError('same fault every frame'))
    errs = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errs) == 1, f'{len(errs)} records — a persistent fault floods the log'
    assert app._render_errors['ValueError'] == GUI.MAX_CONSECUTIVE_RENDER_ERRORS - 1


def test_a_new_error_type_is_logged_separately(caplog):
    app = _app()
    app._render_errors = {}
    app._consecutive_render_errors = 0
    with caplog.at_level(logging.ERROR):
        app._handle_render_error(ValueError('one'))
        app._handle_render_error(KeyError('two'))
    assert len([r for r in caplog.records if r.levelno >= logging.ERROR]) == 2


def test_render_errors_do_not_stop_the_app_immediately():
    app = _app()
    app._render_errors = {}
    app._consecutive_render_errors = 0
    assert app._handle_render_error(ValueError('transient')) is True


def test_sustained_render_failure_asks_for_a_clean_shutdown():
    """A fault that repeats every frame is not transient; stop rather than spin."""
    app = _app()
    app._render_errors = {}
    app._consecutive_render_errors = 0
    results = [app._handle_render_error(ValueError('persistent'))
               for _ in range(GUI.MAX_CONSECUTIVE_RENDER_ERRORS + 1)]
    assert results[-1] is False, 'never gave up — would spin forever on a dead frame'
    assert any(r is True for r in results[:-1])


def test_a_good_frame_resets_the_failure_streak():
    """Occasional bad frames over a long run must not accumulate to a shutdown."""
    app = _app()
    app._render_errors = {}
    app._consecutive_render_errors = 0
    for _ in range(GUI.MAX_CONSECUTIVE_RENDER_ERRORS - 1):
        app._handle_render_error(ValueError('blip'))
    app._note_render_success()
    assert app._consecutive_render_errors == 0
    assert app._handle_render_error(ValueError('blip')) is True


@pytest.mark.parametrize('exc', [ValueError('v'), KeyError('k'), ZeroDivisionError('z')])
def test_handler_never_reraises(exc):
    """X-02: a malformed .h5 gives ZeroDivisionError in the render path. It
    must become a logged error, not an exit that strands the device."""
    app = _app()
    app._render_errors = {}
    app._consecutive_render_errors = 0
    assert app._handle_render_error(exc) in (True, False)
