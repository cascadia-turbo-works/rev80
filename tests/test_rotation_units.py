"""Selectable rotation-rate units, and the discipline of always labelling them.

A shaft rate shown without its unit is a number waiting to be misread -- 30 is
a plausible RPM, a plausible Hz and a plausible rad/s, and they differ by
factors of 60 and 6.28. The amplitude side of this app already carries its unit
everywhere; the rate side must too.
"""

import math

import pytest

import rev80 as vc
from rev80.util import (DEFAULT_ROTATION_UNIT, ROTATION_UNIT_LABELS,
                        ROTATION_UNITS, rotation_from_rpm, rotation_scale)


def test_the_four_distinct_units():
    """rad/s IS angular frequency omega -- they are one option, not two, and
    the label says so."""
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
    """The unit is a display preference, never a property of stored data. A
    number in the file whose meaning depends on a setting is the class of
    defect this codebase keeps finding.
    """
    from rev80 import tach
    import numpy as np
    fs = 41666.5
    t = np.arange(int(fs)) / fs
    x = np.where(np.mod(t, 1 / 30.0) < 200e-6, 5000.0, 0.0)
    r = tach.tach_result(x, fs)
    assert r.rpm == pytest.approx(1800.0, rel=5e-3), 'TachResult.rpm is always RPM'
