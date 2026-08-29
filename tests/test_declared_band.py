"""The overall must be computed over a declared, configurable band (M-06).

Before this, `overall` was the RMS of the whole filtered block, so its band was
`highpass_fc` … fs/2 -- and fs/2 is 1.28x-2.56x maxfreq depending on where the
power-of-two rounding in `AcquisitionSettings.samplerate` lands (2.048x at the
500/1000/2000 Hz presets).  Meanwhile F-9 had already truncated the *spectrum*
at maxfreq, so the overall and the spectrum on screen described different bands.

Two consequences, both quantified by the audit:

  * Content the user explicitly excluded via F_max still landed in the trend.
    2 g RMS at 1500 Hz outside a 1000 Hz F_max inflated reported overall
    velocity from 3.00 to 3.74 mm/s (+25%) -- enough to move a machine from
    ISO 20816 zone B to zone C on a reading that should have excluded it.
  * Overalls were not comparable across sessions taken at different F_max,
    which silently invalidates long-horizon trending.

Everything here excites the chain off-bin, reusing the helpers in
test_measurement_validity.py for the same reason that file gives.
"""

import numpy as np
import pytest

import rev80 as vc
from rev80 import _dsp

from test_measurement_validity import (
    OFFBIN_FRACTIONS,
    make_collector,
    make_sample,
    rel_err,
    tone,
    true_rms,
)


def offbin(dc, nominal: float, frac: float) -> float:
    """Nudge a nominal frequency off the bin grid by `frac` of a bin."""
    return nominal + frac * dc.config.binsize_actual


# ===========================================================================
# The band is declared, defaulted and persisted
# ===========================================================================

def test_band_defaults_to_highpass_fc_and_maxfreq():
    """Unset band edges resolve to the high-pass corner and F_max.

    Not fs/2: the guard band between F_max and fs/2 is where the anti-alias
    filter has not reached full attenuation, so content there is not a
    measurement and must not reach the overall.
    """
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq = 1000.0
    cfg.highpass_enabled = True
    cfg.highpass_fc = 10.0
    assert cfg.band_fmin is None and cfg.band_fmax is None
    assert cfg.band_fmin_resolved == pytest.approx(10.0)
    assert cfg.band_fmax_resolved == pytest.approx(1000.0)


def test_band_default_upper_edge_is_maxfreq_not_nyquist():
    """The whole point of M-06: fs/2 is up to 2.048x maxfreq at these presets."""
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq = 1000.0
    assert cfg.samplerate / 2 > 2.0 * cfg.maxfreq   # the preset really is that wide
    assert cfg.band_fmax_resolved == pytest.approx(cfg.maxfreq)


def test_band_with_highpass_disabled_starts_at_zero():
    """With no high-pass there is no lower edge to inherit."""
    cfg = vc.AcquisitionSettings()
    cfg.highpass_enabled = False
    cfg.highpass_fc = 10.0
    assert cfg.band_fmin_resolved == pytest.approx(0.0)


def test_explicit_band_overrides_the_defaults():
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq = 5000.0
    cfg.band_fmin = 10.0
    cfg.band_fmax = 1000.0
    assert cfg.band_fmin_resolved == pytest.approx(10.0)
    assert cfg.band_fmax_resolved == pytest.approx(1000.0)


def test_band_upper_edge_is_clamped_to_maxfreq():
    """A stored band wider than the current F_max cannot reintroduce guard band."""
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq = 1000.0
    cfg.band_fmax = 20000.0
    assert cfg.band_fmax_resolved == pytest.approx(1000.0)


def test_iso_20816_band_is_available_as_a_preset():
    assert (10.0, 1000.0) in [tuple(b) for b in vc.ISO_BAND_PRESETS.values()]


def test_band_round_trips_through_config_dict():
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq = 5000.0
    cfg.band_fmin = 10.0
    cfg.band_fmax = 1000.0
    back = vc.AcquisitionSettings.from_dict(cfg.to_dict())
    assert back.band_fmin == pytest.approx(10.0)
    assert back.band_fmax == pytest.approx(1000.0)


