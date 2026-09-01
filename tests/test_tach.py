"""Edge-detection mechanics for tachometer channels (rev80.tach).

Scope: the detector itself. Amplitude/timing *accuracy* assertions live in
tests/test_measurement_validity.py, which is off-grid and phase-swept by
construction; this file covers hysteresis, the min-span gate, polarity and
pulses-per-rev being applied exactly once, quality classification, and the
block-boundary cases.

Every synthetic pulse train here is deliberately generated off-grid (a
non-integer number of samples per pulse period) and swept across sub-sample
start phases. An on-grid rate -- e.g. 600 RPM at 1 ppr and 40 kHz, which is
exactly 4000.0 samples per pulse -- is the tachometer's equivalent of a
bin-centred tone: the one case where quantisation error vanishes identically
and a broken detector still passes.
"""

import numpy as np
import pytest

from rev80 import tach

# Real hardware reports 41666.5 Hz, not RAW_SAMPLERATE_HZ (40000). Tests use
# the hardware value so that any implementation reaching for the constant
# instead of the sample's own rate reads 4.166 % high and fails here.
HW_FS = 41666.5
SIM_FS = 40000.0

AMPL_MV = 2000.0   # 2 V swing, a real logic-level tach minimum
OFFSET_MV = 1000.0


def make_pulses(rpm, fs, duration_s=1.0, ppr=1, duty=0.05, amplitude_mv=AMPL_MV,
                offset_mv=OFFSET_MV, phase_s=0.0, noise_mv=0.0, seed=0):
    """A rectangular tach pulse train, offset so it swings 0..amplitude_mv."""
    n = int(round(fs * duration_s))
    t = np.arange(n) / fs
    period = 60.0 / (rpm * ppr)
    frac = np.mod(t - phase_s, period) / period
    x = np.where(frac < duty, amplitude_mv, 0.0) + offset_mv - amplitude_mv / 2.0
    if noise_mv:
        x = x + np.random.default_rng(seed).normal(0.0, noise_mv, n)
    return x


def make_ramped_pulses(rpm, fs, duration_s=1.0, ppr=1, duty=0.5,
                       rise_samples=8, amplitude_mv=AMPL_MV,
                       offset_mv=OFFSET_MV, phase_s=0.0, noise_mv=0.0, seed=0):
    """A pulse train with a finite, linear rise and fall.

    Ideal rectangles are a degenerate test signal for a threshold detector:
    no sample ever lands between the rails, so the hysteresis band is never
    occupied and sub-sample interpolation has nothing to interpolate. Real
    edges reaching this module have already been band-limited by the mandatory
    anti-alias filter, which is what puts samples on the slope.
    """
    n = int(round(fs * duration_s))
    t = np.arange(n) / fs
    period = 60.0 / (rpm * ppr)
    rise_s = rise_samples / fs
    ph = np.mod(t - phase_s, period)
    up = np.clip(ph / rise_s, 0.0, 1.0)
    down = np.clip((ph - duty * period) / rise_s, 0.0, 1.0)
    x = amplitude_mv * (up - down) + offset_mv - amplitude_mv / 2.0
    if noise_mv:
        x = x + np.random.default_rng(seed).normal(0.0, noise_mv, n)
    return x


# --- min-span gate -------------------------------------------------------

def test_noise_only_block_reports_no_signal_not_zero_rpm():
    """A disconnected input must read 'I cannot see a tach', not 'stopped'.

    Without the min-span gate an adaptive threshold finds the noise and counts
    it -- measured at ~9100 edges per block, i.e. 547 752 RPM.
    """
    x = np.random.default_rng(0).normal(0.0, 5.0, int(HW_FS))
    r = tach.tach_result(x, HW_FS, ch=0, rel_time=0.0)
    assert r.rpm is None, 'noise must not produce an RPM reading'
    assert r.quality == 'no_signal'
    assert r.n_edges == 0


