"""The app shuts down cleanly, however it exits.

GUI.cleanup() stops the monitor first, then closes the device. The writer is a
daemon thread and loses queued captures at exit. The render loop logs once for
each exception type and shuts down through cleanup() after repeated failures.
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
    """The monitor stops before the device closes, so the session is flushed."""
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
    """The device closes even when the monitor stop raises."""
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
    """An error in the render path (for example ZeroDivisionError from a
    malformed .h5) is logged and never re-raised."""
    app = _app()
    app._render_errors = {}
    app._consecutive_render_errors = 0
    assert app._handle_render_error(exc) in (True, False)