def test_unset_band_round_trips_as_unset():
    """None must survive; coercing it to a number would freeze today's F_max in."""
    cfg = vc.AcquisitionSettings()
    back = vc.AcquisitionSettings.from_dict(cfg.to_dict())
    assert back.band_fmin is None
    assert back.band_fmax is None


def test_copy_carries_the_band():
    """AcquisitionSettings.copy() dropped every field but maxfreq/binsize (H-08)."""
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq = 5000.0
    cfg.band_fmin = 10.0
    cfg.band_fmax = 1000.0
    cfg.highpass_fc = 4.0
    c = vc.AcquisitionSettings.copy(cfg)
    assert c.band_fmin == pytest.approx(10.0)
    assert c.band_fmax == pytest.approx(1000.0)
    assert c.highpass_fc == pytest.approx(4.0)


# ===========================================================================
# The band is carried on the result
# ===========================================================================

def test_channel_result_reports_the_band_it_was_measured_over():
    """Without this, a stored overall cannot be compared with any other."""
    dc = make_collector(eu='mm/s2', target_unit='mm/s', maxfreq=1000, binsize=2.0)
    dc.config.band_fmin = 10.0
    dc.config.band_fmax = 500.0
    r = dc.process_sample(0, make_sample(dc, tone(dc, 100.0)))
    assert r.band_fmin == pytest.approx(10.0)
    assert r.band_fmax == pytest.approx(500.0)


# ===========================================================================
# Out-of-band content is excluded -- the audit's quantified +25% case
# ===========================================================================

@pytest.mark.parametrize('frac', OFFBIN_FRACTIONS)
def test_out_of_band_tone_does_not_reach_the_overall(frac):
    """The audit's case: 1500 Hz content outside a 1000 Hz F_max inflated the
    reported velocity overall by +25%, on a reading that should have excluded it.
    """
    dc = make_collector(eu='mm/s2', target_unit='mm/s2', amp_mode='RMS',
                        maxfreq=1000, binsize=2.0)
    f_in  = offbin(dc, 300.0, frac)
    f_out = offbin(dc, 1500.0, frac)          # above F_max, below fs/2
    assert f_out < dc.config.samplerate / 2

    data = tone(dc, f_in, amp=1.0) + tone(dc, f_out, amp=2.0)
    r = dc.process_sample(0, make_sample(dc, data))

    assert abs(rel_err(r.overall, true_rms(1.0, f_in, 0))) < 0.02


@pytest.mark.parametrize('frac', OFFBIN_FRACTIONS)
def test_out_of_band_tone_excluded_from_integrated_overall(frac):
    """Same, through the acc->vel integration path."""
    dc = make_collector(eu='mm/s2', target_unit='mm/s', amp_mode='RMS',
                        maxfreq=1000, binsize=2.0)
    f_in  = offbin(dc, 300.0, frac)
    f_out = offbin(dc, 1500.0, frac)
    data = tone(dc, f_in, amp=1.0) + tone(dc, f_out, amp=2.0)
    r = dc.process_sample(0, make_sample(dc, data))
    assert abs(rel_err(r.overall, true_rms(1.0, f_in, 1))) < 0.03


@pytest.mark.parametrize('frac', OFFBIN_FRACTIONS)
def test_below_band_tone_does_not_reach_the_overall(frac):
    """The lower edge must exclude too -- sub-synchronous content and drift."""
    dc = make_collector(eu='mm/s2', target_unit='mm/s2', amp_mode='RMS',
                        maxfreq=1000, binsize=2.0)
    dc.config.band_fmin = 100.0
    f_in  = offbin(dc, 300.0, frac)
    f_low = offbin(dc, 30.0, frac)
    data = tone(dc, f_in, amp=1.0) + tone(dc, f_low, amp=3.0)
    r = dc.process_sample(0, make_sample(dc, data))
    assert abs(rel_err(r.overall, true_rms(1.0, f_in, 0))) < 0.02


# ===========================================================================
# The band, not the preset, decides the number -- what makes trending valid
# ===========================================================================