@pytest.mark.parametrize('noise_mv', [0.61, 2.0, 5.0, 20.0, 80.0])
def test_min_span_gate_rejects_every_measured_noise_level(noise_mv):
    """Spans measured on a 4424A were <= 42.5 mV; the gate sits at 1000 mV."""
    x = np.random.default_rng(1).normal(0.0, noise_mv, int(HW_FS))
    assert tach.tach_result(x, HW_FS, ch=0, rel_time=0.0).quality == 'no_signal'


def test_min_span_gate_accepts_a_real_logic_level_swing():
    x = make_pulses(1800.0, HW_FS)
    assert tach.tach_result(x, HW_FS, ch=0, rel_time=0.0).quality == 'ok'


# --- polarity and pulses-per-rev applied exactly once --------------------

@pytest.mark.parametrize('rpm', [317.3, 1793.3, 2617.9])
def test_rising_and_falling_polarity_agree_on_rate(rpm):
    """Inverting the pulse and the polarity setting must give the same RPM."""
    x = make_pulses(rpm, HW_FS, duty=0.5)
    rising = tach.tach_result(x, HW_FS, ch=0, rel_time=0.0)
    falling = tach.tach_result(
        -x, HW_FS, ch=0, rel_time=0.0,
        settings=tach.TachSettings(polarity='falling'))
    assert rising.rpm == pytest.approx(rpm, rel=2e-3)
    assert falling.rpm == pytest.approx(rpm, rel=2e-3)


def test_polarity_selects_which_end_of_the_pulse_is_timed():
    """Rate alone cannot pin polarity -- a pulse train has the same period
    whichever end you time. The edge *instants* are what differ: 'rising' marks
    each pulse's leading edge, 'falling' its trailing edge, one duty cycle
    later. Without the inversion both settings return the leading edge and the
    keyphasor's angular reference is silently wrong by the pulse width.
    """
    rpm, duty = 1800.0, 0.25
    period_s = 60.0 / rpm
    # Start the block in the gap between pulses. A block that opens mid-pulse
    # correctly suppresses that pulse's leading edge (it happened in the
    # previous block), which would make the two series start on different
    # pulses and the offset come out negative.
    x = make_pulses(rpm, HW_FS, duty=duty, phase_s=-0.5 * period_s)
    lead = tach.tach_result(x, HW_FS, ch=0, rel_time=0.0)
    trail = tach.tach_result(
        x, HW_FS, ch=0, rel_time=0.0,
        settings=tach.TachSettings(polarity='falling'))
    assert lead.rpm == pytest.approx(trail.rpm, rel=1e-3)
    offset = trail.edge_times_s[0] - lead.edge_times_s[0]
    assert offset == pytest.approx(duty * period_s, rel=0.02), (
        'falling polarity must time the trailing edge, one duty cycle later')


@pytest.mark.parametrize('ppr', [1, 2, 6, 60])
def test_pulses_per_rev_divides_exactly_once(ppr):
    """ppr applied twice, or not at all, shifts the answer by exactly ppr.

    Duty is 0.5 because a multi-line encoder emits a square wave, not a narrow
    spike -- a fixed pulse *width* scaled down by ppr would put the 60-line
    case below one sample and test the acquisition floor instead of the divide.
    """
    shaft_rpm = 600.0
    x = make_pulses(shaft_rpm, HW_FS, ppr=ppr, duty=0.5)
    r = tach.tach_result(x, HW_FS, ch=0, rel_time=0.0,
                         settings=tach.TachSettings(pulses_per_rev=ppr))
    # Tolerance is two samples of slop on one pulse period, because these are
    # ideal rectangles: both samples straddling a crossing sit at the rails, so
    # linear interpolation returns a constant fraction and degenerates to
    # nearest-sample quantisation. Real edges are band-limited by the hardware
    # anti-alias filter, which is what gives interpolation its purchase -- the
    # bench measured 0.026 % at 600 RPM against the ~0.05 % allowed here.
    # Accuracy proper is asserted in tests/test_measurement_validity.py.
    samples_per_pulse = HW_FS / (shaft_rpm * ppr / 60.0)
    assert r.rpm == pytest.approx(shaft_rpm, rel=2.0 / samples_per_pulse)
    assert r.pulses_per_rev == ppr


