"""Claiming a channel for the tachometer role.

`config.tach_channels` filters by enabled_channels -- deliberately, so a tach
role left on a switched-off input does not send the collector hunting for a
pulse train nobody is sampling. The consequence is that claiming a *disabled*
channel does nothing at all, silently, which is exactly what an operator hits
when the channel they want for the tach is one they never enabled for
vibration.
"""


import rev80 as vc
from rev80.gui import apply_tach_claim
from rev80.tach import TachSettings


def _collector(enabled=(0,)):
    cfg = vc.AcquisitionSettings()
    cfg.enabled_channels = list(enabled)
    return vc.DataCollector(config=cfg)


def test_claiming_a_disabled_channel_enables_it():
    """The bug: picking channel 3 for the tach when only 0 is enabled left
    tach_channels empty and the rate simply never appeared."""
    dc = _collector(enabled=(0,))
    apply_tach_claim(dc, 3, None, TachSettings())
    assert 3 in dc.config.enabled_channels
    assert dc.config.tach_channels == [3]
    assert dc.config.vibration_channels == [0]


def test_claiming_an_already_enabled_channel_leaves_it_enabled():
    dc = _collector(enabled=(0, 1))
    implicit = apply_tach_claim(dc, 1, None, TachSettings())
    assert dc.config.tach_channels == [1]
    assert implicit is None, 'it was already on; releasing must not switch it off'


def test_releasing_switches_off_a_channel_it_switched_on():
    """Otherwise the operator is handed an enabled vibration channel they never
    asked for, carrying a pulse train -- overall 1515 mV, kurtosis 15.94."""
    dc = _collector(enabled=(0,))
    implicit = apply_tach_claim(dc, 3, None, TachSettings())
    assert implicit == 3
    apply_tach_claim(dc, None, implicit)
    assert 3 not in dc.config.enabled_channels
    assert dc.config.tach_channels == []


def test_releasing_leaves_a_channel_the_operator_enabled():
    dc = _collector(enabled=(0, 1))
    implicit = apply_tach_claim(dc, 1, None, TachSettings())
    apply_tach_claim(dc, None, implicit)
    assert 1 in dc.config.enabled_channels, 'it was enabled before the claim'
    assert dc.config.role_for(1) == 'vibration'


def test_moving_the_claim_releases_the_previous_channel():
    dc = _collector(enabled=(0,))
    implicit = apply_tach_claim(dc, 2, None, TachSettings())
    implicit = apply_tach_claim(dc, 3, implicit, TachSettings())
    assert dc.config.tach_channels == [3]
    assert 2 not in dc.config.enabled_channels, 'the old implicit enable is undone'
    assert implicit == 3


def test_claim_installs_the_calibration():
    dc = _collector()
    s = TachSettings(threshold_mode='fixed', threshold_mv=1234.0)
    apply_tach_claim(dc, 1, None, s)
    assert dc.tach_settings_for(1) == s


def test_release_clears_the_calibration():
    dc = _collector()
    implicit = apply_tach_claim(dc, 1, None, TachSettings())
    apply_tach_claim(dc, None, implicit)
    assert 1 not in dc.tach_settings


def test_only_one_channel_can_be_the_tachometer():
    dc = _collector(enabled=(0, 1, 2))
    apply_tach_claim(dc, 1, None, TachSettings())
    apply_tach_claim(dc, 2, None, TachSettings())
    assert dc.config.tach_channels == [2]
    assert dc.config.role_for(1) == 'vibration'