@pytest.mark.parametrize('maxfreq', [1000.0, 2000.0, 5000.0])
def test_overall_is_invariant_to_maxfreq_at_a_fixed_band(maxfreq):
    """A trend must stay comparable when the operator changes F_max.

    Same signal, same declared band, three presets: the reported overall must
    agree. Before this it moved with fs/2, so long-horizon trending across a
    settings change was silently invalid.
    """
    dc = make_collector(eu='mm/s2', target_unit='mm/s2', amp_mode='RMS',
                        maxfreq=maxfreq, binsize=2.0)
    dc.config.band_fmin = 10.0
    dc.config.band_fmax = 800.0
    data = tone(dc, 317.3, amp=1.0) + tone(dc, 123.7, amp=0.5)
    r = dc.process_sample(0, make_sample(dc, data))
    expected = np.sqrt(true_rms(1.0, 317.3, 0) ** 2 + true_rms(0.5, 123.7, 0) ** 2)
    assert abs(rel_err(r.overall, expected)) < 0.02


@pytest.mark.parametrize('frac', OFFBIN_FRACTIONS)
def test_in_band_passthrough_overall_still_exact(frac):
    """Band-limiting must not cost the exactness the passthrough path had.

    Order 0 moved from a time-domain sqrt(mean(x^2)) to a masked rFFT under
    Parseval; over a band containing all the signal the two must agree.
    """
    dc = make_collector(eu='mm/s2', target_unit='mm/s2', amp_mode='RMS',
                        maxfreq=1000, binsize=2.0)
    f = offbin(dc, 300.0, frac)
    r = dc.process_sample(0, make_sample(dc, tone(dc, f, amp=1.0)))
    assert abs(rel_err(r.overall, true_rms(1.0, f, 0))) < 0.005


def test_all_integration_orders_share_one_band():
    """Every order must exclude the same content, or the five disagree.

    An out-of-band tone is added; each order's overall must match what the
    in-band tone alone predicts, at that order.
    """
    for target, n_int in (('mm/s2', 0), ('mm/s', 1), ('mm', 2)):
        dc = make_collector(eu='mm/s2', target_unit=target, amp_mode='RMS',
                            maxfreq=1000, binsize=2.0)
        f_in, f_out = 317.3, 1517.3
        data = tone(dc, f_in, amp=1.0) + tone(dc, f_out, amp=2.0)
        r = dc.process_sample(0, make_sample(dc, data))
        err = abs(rel_err(r.overall, true_rms(1.0, f_in, n_int)))
        assert err < 0.03, f'{target}: {err:+.2%}'


def test_waveform_and_overall_describe_the_same_band():
    """The displayed trace must not contain content the overall excluded."""
    dc = make_collector(eu='mm/s2', target_unit='mm/s2', amp_mode='0-P',
                        maxfreq=1000, binsize=2.0)
    f_in, f_out = 317.3, 1517.3
    data = tone(dc, f_in, amp=1.0) + tone(dc, f_out, amp=2.0)
    r = dc.process_sample(0, make_sample(dc, data))
    # The out-of-band tone is twice the in-band one; if it survived into the
    # trace the peak would be ~3.0 rather than ~1.0.
    assert np.abs(r.time_data).max() < 1.35


# ===========================================================================
# The PSD cache must not outlive a band change (the M-09 failure mode)
# ===========================================================================

def test_changing_the_band_invalidates_the_cached_overall():
    """M-09 was exactly this bug for binsize: a stale cache under a new setting."""
    dc = make_collector(eu='mm/s2', target_unit='mm/s2', amp_mode='RMS',
                        maxfreq=1000, binsize=2.0)
    data = tone(dc, 317.3, amp=1.0) + tone(dc, 717.3, amp=1.0)
    sample = make_sample(dc, data)

    dc.config.band_fmax = 1000.0
    wide = dc.process_sample(0, sample).overall
    dc.config.band_fmax = 500.0
    narrow = dc.process_sample(0, sample).overall

    assert narrow < 0.8 * wide, (
        f'narrowing the band left the overall unchanged ({wide:.6g} -> '
        f'{narrow:.6g}) -- the cache key is missing the band'
    )


# ===========================================================================
# High-pass: highpass_fc is the start of attenuation, not the -3 dB knee
# ===========================================================================

