"""Edge-detection mechanics for tachometer channels (rev80.tach).

Covers hysteresis, the min-span gate, polarity, pulses per revolution applied
exactly once, quality classification, block boundaries and duty cycle.

Each synthetic pulse train is off-grid (a non-integer number of samples per
pulse) and swept across sub-sample start phases. An on-grid rate is the
tachometer's version of a bin-centred tone: quantisation error vanishes and a
broken detector still passes.
"""

import numpy as np
import pytest

from rev80 import tach

# Two rates that are not RAW_SAMPLERATE_HZ (25600 Hz). An implementation that
# reads the module constant instead of the sample's own rate gives the wrong
# RPM here and fails. (41666.5 Hz is the achieved rate of an earlier raw rate.)
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
    """A noise-only block reads 'no_signal' with rpm None, not 0 RPM.

    Without the min-span gate, an adaptive threshold counts the noise: about
    9100 edges per block, which is 547752 RPM.
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
    """'rising' times the leading edge; 'falling' times the trailing edge.

    The rate is the same for both, so the test compares edge instants: the
    trailing edge is one duty cycle later. If both gave the leading edge, the
    keyphasor angle would be wrong by the pulse width.
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
    # Tolerance is two samples on one pulse period. On ideal rectangles both
    # samples at a crossing sit at the rails, so interpolation becomes
    # nearest-sample quantisation. Real edges are band-limited by the
    # anti-alias filter; AWG loopback measured 0.026 % at 600 RPM and 1 ppr,
    # against about 0.05 % allowed here (CONTRIBUTING.md, "E14.2. Accuracy").
    samples_per_pulse = HW_FS / (shaft_rpm * ppr / 60.0)
    assert r.rpm == pytest.approx(shaft_rpm, rel=2.0 / samples_per_pulse)
    assert r.pulses_per_rev == ppr


def test_samplerate_comes_from_the_argument_not_a_module_constant():
    """tach_result() uses its samplerate argument, not RAW_SAMPLERATE_HZ.

    Neither HW_FS nor SIM_FS is the 25600 Hz constant. The achieved hardware
    rate is not the nominal rate either.
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
    """The adaptive threshold reads the same rate at any duty, DC or AC coupled.

    AC coupling removes the mean, and on a pulse train the mean is the duty
    cycle. On the bench, a fixed threshold failed above about 55 % duty; the
    adaptive threshold read 1801.7 RPM in all ten conditions.
    """
    dc = make_pulses(1800.0, HW_FS, duty=duty)
    ac = dc - dc.mean()                      # what AC coupling does to a pulse train
    for x in (dc, ac):
        r = tach.tach_result(x, HW_FS, ch=0, rel_time=0.0)
        assert r.rpm == pytest.approx(1800.0, rel=2e-3)


def test_fixed_threshold_fails_on_ac_coupled_high_duty_signal():
    """A fixed threshold reads no rate on an AC-coupled 85 % duty signal.

    This is the case that makes the adaptive threshold the default.
    """
    dc = make_pulses(1800.0, HW_FS, duty=0.85)
    ac = dc - dc.mean()
    fixed = tach.TachSettings(threshold_mode='fixed', threshold_mv=OFFSET_MV)
    assert tach.tach_result(ac, HW_FS, ch=0, rel_time=0.0, settings=fixed).rpm is None
    assert tach.tach_result(dc, HW_FS, ch=0, rel_time=0.0,
                            settings=fixed).rpm == pytest.approx(1800.0, rel=2e-3)


def test_hysteresis_rejects_noise_riding_on_the_threshold():
    """Noise on the edge slope does not add edges.

    The edges have a finite rise, so samples land near the threshold. On an
    ideal rectangle, hysteresis is never used and its removal is not detected.
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
    """detect_edges() applies the min-span gate itself.

    It is public and callers such as the GUI tach waveform view call it
    directly, not through tach_result().
    """
    noise = np.random.default_rng(7).normal(0.0, 5.0, int(HW_FS))
    assert tach.detect_edges(noise).size == 0


