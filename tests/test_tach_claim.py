"""Claiming a channel for the tachometer role (gui.apply_tach_claim).

`config.tach_channels` filters by enabled_channels, so a tach role on a
switched-off input is not sampled. Therefore a claim enables the channel, and a
release switches off only a channel that the claim switched on.
"""


import rev80 as vc
from rev80.gui import apply_tach_claim
from rev80.tach import TachSettings


def _collector(enabled=(0,)):
    cfg = vc.AcquisitionSettings()
    cfg.enabled_channels = list(enabled)
    return vc.DataCollector(config=cfg)


def test_claiming_a_disabled_channel_enables_it():
    """Claiming disabled channel 3 enables it and makes it the tach channel.

    If it stayed disabled, tach_channels would be empty and no rate would show.
    """
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
    """Releasing a claim switches off the channel that the claim enabled.

    Otherwise a vibration channel carries a pulse train and reads, for example,
    overall 1515 mV and kurtosis 15.94.
    """
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