def test_highpass_knee_sits_below_the_declared_edge():
    """A 4th-order Butterworth designed AT 10 Hz is -3 dB at 10 Hz, inside the
    band ISO 2954 requires flat. The knee must be placed below the edge."""
    dc = make_collector(highpass_enabled=True, highpass_fc=10.0,
                        maxfreq=1000, binsize=2.0)
    knee = dc.highpass_knee_hz(dc.config.samplerate)
    assert knee < 10.0
    assert knee == pytest.approx(10.0 * 0.8342, rel=1e-3)


@pytest.mark.parametrize('fc', [2.0, 5.0, 10.0, 20.0])
def test_highpass_response_at_the_declared_edge_is_within_tolerance(fc):
    """+/-10% amplitude (ISO 2954) at the declared edge, not -3 dB."""
    import scipy.signal

    dc = make_collector(highpass_enabled=True, highpass_fc=fc,
                        maxfreq=1000, binsize=2.0)
    fs = dc.config.samplerate
    sos = dc._highpass_sos(fs)
    w, h = scipy.signal.sosfreqz(sos, worN=[fc], fs=fs)
    mag = float(np.abs(h[0]))
    assert 0.9 <= mag <= 1.0, f'{fc} Hz edge magnitude {mag:.4f}'
    assert mag == pytest.approx(0.9, abs=0.01)


def test_highpass_still_rejects_well_below_the_edge():
    """Moving the knee down must not turn the high-pass into a pass-through."""
    import scipy.signal

    dc = make_collector(highpass_enabled=True, highpass_fc=10.0,
                        maxfreq=1000, binsize=2.0)
    fs = dc.config.samplerate
    sos = dc._highpass_sos(fs)
    _, h = scipy.signal.sosfreqz(sos, worN=[1.0], fs=fs)
    assert float(np.abs(h[0])) < 0.01


# ===========================================================================
# M-12 -- anti-alias stopband against an absolute dB spec
# ===========================================================================

def test_antialias_stopband_meets_80_db():
    """scipy decimate(ftype='fir') uses a Hamming kernel with ~-53 dB sidelobes;
    measured -55.5 dB worst case. ISO 2954 and analyzer practice want >= 80 dB.

    Sweeps tones across the stopband and checks how much of each survives
    decimation, measured at the frequency it folds to.
    """
    from rev80.picoscope import antialias_decimate

    fs_raw, factor = 32768.0, 4
    fs_out = fs_raw / factor
    n = 1 << 15
    t = np.arange(n) / fs_raw

    worst_db = 0.0
    worst_f = None
    # Stopband: above the decimated Nyquist, up to the raw Nyquist.
    for f in np.linspace(0.62 * fs_out, 0.5 * fs_raw, 40):
        x = np.sin(2 * np.pi * f * t + 0.7).reshape(-1, 1)
        y = antialias_decimate(x, factor)[:, 0]
        # Ignore filter start-up at both ends.
        edge = len(y) // 8
        resid = np.sqrt(np.mean(y[edge:-edge] ** 2)) / (1 / np.sqrt(2))
        db = 20 * np.log10(max(resid, 1e-12))
        if db > worst_db or worst_f is None:
            worst_db, worst_f = db, f

    assert worst_db <= -80.0, (
        f'worst stopband rejection {worst_db:.1f} dB at {worst_f:.1f} Hz'
    )


def test_antialias_passband_is_not_attenuated():
    """The steeper kernel must not eat the top of the usable band."""
    from rev80.picoscope import antialias_decimate

    fs_raw, factor = 32768.0, 4
    fs_out = fs_raw / factor
    n = 1 << 15
    t = np.arange(n) / fs_raw

    for f in (0.05 * fs_out, 0.2 * fs_out, 0.39 * fs_out):
        x = np.sin(2 * np.pi * f * t + 0.7).reshape(-1, 1)
        y = antialias_decimate(x, factor)[:, 0]
        edge = len(y) // 8
        amp = np.sqrt(np.mean(y[edge:-edge] ** 2)) * np.sqrt(2)
        assert abs(amp - 1.0) < 0.02, f'{f:.1f} Hz passband amplitude {amp:.4f}'