def test_sub_sample_interpolation_beats_nearest_sample_quantisation():
    """Sub-sample interpolation keeps the error below 0.3 % at 60 ppr.

    At HW_FS and 600 RPM, a pulse period is about 69 samples, so rounding each
    edge to the nearest sample costs up to 1.4 %.
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
    """A block that starts above the threshold has no edge at sample 1.

    An edge needs a real crossing.
    """
    x = make_pulses(1800.0, HW_FS, duty=0.5)
    x = np.roll(x, -int(0.25 * HW_FS / 30.0))   # start part-way through a high
    assert x[0] > OFFSET_MV, 'test setup: block must start mid-pulse'
    r = tach.tach_result(x, HW_FS, ch=0, rel_time=0.0)
    assert r.rpm == pytest.approx(1800.0, rel=2e-3)


def test_block_opening_inside_the_hysteresis_band_reports_no_edge_there():
    """An edge needs a decided low state before it, not only 'not high'.

    A block can open inside the hysteresis band, where the detector cannot tell
    a rising from a falling signal. An edge there would be at an arbitrary
    position and could set 'inconsistent' on a good sensor. Suppressing it
    costs at most one interval in thirty.
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
    """The rate is stable across sub-sample start phases.

    The phase sweep stops an on-grid rate from hiding quantisation error.
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
    """One missing edge sets 'inconsistent', but the median keeps the rate.

    With the median of intervals, one bad edge costs 0.15 RPM, not 62 RPM.
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
    """A 4 % speed ramp across the block sets 'unsteady'; rpm is still given.

    A spectrum taken during acceleration is smeared: 2 %/s costs 17 % of peak
    height and spreads a bearing tone over 18 bins.
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
    """The result carries the edge times that are written to HDF5.

    A tachometer channel stores edge times, not the waveform. They are enough
    to re-derive RPM at a different pulses_per_rev.
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
    """from_dict() coerces YAML strings and fills missing keys with defaults.

    A KeyError from a config loader must not become a lost configuration.
    """
    s = tach.TachSettings.from_dict({'pulses_per_rev': '6', 'threshold_mv': '2500'})
    assert s.pulses_per_rev == 6 and isinstance(s.pulses_per_rev, int)
    assert s.threshold_mv == 2500.0 and isinstance(s.threshold_mv, float)
    assert s.polarity == 'rising'
    assert tach.TachSettings.from_dict({}) == tach.TachSettings()


# --- pulses per rev, and the minimum-revolutions gate ----------------------

def test_default_is_one_pulse_per_rev():
    """One pulse per revolution is the default and the recommended configuration.

    At 1 ppr every interval is one revolution, so division error and
    once-per-rev speed modulation cancel: 0.0013 % at 1 ppr against 0.091 % for
    a 60-line encoder. Evidence: CONTRIBUTING.md, "E14.4. One pulse per
    revolution and `MIN_REVS`".
    """
    assert tach.TachSettings().pulses_per_rev == 1


def test_three_edges_is_two_whole_revolutions_at_one_ppr():
    """At 1 ppr, MIN_REVS = 2.0 needs three edges: two intervals, two turns."""
    assert tach.MIN_REVS == 2.0
    assert tach.min_edges_for(1) == 3
    x = make_pulses(1800.0, HW_FS, duration_s=3.2 * 60.0 / 1800.0)
    r = tach.tach_result(x, HW_FS, ch=0, rel_time=0.0)
    assert r.quality == tach.QUALITY_OK
    assert r.n_edges >= tach.min_edges_for(1)


@pytest.mark.parametrize('ppr, edges', [(1, 3), (2, 5), (6, 13), (60, 121)])
def test_min_edges_scales_with_pulses_per_rev(ppr, edges):
    """min_edges_for(ppr) spans MIN_REVS whole revolutions at any ppr.

    Three edges of a 60-line encoder are 0.033 of a revolution: 0.580 % mean
    and 1.898 % worst error, against 0.091 % from one full turn.
    """
    assert tach.min_edges_for(ppr) == edges


def test_high_ppr_block_holding_min_revs_reads_correctly():
    ppr = 6
    rpm = 1800.0
    # 3 turns, more than MIN_REVS, so the gate is not under test.
    x = make_ramped_pulses(rpm, HW_FS, ppr=ppr, duty=0.3, rise_samples=2,
                           duration_s=3.0 * 60.0 / rpm)
    r = tach.tach_result(x, HW_FS, settings=tach.TachSettings(pulses_per_rev=ppr))
    assert r.quality == tach.QUALITY_OK
    assert r.rpm == pytest.approx(rpm, rel=0.01)
    assert r.n_edges >= tach.min_edges_for(ppr)