def test_samplerate_comes_from_the_argument_not_a_module_constant():
    """The 4.166 % trap: hardware reports 41666.5 Hz, the constant says 40000.

    An implementation that reaches for RAW_SAMPLERATE_HZ is exactly right in
    CI and reads 1875 RPM for an 1800 RPM shaft on real hardware.
    """
    x = make_pulses(1800.0, HW_FS)
    assert tach.tach_result(x, HW_FS, ch=0, rel_time=0.0).rpm == pytest.approx(
        1800.0, rel=1e-3)
    x_sim = make_pulses(1800.0, SIM_FS)
    assert tach.tach_result(x_sim, SIM_FS, ch=0, rel_time=0.0).rpm == pytest.approx(
        1800.0, rel=1e-3)


# --- threshold mode and coupling ----------------------------------------

@pytest.mark.parametrize('duty', [0.05, 0.30, 0.50, 0.70, 0.85])
def test_adaptive_threshold_is_invariant_to_duty_and_ac_coupling(duty):
    """Measured on hardware: fixed thresholds fail above ~55 % duty when the
    input is AC-coupled, because AC coupling removes the mean and the mean is
    the duty cycle. Adaptive returned 1801.7 RPM in all ten bench conditions.
    """
    dc = make_pulses(1800.0, HW_FS, duty=duty)
    ac = dc - dc.mean()                      # what AC coupling does to a pulse train
    for x in (dc, ac):
        r = tach.tach_result(x, HW_FS, ch=0, rel_time=0.0)
        assert r.rpm == pytest.approx(1800.0, rel=2e-3)


def test_fixed_threshold_fails_on_ac_coupled_high_duty_signal():
    """The failure the adaptive default exists to prevent -- kept as a test so
    the default is never 'simplified' back to a fixed threshold.
    """
    dc = make_pulses(1800.0, HW_FS, duty=0.85)
    ac = dc - dc.mean()
    fixed = tach.TachSettings(threshold_mode='fixed', threshold_mv=OFFSET_MV)
    assert tach.tach_result(ac, HW_FS, ch=0, rel_time=0.0, settings=fixed).rpm is None
    assert tach.tach_result(dc, HW_FS, ch=0, rel_time=0.0,
                            settings=fixed).rpm == pytest.approx(1800.0, rel=2e-3)


def test_hysteresis_rejects_noise_riding_on_the_threshold():
    """Noise at the switching point must not multiply the edge count.

    The edge has to have a finite rise time for this to bite: on an ideal
    rectangle no sample ever lands near the threshold, so hysteresis is never
    exercised and its removal goes unnoticed. Real edges are band-limited by
    the anti-alias filter upstream, which is what puts samples in the band.
    """
    rpm = 1800.0
    kw = dict(duty=0.5, rise_samples=12)
    clean = tach.tach_result(make_ramped_pulses(rpm, HW_FS, **kw), HW_FS)
    noisy = tach.tach_result(
        make_ramped_pulses(rpm, HW_FS, noise_mv=90.0, seed=3, **kw), HW_FS)
    assert noisy.n_edges == clean.n_edges, (
        'noise on the slope must not add edges')
    assert noisy.rpm == pytest.approx(rpm, rel=5e-3)
    assert noisy.quality == tach.QUALITY_OK


def test_detect_edges_applies_the_min_span_gate_itself():
    """detect_edges is public and is called directly (by estimate_rpm's
    callers and by the GUI's tach waveform view), so it cannot rely on
    tach_result having already checked the span.
    """
    noise = np.random.default_rng(7).normal(0.0, 5.0, int(HW_FS))
    assert tach.detect_edges(noise).size == 0


