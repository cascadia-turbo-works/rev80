"""A tachometer channel on the Channels card of the main window.

A tachometer channel has no sensor and no engineering unit. The Channels card
shows its rotation unit, not '(none) : mV'. The charts leave it out: see
tests/test_gui_charts.py.
"""

import rev80
from rev80.gui import GUI, apply_tach_claim
from rev80.tach import TachSettings


class _Sensor:
    name = 'Accel 100'
    engineering_units = 'g'


def _app(enabled=(0, 1), tach=0):
    cfg = rev80.AcquisitionSettings()
    cfg.enabled_channels = list(enabled)
    dc = rev80.DataCollector(config=cfg)
    for ch in enabled:
        if ch != tach:
            dc.scope_sensors[ch] = _Sensor()
    if tach is not None:
        apply_tach_claim(dc, tach, None, TachSettings())
    app = GUI.__new__(GUI)
    app.collector = dc
    app._num_channels = 4
    return app


def test_channels_card_shows_a_tachometer_with_its_rotation_unit():
    app = _app()
    assert app._channel_summary_text(0) == 'Tach A : RPM'
    assert app._channel_summary_text(1) == 'Ch B : Accel 100 : g'


def test_channels_card_follows_the_rotation_unit_and_keeps_a_user_name():
    app = _app()
    app.collector.config.rotation_unit = 'Hz'
    app.collector.config.channel_names[0] = 'Motor shaft'
    assert app._channel_summary_text(0) == 'Motor shaft : Hz'