def test_high_ppr_block_under_min_revs_reports_no_reading():
    """A 6 ppr block with fewer than MIN_REVS turns gives no rpm.

    The block holds 9.4 pulse periods, about 1.6 revolutions (10 edges).
    Once-per-rev modulation and division error do not cancel in part of a turn.
    The quality is 'too_few_edges', not 'no_signal': the pulse train is good,
    the block is short.
    """
    ppr = 6
    rpm = 1800.0
    pulse_period = 60.0 / (rpm * ppr)
    x = make_ramped_pulses(rpm, HW_FS, ppr=ppr, duty=0.3, rise_samples=2,
                           duration_s=9.4 * pulse_period)
    s = tach.TachSettings(pulses_per_rev=ppr)
    r = tach.tach_result(x, HW_FS, settings=s)
    assert 3 <= r.n_edges < tach.min_edges_for(ppr), (
        'the block must hold more than the old fixed MIN_EDGES = 3, or this '
        'test does not discriminate')
    assert r.rpm is None
    assert r.quality == tach.QUALITY_TOO_FEW_EDGES


def test_slowest_measurable_shaft_matches_the_documented_table():
    """slowest_rpm_for() at 1 ppr is 180 / T_block RPM, as in its docstring table.

    The block must span whole pulse periods, not intervals, because the start
    phase is arbitrary.
    """
    for t_block, floor in ((4.0, 45.0), (2.0, 90.0), (1.0, 180.0),
                           (0.5, 360.0), (0.2, 900.0), (0.1, 1800.0)):
        assert tach.slowest_rpm_for(t_block, 1) == pytest.approx(floor)


def test_more_pulses_per_rev_barely_lowers_the_speed_floor():
    """More pulses per revolution lower the speed floor by less than 1.5x, not ppr x.

    The gate is MIN_REVS whole revolutions at any ppr, so the floor is at least
    MIN_REVS * 60 / T_block = 120 RPM at a 1 s block. More pulses recover only
    the one-pulse-period phase margin:

        ppr      floor @ T=1 s
          1        180 RPM
          2        150 RPM
          6        130 RPM
         60        121 RPM
          inf      120 RPM   (the MIN_REVS bound)

    To read a slower shaft, use a longer block (a smaller binsize).
    """
    bound = tach.MIN_REVS * 60.0 / 1.0
    floors = [tach.slowest_rpm_for(1.0, ppr) for ppr in (1, 2, 6, 60)]

    assert floors == sorted(floors, reverse=True), 'must not increase with ppr'
    assert all(f >= bound for f in floors), 'MIN_REVS is the hard bound'
    assert floors[0] / floors[-1] < 1.5, 'the whole gain is one pulse period'
    assert floors[-1] == pytest.approx(bound, rel=0.02), (
        'at 60 ppr the phase-safety period is negligible and the floor is the '
        'MIN_REVS bound itself')


def test_non_unity_ppr_is_honoured_without_warning(caplog):
    """Loading pulses_per_rev = 6 logs no warning.

    ppr is a supported setting. The accuracy caution is in the front ends,
    which know the sample rate.
    """
    with caplog.at_level('WARNING'):
        s = tach.TachSettings.from_dict({'pulses_per_rev': 6})
    assert s.pulses_per_rev == 6, 'must not silently clamp'
    assert not [r for r in caplog.records if 'pulses_per_rev' in r.message]


def test_unity_ppr_does_not_warn(caplog):
    with caplog.at_level('WARNING'):
        s = tach.TachSettings.from_dict({'pulses_per_rev': 1})
    assert s.pulses_per_rev == 1
    assert not [r for r in caplog.records if 'pulses_per_rev' in r.message]


@pytest.mark.parametrize('bad', [0, -6, 0.5])
def test_unusable_ppr_falls_back_to_one_and_says_so(bad, caplog):
    """A ppr that is zero, negative or fractional falls back to 1 with a warning.

    The fallback changes the reported speed, so it is logged.
    """
    with caplog.at_level('WARNING'):
        s = tach.TachSettings.from_dict({'pulses_per_rev': bad})
    assert s.pulses_per_rev == 1
    assert any('pulses_per_rev' in rec.message for rec in caplog.records)


# --- duty cycle ----------------------------------------------------------

@pytest.mark.parametrize('duty', [0.05, 0.15, 0.30, 0.50, 0.70, 0.85])
def test_duty_cycle_is_measured(duty):
    """duty_cycle is measured to within 0.02 at 5 % to 85 % duty.

    Surface velocity from reflector size (f*L/duty) is tracked as R46 in
    doc/PROGRESS.md.
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
    """A pulse whose opening edge was in the previous block adds no width.

    Its truncated remainder would pull the duty cycle down.
    """
    duty = 0.5
    x = make_ramped_pulses(1800.0, HW_FS, duty=duty, rise_samples=2)
    rolled = np.roll(x, -int(0.25 * HW_FS / 30.0))
    r = tach.tach_result(rolled, HW_FS)
    assert r.duty_cycle == pytest.approx(duty, abs=0.02)