def test_sub_sample_interpolation_beats_nearest_sample_quantisation():
    """At 60 pulses/rev a period is only ~69 samples, so rounding each edge to
    the nearest sample costs up to 1.4 %. Interpolating the crossing on a
    band-limited edge must do materially better than that.
    """
    rpm, ppr = 600.0, 60
    settings = tach.TachSettings(pulses_per_rev=ppr)
    errs = []
    for phase_frac in np.linspace(0.0, 1.0, 8, endpoint=False):
        x = make_ramped_pulses(rpm, HW_FS, ppr=ppr, duty=0.5, rise_samples=6,
                               phase_s=phase_frac / HW_FS)
        r = tach.tach_result(x, HW_FS, ch=0, rel_time=0.0, settings=settings)
        errs.append(abs(r.rpm - rpm) / rpm)
    assert max(errs) < 3e-3, (
        f'worst relative error {max(errs):.2%} -- interpolation is not working; '
        'nearest-sample quantisation alone would give ~1.4 %')


# --- block boundaries ----------------------------------------------------

def test_block_starting_mid_pulse_does_not_report_a_phantom_edge():
    """A naive loop detector reports an edge at sample 1 whenever a block
    begins already above the threshold. Requiring a real crossing does not.
    """
    x = make_pulses(1800.0, HW_FS, duty=0.5)
    x = np.roll(x, -int(0.25 * HW_FS / 30.0))   # start part-way through a high
    assert x[0] > OFFSET_MV, 'test setup: block must start mid-pulse'
    r = tach.tach_result(x, HW_FS, ch=0, rel_time=0.0)
    assert r.rpm == pytest.approx(1800.0, rel=2e-3)


def test_block_opening_inside_the_hysteresis_band_reports_no_edge_there():
    """An edge requires a *decided low* state before it, not merely 'not high'.

    A block can open with its first samples part-way up a slope, inside the
    hysteresis band, where the detector has no prior state and cannot know
    whether the signal was rising or falling into it. Accepting that as an edge
    invents one at an arbitrary position, which corrupts one interval and can
    trip the 'inconsistent' flag on a perfectly good sensor. Suppressing it
    costs at most one interval out of thirty and corrupts nothing.
    """
    rpm, rise = 1800.0, 60
    rise_s = rise / HW_FS
    x = make_ramped_pulses(rpm, HW_FS, duty=0.5, rise_samples=rise,
                           phase_s=-0.5 * rise_s)
    span = x.max() - x.min()
    mid = (x.max() + x.min()) / 2.0
    assert abs(x[0] - mid) < tach.HYSTERESIS_FRAC * span / 2.0, (
        'test setup: block must open inside the hysteresis band')

    edges = tach.detect_edges(x)
    settled = tach.detect_edges(x[rise:])     # same signal, opening below the band
    assert len(edges) == len(settled), (
        'opening inside the band must not add an edge the settled block lacks')


@pytest.mark.parametrize('phase_frac', np.linspace(0.0, 1.0, 8, endpoint=False))
def test_rate_is_stable_across_sub_sample_start_phases(phase_frac):
    """Sweeping the pulse across one sample interval is what stops an on-grid
    rate from hiding quantisation error.
    """
    x = make_pulses(1793.3, HW_FS, phase_s=phase_frac / HW_FS)
    assert tach.tach_result(x, HW_FS, ch=0, rel_time=0.0).rpm == pytest.approx(
        1793.3, rel=2e-3)


def test_too_few_edges_is_distinct_from_no_signal():
    """A slow shaft in a short block: the signal is there, the rate is not."""
    x = make_pulses(20.0, HW_FS, duration_s=1.0)   # 1 edge in the block
    r = tach.tach_result(x, HW_FS, ch=0, rel_time=0.0)
    assert r.rpm is None
    assert r.quality == 'too_few_edges'
    assert r.span_mv > tach.MIN_PULSE_AMPLITUDE_MV


# --- quality classification ---------------------------------------------

