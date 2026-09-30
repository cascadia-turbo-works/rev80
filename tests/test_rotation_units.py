"""Selectable units for shaft speed: RPM, Hz, rad/s and deg/s.

A shaft speed of 30 is a plausible value in RPM, Hz and rad/s, so the unit
is always shown. Stored data is always in RPM.
"""

import math

import pytest

import rev80 as vc
from rev80.util import (DEFAULT_ROTATION_UNIT, ROTATION_UNIT_LABELS,
                        ROTATION_UNITS, rotation_from_rpm, rotation_scale)


def test_the_four_distinct_units():
    """Four units. rad/s is angular frequency omega, and its label says so."""
    assert ROTATION_UNITS == ('RPM', 'Hz', 'rad/s', 'deg/s')
    assert 'omega' in ROTATION_UNIT_LABELS['rad/s'] or 'ω' in ROTATION_UNIT_LABELS['rad/s']


def test_default_is_rpm():
    assert DEFAULT_ROTATION_UNIT == 'RPM'


@pytest.mark.parametrize('unit,expected', [
    ('RPM',   60.0),
    ('Hz',     1.0),
    ('rad/s',  2 * math.pi),
    ('deg/s', 360.0),
])
def test_scale_is_applied_to_shaft_hz(unit, expected):
    assert rotation_scale(unit) == pytest.approx(expected)


@pytest.mark.parametrize('unit,expected', [
    ('RPM',   1800.0),
    ('Hz',      30.0),
    ('rad/s',  188.4955592),
    ('deg/s', 10800.0),
])
def test_conversion_from_rpm(unit, expected):
    assert rotation_from_rpm(1800.0, unit) == pytest.approx(expected)


def test_none_rpm_stays_none():
    """No reading converts to no reading, not to zero."""
    assert rotation_from_rpm(None, 'Hz') is None


def test_unknown_unit_falls_back_to_the_default():
    """A hand-edited config must not be able to invent a scale factor."""
    assert rotation_scale('furlongs/fortnight') == rotation_scale(DEFAULT_ROTATION_UNIT)


def test_setting_round_trips_and_survives_copy():
    cfg = vc.AcquisitionSettings()
    assert cfg.rotation_unit == DEFAULT_ROTATION_UNIT
    cfg.rotation_unit = 'rad/s'
    assert vc.AcquisitionSettings.from_dict(cfg.to_dict()).rotation_unit == 'rad/s'
    assert vc.AcquisitionSettings.copy(cfg).rotation_unit == 'rad/s'


def test_rate_is_stored_in_rpm_regardless_of_display_unit():
    """TachResult.rpm is in RPM for any display unit (41666.5 Hz is a non-nominal test rate)."""
    from rev80 import tach
    import numpy as np
    fs = 41666.5
    t = np.arange(int(fs)) / fs
    x = np.where(np.mod(t, 1 / 30.0) < 200e-6, 5000.0, 0.0)
    r = tach.tach_result(x, fs)
    assert r.rpm == pytest.approx(1800.0, rel=5e-3), 'TachResult.rpm is always RPM'