def test_single_miscounted_edge_is_flagged_inconsistent_but_rpm_survives():
    """Median-of-intervals is chosen precisely so one bad edge costs 0.15 RPM
    rather than 62 RPM. The flag says the sensor needs looking at.
    """
    x = make_pulses(1800.0, HW_FS, duty=0.05)
    edges = tach.detect_edges(x)
    dropped = np.delete(edges, len(edges) // 2)
    r = tach.estimate_rpm(dropped, HW_FS, ch=0, rel_time=0.0)
    assert r.quality == 'inconsistent'
    assert r.rpm == pytest.approx(1800.0, rel=5e-3)
    assert r.interval_spread > tach.INTERVAL_SPREAD_MAX


def test_steady_shaft_is_not_flagged_unsteady():
    x = make_pulses(1800.0, HW_FS)
    r = tach.tach_result(x, HW_FS, ch=0, rel_time=0.0)
    assert r.quality == 'ok'
    assert abs(r.speed_drift_pct) < tach.SPEED_DRIFT_MAX_PCT


def test_speed_ramp_across_the_block_is_flagged_unsteady():
    """A spectrum captured while the shaft is accelerating is smeared and must
    be rejected, not corrected -- 2 %/s costs 17 % of peak height and spreads a
    bearing tone over 18 bins.
    """
    fs, dur = HW_FS, 1.0
    n = int(fs * dur)
    t = np.arange(n) / fs
    f0, drift = 30.0, 0.04           # 4 % speed increase across the block
    phase = 2 * np.pi * f0 * (t + drift * t * t / (2 * dur))
    x = np.where(np.mod(phase, 2 * np.pi) < 2 * np.pi * 0.05,
                 AMPL_MV, 0.0) + OFFSET_MV - AMPL_MV / 2.0
    r = tach.tach_result(x, fs, ch=0, rel_time=0.0)
    assert r.quality == 'unsteady'
    assert abs(r.speed_drift_pct) > tach.SPEED_DRIFT_MAX_PCT
    assert r.rpm is not None, 'an unsteady frame still reports its mean rate'


def test_drift_is_reported_signed_so_the_direction_is_recoverable():
    x = make_pulses(1800.0, HW_FS)
    assert tach.tach_result(x, HW_FS, ch=0, rel_time=0.0).speed_drift_pct == (
        pytest.approx(0.0, abs=0.2))


# --- result shape --------------------------------------------------------

def test_result_carries_the_edge_times_that_get_persisted():
    """Edge times, not the waveform, are what reaches HDF5 -- ~1400x smaller
    and still enough to re-derive RPM at a different pulses_per_rev.
    """
    x = make_pulses(1800.0, HW_FS)
    r = tach.tach_result(x, HW_FS, ch=3, rel_time=1.25)
    assert r.channel == 3
    assert r.rel_time == 1.25
    assert r.samplerate == HW_FS
    assert len(r.edge_times_s) == r.n_edges
    assert np.all(np.diff(r.edge_times_s) > 0)
    assert r.edge_times_s[-1] < len(x) / HW_FS


def test_shaft_hz_is_rpm_over_sixty_and_none_when_rpm_is():
    x = make_pulses(1800.0, HW_FS)
    assert tach.tach_result(x, HW_FS, ch=0, rel_time=0.0).shaft_hz == pytest.approx(
        30.0, rel=2e-3)
    noise = np.random.default_rng(0).normal(0.0, 5.0, int(HW_FS))
    assert tach.tach_result(noise, HW_FS, ch=0, rel_time=0.0).shaft_hz is None


def test_settings_round_trip_through_dict():
    s = tach.TachSettings(pulses_per_rev=6, polarity='falling',
                          threshold_mode='fixed', threshold_mv=1234.0)
    assert tach.TachSettings.from_dict(s.to_dict()) == s


def test_settings_from_dict_coerces_types_and_fills_defaults():
    """YAML round-trips give strings; a KeyError here silently erased the whole
    sensor library once already (audit X-01).
    """
    s = tach.TachSettings.from_dict({'pulses_per_rev': '6', 'threshold_mv': '2500'})
    assert s.pulses_per_rev == 6 and isinstance(s.pulses_per_rev, int)
    assert s.threshold_mv == 2500.0 and isinstance(s.threshold_mv, float)
    assert s.polarity == 'rising'
    assert tach.TachSettings.from_dict({}) == tach.TachSettings()


# --- pulses per rev is clamped to 1 by the UI, not by the code (D-6) --------

def test_default_is_one_pulse_per_rev():
    """D-6: the preponderance of installs is one reflective tape or one
    keyway, and 1 ppr is not merely the common case but the accurate one --
    every interval is then exactly one revolution, so once-per-rev division
    error and load-zone speed modulation cancel by construction rather than by
    averaging (measured 0.0013% at 1 ppr vs 0.091% for a 60-line encoder at
    any window length).
    """
    assert tach.TachSettings().pulses_per_rev == 1


def test_three_edges_is_two_whole_revolutions_at_one_ppr():
    """Which is why there is no separate minimum-revolutions gate: MIN_EDGES
    already is one, at the only ppr the UI can produce."""
    assert tach.MIN_EDGES == 3
    x = make_pulses(1800.0, HW_FS, duration_s=3.2 * 60.0 / 1800.0)
    r = tach.tach_result(x, HW_FS, ch=0, rel_time=0.0)
    assert r.quality == tach.QUALITY_OK
    assert r.n_edges >= tach.MIN_EDGES


def test_non_unity_ppr_is_honoured_and_warns(caplog):
    """Never silently clamp to 1. A hand-edited YAML carrying ppr=6 clamped to
    1 would read 6x high with nothing on screen to say so -- the silent-wrong
    -number class this project keeps finding. Honour it, and say it is
    unsupported.
    """
    with caplog.at_level('WARNING'):
        s = tach.TachSettings.from_dict({'pulses_per_rev': 6})
    assert s.pulses_per_rev == 6, 'must not silently clamp'
    assert any('pulses_per_rev' in rec.message for rec in caplog.records)


def test_unity_ppr_does_not_warn(caplog):
    with caplog.at_level('WARNING'):
        s = tach.TachSettings.from_dict({'pulses_per_rev': 1})
    assert s.pulses_per_rev == 1
    assert not [r for r in caplog.records if 'pulses_per_rev' in r.message]


# --- duty cycle (R46 prerequisite) ---------------------------------------

@pytest.mark.parametrize('duty', [0.05, 0.15, 0.30, 0.50, 0.70, 0.85])
def test_duty_cycle_is_measured(duty):
    """Duty is what turns a reflector's physical size into a shaft diameter:
    the reflector subtends `duty` of a revolution, so C = L/duty and the
    surface velocity is f*L/duty (R46).
    """
    x = make_ramped_pulses(1800.0, HW_FS, duty=duty, rise_samples=2)
    r = tach.tach_result(x, HW_FS, ch=0, rel_time=0.0)
    assert r.duty_cycle == pytest.approx(duty, abs=0.02)


def test_duty_is_zero_when_unmeasurable():
    """No complete pulse in the block means no duty, not a fabricated one."""
    noise = np.random.default_rng(0).normal(0.0, 5.0, int(HW_FS))
    assert tach.tach_result(noise, HW_FS).duty_cycle == 0.0


def test_pulse_widths_are_reported_per_pulse():
    x = make_ramped_pulses(1800.0, HW_FS, duty=0.25, rise_samples=2)
    r = tach.tach_result(x, HW_FS)
    period = 60.0 / 1800.0
    assert len(r.pulse_widths_s) >= r.n_edges - 1
    assert np.allclose(r.pulse_widths_s, 0.25 * period, atol=0.02 * period)


def test_duty_measures_the_active_state_under_falling_polarity():
    """A keyphasor idles high and the key is a negative-going notch. The
    'active' state is the notch, so its width is what corresponds to the key.
    """
    duty = 0.2
    x = make_ramped_pulses(1800.0, HW_FS, duty=duty, rise_samples=2)
    inverted = -x
    r = tach.tach_result(inverted, HW_FS,
                         settings=tach.TachSettings(polarity='falling'))
    assert r.duty_cycle == pytest.approx(duty, abs=0.02)


def test_block_opening_mid_pulse_contributes_no_partial_width():
    """A pulse whose opening edge fell in the previous block has no measurable
    width here; counting the truncated remainder would drag duty down."""
    duty = 0.5
    x = make_ramped_pulses(1800.0, HW_FS, duty=duty, rise_samples=2)
    rolled = np.roll(x, -int(0.25 * HW_FS / 30.0))
    r = tach.tach_result(rolled, HW_FS)
    assert r.duty_cycle == pytest.approx(duty, abs=0.02)
