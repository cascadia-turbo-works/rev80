"""Measurement-validity regression tests (branch: fix/measurement-validity).

These tests exist because the pre-existing DSP suite passed completely while
the instrument was measurably wrong.  Every amplitude test in
``tests/test_sample.py`` excites the chain only at *bin-centred* frequencies
(F_max=10000, binsize=2 → df exactly 2.000 Hz, tones at 500, 1000, 1500 …),
which is the single degenerate case where the block is genuinely periodic in
N samples, the FFT's circular-wrap discontinuity vanishes, and the
integration error is identically zero.

Everything here therefore excites the chain **off-bin**, with the high-pass
filter enabled, across block boundaries, and at every preset — the conditions
a real machine actually produces.

Defect IDs (F-1 … F-9) refer to the vibration-engineering audit; see
BRANCH-NOTES.md for root causes and measured before/after numbers.
"""

from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest

import rev80 as vc
from rev80.scope_sensor import ScopeSensor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_collector(eu: str = 'mm/s2', target_unit: str = 'mm/s',
                   amp_mode: str = 'RMS', maxfreq: float = 10000,
                   binsize: float = 2.0, highpass_enabled: bool = False,
                   highpass_fc: float = 10.0, sensitivity: float = 1.0):
    """A DataCollector wired to a unit-sensitivity sensor, with no hardware."""
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq = maxfreq
    cfg.binsize = binsize
    cfg.highpass_enabled = highpass_enabled
    cfg.highpass_fc = highpass_fc
    cfg.channel_target_units[0] = target_unit
    cfg.channel_amplitude_modes[0] = amp_mode
    dc = vc.DataCollector(None, cfg)
    dc.set_scope_sensor(0, ScopeSensor(name='test', engineering_units=eu,
                                       sensitivity=sensitivity))
    return dc


def make_sample(dc, data: np.ndarray, overflow: bool = False,
                degraded: bool = False, rel_time: float = 0.0,
                timestamp: datetime | None = None) -> vc.VibeSample:
    """Wrap a raw mV array in a VibeSample at the collector's sample rate."""
    return vc.VibeSample(
        status='OVERFLOW' if overflow else 'OKAY',
        _timestamp=timestamp or datetime.now(),
        samplerate=dc.config.samplerate,
        unit='mV',
        overflow=overflow,
        degraded=degraded,
        data=np.ascontiguousarray(data, dtype=np.float64),
        rel_time=rel_time,
    )


# Default starting phase for generated tones. Deliberately NOT 0.
#
# sin(0) == 0 makes x[0] equal the signal's DC level, which is a degenerate
# case in exactly the same way bin-centred frequencies are: it happens to be
# the one starting condition for which a high-pass seeded from x[0] behaves
# correctly. Real captures do not oblige -- measured on four consecutive
# PicoScope blocks of a 447.3 Hz loopback tone, x[0] ranged over 36..305 mV
# while the true block mean was -0.06..-0.21 mV. An earlier version of these
# tests used phase 0 throughout and passed against a seeding bug that made the
# first block of every stream read +4297% high in displacement.
DEFAULT_PHASE = 0.7


def tone(dc, freq: float, amp: float = 1.0, offset: float = 0.0,
         n: int | None = None, start_sample: int = 0,
         phase: float = DEFAULT_PHASE) -> np.ndarray:
    """A pure sine of `amp` (0-peak) at `freq`, sampled at the collector rate.

    `phase` (radians) shifts the start of the record. Amplitude, RMS and the
    analytic integration results are all phase-independent, so every assertion
    here holds for any phase -- which is precisely why the tests must not all
    share the one phase that is arithmetically convenient.
    """
    fs = dc.config.samplerate
    n = n if n is not None else dc.config.blocksize
    t = (np.arange(n) + start_sample) / fs
    return amp * np.sin(2 * np.pi * freq * t + phase) + offset


def true_rms(amp: float, freq: float, n_integrations: int) -> float:
    """Analytic RMS of a sine after `n_integrations` integrations.

    A sine of 0-peak amplitude A at f0 has RMS A/sqrt(2); each integration
    divides the amplitude by (2*pi*f0).
    """
    return (amp / np.sqrt(2)) / (2 * np.pi * freq) ** n_integrations


def rel_err(actual: float, expected: float) -> float:
    return (actual - expected) / expected


def as_streaming(dc):
    """Make dc.is_streaming report True without any hardware."""
    dc.sensor = SimpleNamespace(name='fake')
    dc.stream = SimpleNamespace(active=True)
    return dc


# Fractional bin offsets.  0.0 is the degenerate on-bin case the old suite
# used exclusively; the rest are what a real machine produces.
OFFBIN_FRACTIONS = [0.37, 0.5, 0.13, 0.71]


# ===========================================================================
# F-1 — FFT wrap leakage corrupts every integrated overall and waveform
# ===========================================================================

@pytest.mark.parametrize('frac', OFFBIN_FRACTIONS)
def test_f1_offbin_velocity_overall(frac):
    """Off-bin tone, acc→vel: result.overall must match the analytic RMS.

    The old suite only ever asserted this at exact bin centres.
    """
    dc = make_collector(eu='mm/s2', target_unit='mm/s')
    df = dc.config.samplerate / dc.config.blocksize
    freq = 61 * df + frac * df          # deliberately not a bin centre
    amp = 1.0

    result = dc.process_sample(0, make_sample(dc, tone(dc, freq, amp)))
    assert result is not None

    expected = true_rms(amp, freq, 1)
    err = rel_err(result.overall, expected)
    assert abs(err) < 0.02, (
        f'velocity overall at {freq:.3f} Hz ({frac} bins off-centre): '
        f'expected {expected:.6e}, got {result.overall:.6e} ({err:+.2%})'
    )


@pytest.mark.parametrize('frac', OFFBIN_FRACTIONS)
def test_f1_offbin_displacement_overall(frac):
    """Off-bin tone, acc→disp: double integration amplifies wrap leakage by 1/w^2."""
    dc = make_collector(eu='mm/s2', target_unit='mm')
    df = dc.config.samplerate / dc.config.blocksize
    freq = 61 * df + frac * df
    amp = 1.0

    result = dc.process_sample(0, make_sample(dc, tone(dc, freq, amp)))
    assert result is not None

    expected = true_rms(amp, freq, 2)
    err = rel_err(result.overall, expected)
    assert abs(err) < 0.02, (
        f'displacement overall at {freq:.3f} Hz: expected {expected:.6e}, '
        f'got {result.overall:.6e} ({err:+.2%})'
    )


@pytest.mark.parametrize('freq_hz', [61.0, 120.7, 501.0])
def test_f1_offbin_displacement_overall_absolute(freq_hz):
    """The exact frequencies the audit reproduced numerically."""
    dc = make_collector(eu='mm/s2', target_unit='mm')
    result = dc.process_sample(0, make_sample(dc, tone(dc, freq_hz, 1.0)))
    assert result is not None
    expected = true_rms(1.0, freq_hz, 2)
    err = rel_err(result.overall, expected)
    assert abs(err) < 0.02, (
        f'{freq_hz} Hz displacement overall: expected {expected:.6e}, '
        f'got {result.overall:.6e} ({err:+.2%})'
    )


@pytest.mark.parametrize('frac', [0.37, 0.5])
def test_f1_offbin_velocity_waveform(frac):
    """result.time_data (the displayed trace) must not carry a leakage ramp.

    The peak of the integrated waveform must match the analytic 0-peak
    velocity amplitude.
    """
    dc = make_collector(eu='mm/s2', target_unit='mm/s')
    df = dc.config.samplerate / dc.config.blocksize
    freq = 61 * df + frac * df
    amp = 1.0

    result = dc.process_sample(0, make_sample(dc, tone(dc, freq, amp)))
    assert result is not None
    assert len(result.time_data) == len(result.time_vec), \
        'time_data and time_vec must stay the same length'

    expected_peak = amp / (2 * np.pi * freq)
    actual_peak = float(np.max(np.abs(result.time_data)))
    err = rel_err(actual_peak, expected_peak)
    assert abs(err) < 0.05, (
        f'velocity waveform peak at {freq:.3f} Hz: expected {expected_peak:.6e}, '
        f'got {actual_peak:.6e} ({err:+.2%})'
    )


@pytest.mark.parametrize('frac', [0.37, 0.5])
def test_f1_offbin_displacement_waveform(frac):
    """Displacement trace — 1/w^2 makes the leakage ramp dominate the display."""
    dc = make_collector(eu='mm/s2', target_unit='mm')
    df = dc.config.samplerate / dc.config.blocksize
    freq = 61 * df + frac * df
    amp = 1.0

    result = dc.process_sample(0, make_sample(dc, tone(dc, freq, amp)))
    assert result is not None
    assert len(result.time_data) == len(result.time_vec)

    expected_peak = amp / (2 * np.pi * freq) ** 2
    actual_peak = float(np.max(np.abs(result.time_data)))
    err = rel_err(actual_peak, expected_peak)
    assert abs(err) < 0.05, (
        f'displacement waveform peak at {freq:.3f} Hz: expected {expected_peak:.6e}, '
        f'got {actual_peak:.6e} ({err:+.2%})'
    )


def test_f1_onbin_still_exact():
    """Regression guard: the on-bin case the old suite covered must stay exact."""
    dc = make_collector(eu='mm/s2', target_unit='mm')
    result = dc.process_sample(0, make_sample(dc, tone(dc, 500.0, 1.0)))
    assert result is not None
    expected = true_rms(1.0, 500.0, 2)
    assert abs(rel_err(result.overall, expected)) < 0.02


def test_f1_passthrough_overall_unchanged():
    """n_steps == 0 needs no taper — the overall must be the record's exact RMS.

    Compared against the RMS of the actual samples rather than A/sqrt(2): an
    off-bin tone spans a non-integer number of cycles, so the record's true
    RMS differs from A/sqrt(2) by ~0.06% for physical reasons that are not a
    defect.  The passthrough path must reproduce it exactly.
    """
    dc = make_collector(eu='mm/s2', target_unit='mm/s2')
    data = tone(dc, 120.7, 1.0)
    result = dc.process_sample(0, make_sample(dc, data))
    assert result is not None
    exact = float(np.sqrt(np.mean(data ** 2)))
    assert abs(rel_err(result.overall, exact)) < 1e-9


@pytest.mark.parametrize('frac', [0.37, 0.5])
def test_f1_offbin_with_highpass_enabled(frac):
    """Same off-bin integration, but through the high-pass path.

    `_make_dc` in test_sample.py defaults highpass_enabled=False, so the
    filtered path was never exercised by any amplitude assertion.
    """
    dc = make_collector(eu='mm/s2', target_unit='mm/s',
                        highpass_enabled=True, highpass_fc=10.0)
    df = dc.config.samplerate / dc.config.blocksize
    freq = 61 * df + frac * df
    amp = 1.0

    result = dc.process_sample(0, make_sample(dc, tone(dc, freq, amp)))
    assert result is not None
    expected = true_rms(amp, freq, 1)
    err = rel_err(result.overall, expected)
    assert abs(err) < 0.03, (
        f'velocity overall (HP on) at {freq:.3f} Hz: expected {expected:.6e}, '
        f'got {result.overall:.6e} ({err:+.2%})'
    )


def test_f1_offbin_with_highpass_and_dc_offset():
    """A DC offset must be removed by the high-pass, not integrated into a ramp."""
    dc = make_collector(eu='mm/s2', target_unit='mm/s',
                        highpass_enabled=True, highpass_fc=10.0)
    df = dc.config.samplerate / dc.config.blocksize
    freq = 61 * df + 0.37 * df
    amp = 1.0

    data = tone(dc, freq, amp, offset=1000.0)
    result = dc.process_sample(0, make_sample(dc, data))
    assert result is not None
    expected = true_rms(amp, freq, 1)
    err = rel_err(result.overall, expected)
    assert abs(err) < 0.05, (
        f'velocity overall (HP on, 1000 mV DC offset): expected {expected:.6e}, '
        f'got {result.overall:.6e} ({err:+.2%})'
    )


# ===========================================================================
# F-4 — High-pass filter state is reset to zero on every block
# ===========================================================================

def test_f4_filter_state_continuity_across_blocks():
    """Consecutive blocks of ONE continuous stream must not each restart the filter.

    Feeding a continuous sine in blocks, every block after the first should
    read the true RMS — a per-block state reset injects a startup transient
    into every frame.
    """
    dc = as_streaming(make_collector(eu='mm/s2', target_unit='mm/s2',
                                     maxfreq=2000, binsize=2.0,
                                     highpass_enabled=True, highpass_fc=10.0))
    N = dc.config.blocksize
    freq, amp = 200.0, 1.0

    peaks = []
    for i in range(4):
        block = tone(dc, freq, amp, n=N, start_sample=i * N)
        dc.receive_data({
            'status': 'OKAY', 'overflow_mask': 0, 'rel_time': i * 1.0,
            'timestamp': datetime.now(), 'unit': ['mV'], 'channels': [0],
            'data': block[:, np.newaxis], 'samplerate': dc.config.samplerate,
            'degraded': False,
        })
        sample = dc.data['frame_cache'][-1][0]
        result = dc.process_sample(0, sample)
        peaks.append(float(np.max(np.abs(result.time_data))))

    # The transient shows up most clearly in the waveform peak: a filter that
    # restarts from zero overshoots the true 0-peak amplitude at every block
    # start.  Blocks 1.. are mid-stream, so no transient is physically present.
    for i, pk in enumerate(peaks[1:], start=1):
        err = rel_err(pk, amp)
        assert abs(err) < 0.01, (
            f'block {i} waveform peak={pk:.6f}, expected {amp:.6f} ({err:+.2%}) '
            f'— filter state not carried across blocks'
        )


def test_f4_filter_state_continuity_with_dc_offset():
    """With a DC offset the per-block reset is catastrophic, not cosmetic."""
    dc = as_streaming(make_collector(eu='mm/s2', target_unit='mm/s2',
                                     maxfreq=2000, binsize=2.0,
                                     highpass_enabled=True, highpass_fc=10.0))
    N = dc.config.blocksize
    freq, amp, offset = 200.0, 1.0, 1000.0

    overalls = []
    for i in range(4):
        block = tone(dc, freq, amp, offset=offset, n=N, start_sample=i * N)
        dc.receive_data({
            'status': 'OKAY', 'overflow_mask': 0, 'rel_time': i * 1.0,
            'timestamp': datetime.now(), 'unit': ['mV'], 'channels': [0],
            'data': block[:, np.newaxis], 'samplerate': dc.config.samplerate,
            'degraded': False,
        })
        sample = dc.data['frame_cache'][-1][0]
        overalls.append(dc.process_sample(0, sample).overall)

    expected = amp / np.sqrt(2)
    for i, ov in enumerate(overalls[1:], start=1):
        err = rel_err(ov, expected)
        assert abs(err) < 0.01, (
            f'block {i} with {offset} mV DC offset: overall={ov:.6f}, '
            f'expected {expected:.6f} ({err:+.2%})'
        )


def test_f4_replay_is_order_independent():
    """Browse/offline mode re-processes cached frames out of order.

    Carried streaming state must NOT leak into replay: processing the same
    stored frame twice, and in a different order, must give identical results.
    """
    dc = make_collector(eu='mm/s2', target_unit='mm/s2', maxfreq=2000,
                        binsize=2.0, highpass_enabled=True, highpass_fc=10.0)
    N = dc.config.blocksize
    frames = [make_sample(dc, tone(dc, 200.0, 1.0 + i, n=N, start_sample=i * N))
              for i in range(3)]

    forward = [dc.process_sample(0, f).overall for f in frames]
    # Re-process in reverse; each frame must reproduce its own value exactly.
    reverse = {}
    for i in reversed(range(3)):
        reverse[i] = dc.process_sample(0, frames[i]).overall

    for i in range(3):
        assert reverse[i] == pytest.approx(forward[i], rel=1e-12), (
            f'frame {i} replayed out of order gave {reverse[i]:.9f}, '
            f'first pass gave {forward[i]:.9f} — replay is not deterministic'
        )


@pytest.mark.parametrize('phase', [0.0, np.pi / 2, np.pi, 2.4, -np.pi / 2])
@pytest.mark.parametrize('target', ['mm/s2', 'mm/s'])
def test_f4_seed_independent_of_start_phase(phase, target):
    """An isolated block must filter correctly whatever sample it starts on.

    Seeding the high-pass with sosfilt_zi * x[0] treats the first sample as the
    signal's DC baseline. That is true only when the record happens to start at
    a zero crossing. At phase pi/2 the block starts at the positive peak, and
    the filter then decays a step that was never in the signal.
    """
    dc = make_collector(eu='mm/s2', target_unit=target, maxfreq=2000,
                        binsize=2.0, highpass_enabled=True, highpass_fc=10.0)
    freq, amp = 200.0, 1.0
    n_int = 0 if target == 'mm/s2' else 1

    data = tone(dc, freq, amp, phase=phase)
    result = dc.process_sample(0, make_sample(dc, data))
    assert result is not None

    expected = true_rms(amp, freq, n_int)
    err = rel_err(result.overall, expected)
    assert abs(err) < 0.01, (
        f'{target} overall at start phase {phase:.3f} rad (x[0]={data[0]:+.4f}, '
        f'mean={data.mean():+.4f}): expected {expected:.6e}, got '
        f'{result.overall:.6e} ({err:+.2%}) -- filter seeded from x[0], not the '
        f'block DC level'
    )


@pytest.mark.parametrize('phase', [np.pi / 2, -np.pi / 2])
def test_f4_seed_with_phase_and_dc_offset(phase):
    """Phase offset AND a real DC offset -- the case seeding exists to handle.

    The seed must track the block's DC content (which the high-pass should
    reject) and not the waveform excursion on top of it.
    """
    dc = make_collector(eu='mm/s2', target_unit='mm/s2', maxfreq=2000,
                        binsize=2.0, highpass_enabled=True, highpass_fc=10.0)
    freq, amp, offset = 200.0, 1.0, 1000.0

    data = tone(dc, freq, amp, offset=offset, phase=phase)
    result = dc.process_sample(0, make_sample(dc, data))
    assert result is not None

    expected = amp / np.sqrt(2)
    err = rel_err(result.overall, expected)
    # Tight: x[0]-seeding errs +1.017% here (the seed misses the DC level by
    # the waveform excursion), mean-seeding by -0.000%.
    assert abs(err) < 0.005, (
        f'overall at phase {phase:.3f} with {offset} mV DC offset '
        f'(x[0]={data[0]:.3f}, mean={data.mean():.3f}): expected '
        f'{expected:.6f}, got {result.overall:.6f} ({err:+.2%})'
    )


def test_f4_streaming_first_block_seeded_from_dc_not_first_sample():
    """Block 0 of a live stream is seeded, not carried -- the seed must be right."""
    dc = as_streaming(make_collector(eu='mm/s2', target_unit='mm/s2',
                                     maxfreq=2000, binsize=2.0,
                                     highpass_enabled=True, highpass_fc=10.0))
    N = dc.config.blocksize
    # Start at the positive peak: worst case for x[0]-based seeding.
    block = tone(dc, 200.0, 1.0, n=N, phase=np.pi / 2)
    dc.receive_data({
        'status': 'OKAY', 'overflow_mask': 0, 'rel_time': 0.0,
        'timestamp': datetime.now(), 'unit': ['mV'], 'channels': [0],
        'data': block[:, np.newaxis], 'samplerate': dc.config.samplerate,
        'degraded': False,
    })
    result = dc.process_sample(0, dc.data['frame_cache'][-1][0])
    expected = 1.0 / np.sqrt(2)
    err = rel_err(result.overall, expected)
    assert abs(err) < 0.01, (
        f'first streaming block starting at the peak: overall={result.overall:.6f}, '
        f'expected {expected:.6f} ({err:+.2%})'
    )


def test_f4_replay_has_no_startup_transient():
    """An isolated stored frame must still be filtered without a step transient."""
    dc = make_collector(eu='mm/s2', target_unit='mm/s2', maxfreq=2000,
                        binsize=2.0, highpass_enabled=True, highpass_fc=10.0)
    data = tone(dc, 200.0, 1.0, offset=1000.0)
    result = dc.process_sample(0, make_sample(dc, data))
    expected = 1.0 / np.sqrt(2)
    err = rel_err(result.overall, expected)
    assert abs(err) < 0.02, (
        f'isolated replay frame with DC offset: overall={result.overall:.6f}, '
        f'expected {expected:.6f} ({err:+.2%})'
    )


# ===========================================================================
# F-2 — The reported sample rate is not the sample rate actually used
# ===========================================================================

def test_f2_reported_samplerate_matches_hardware():
    """PicoScopeStream must report actual_raw_fs / osr, not the requested rate.

    The driver rounds the streaming interval to whole microseconds and writes
    back what it used.  Reporting the requested rate instead scales every
    displayed frequency by (requested / actual).
    """
    from rev80.picoscope import STREAMING_CEILING_HZ, OSR_TARGET

    cfg = vc.AcquisitionSettings()
    cfg.maxfreq = 2000
    cfg.binsize = 2.0
    fs = cfg.samplerate                      # 8192
    osr = max(1, int(min(OSR_TARGET, STREAMING_CEILING_HZ / fs)))
    raw_req = fs * osr
    interval_us = max(1, int(1e6 / raw_req))
    actual_raw_fs = round(1e6 / interval_us)
    expected_reported = actual_raw_fs / osr

    # The truncation must actually bite for this preset, else the test is vacuous.
    assert actual_raw_fs != raw_req, 'preset chosen does not exercise us truncation'

    assert abs(expected_reported - fs) / fs > 0.01, (
        'expected a >1% discrepancy between requested and achieved rate'
    )

    stream = _make_bare_stream(cfg)
    stream._effective_osr = osr
    _simulate_run_streaming(stream, interval_us)

    assert stream._actual_samplerate == pytest.approx(expected_reported, rel=1e-9), (
        f'reported samplerate {stream._actual_samplerate} != actual '
        f'{expected_reported:.2f} Hz (requested {fs})'
    )


def _make_bare_stream(cfg):
    """A PicoScopeStream instance without touching the driver."""
    from rev80.picoscope import PicoScopeStream
    return PicoScopeStream(cfg, lambda samp: None)


def _simulate_run_streaming(stream, interval_us: int):
    """Reproduce the post-RunStreaming rate write-back that _start_streaming does."""
    actual_raw_fs = round(1e6 / interval_us)
    stream._actual_raw_samplerate = actual_raw_fs
    stream._actual_samplerate = stream._report_samplerate(actual_raw_fs)


@pytest.mark.parametrize('maxfreq', [200, 500, 1000, 2000, 5000, 10000])
def test_f2_reported_rate_consistent_across_presets(maxfreq):
    """Whatever the preset, the reported rate must equal raw_actual / osr."""
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq = maxfreq
    cfg.binsize = 2.0
    stream = _make_bare_stream(cfg)
    osr = stream._effective_osr
    raw_req = cfg.samplerate * osr
    interval_us = max(1, int(1e6 / raw_req))
    actual_raw_fs = round(1e6 / interval_us)

    _simulate_run_streaming(stream, interval_us)
    assert stream._actual_samplerate == pytest.approx(actual_raw_fs / osr, rel=1e-9)


# ===========================================================================
# F-3 — No anti-alias filtering at all above F_max = 20 kHz
# ===========================================================================

@pytest.mark.parametrize('maxfreq', vc.MAXFREQ_PRESETS)
def test_f3_every_preset_has_antialias_headroom(maxfreq):
    """Every offered preset must actually get anti-alias protection.

    antialias_decimate() is a no-op at factor=1, so an oversample ratio of 1
    means NO anti-alias filtering at all.
    """
    from rev80.picoscope import STREAMING_CEILING_HZ

    cfg = vc.AcquisitionSettings()
    cfg.maxfreq = maxfreq
    cfg.binsize = 2.0
    stream = _make_bare_stream(cfg)

    assert stream._effective_osr >= 2, (
        f'F_max={maxfreq:.0f} Hz (fs={cfg.samplerate}) gets osr='
        f'{stream._effective_osr} → antialias_decimate is a no-op, '
        f'so there is NO anti-alias filter'
    )
    raw = cfg.samplerate * stream._effective_osr
    assert raw <= STREAMING_CEILING_HZ, (
        f'F_max={maxfreq:.0f} Hz needs {raw} Hz raw streaming, above the '
        f'measured {STREAMING_CEILING_HZ} Hz safe ceiling — the driver '
        f'silently drops samples with status=OKAY'
    )


def test_f3_presets_are_gated_at_selection_time():
    """MAXFREQ_PRESETS must not offer a rate the hardware cannot stream safely."""
    from rev80.picoscope import STREAMING_CEILING_HZ

    for maxfreq in vc.MAXFREQ_PRESETS:
        cfg = vc.AcquisitionSettings()
        cfg.maxfreq = maxfreq
        assert cfg.samplerate * 2 <= STREAMING_CEILING_HZ, (
            f'preset F_max={maxfreq:.0f} Hz cannot support even 2x oversampling '
            f'({cfg.samplerate * 2} Hz > {STREAMING_CEILING_HZ} Hz)'
        )


# ===========================================================================
# F-5 — Overload / degraded frames are trended, alarmed on, and lose their flags
# ===========================================================================

def test_f5_flags_survive_hdf5_round_trip(tmp_path):
    """overflow and degraded are written by _write_channel_group but never read back."""
    dc = as_streaming(make_collector(eu='mm/s2', target_unit='mm/s2',
                                     maxfreq=2000, binsize=2.0))
    N = dc.config.blocksize
    flags = [(False, False), (True, False), (False, True), (True, True)]
    for i, (ovf, deg) in enumerate(flags):
        dc.data['frame_cache'].append(
            {0: make_sample(dc, tone(dc, 200.0, 1.0, n=N), overflow=ovf,
                            degraded=deg, rel_time=float(i))}
        )

    target = tmp_path / 'flags.h5'
    dc.save_data(target)

    dc2 = make_collector(eu='mm/s2', target_unit='mm/s2', maxfreq=2000, binsize=2.0)
    dc2.load_data(target)

    assert len(dc2.data['frame_cache']) == len(flags)
    for i, (ovf, deg) in enumerate(flags):
        s = dc2.data['frame_cache'][i][0]
        assert s.overflow is ovf, f'frame {i}: overflow read back as {s.overflow}, expected {ovf}'
        assert s.degraded is deg, f'frame {i}: degraded read back as {s.degraded}, expected {deg}'


def test_f5_flagged_frames_excluded_from_trend():
    """A clipped or degraded frame must not become a trend point."""
    dc = as_streaming(make_collector(eu='mm/s2', target_unit='mm/s2',
                                     maxfreq=2000, binsize=2.0))
    dc.init_trend_channels()
    N = dc.config.blocksize

    def push(ovf, deg, rel):
        dc.data['frame_cache'].append(
            {0: make_sample(dc, tone(dc, 200.0, 1.0, n=N), overflow=ovf,
                            degraded=deg, rel_time=rel)}
        )
        dc.process_samples()

    push(False, False, 0.0)
    push(True, False, 1.0)      # clipped — must be skipped
    push(False, True, 2.0)      # degraded — must be skipped
    push(False, False, 3.0)

    rel_times = list(dc.trend[0]['rel_times'])
    assert rel_times == [0.0, 3.0], (
        f'trend recorded {rel_times}; clipped/degraded frames must be excluded'
    )


def test_f5_anomaly_hook_ignores_flagged_frames():
    """A clipped frame reads high with harmonic distortion — it must not alarm."""
    from rev80.monitor.anomaly import RmsThresholdHook

    hook = RmsThresholdHook(rms_threshold_pct=10.0, consecutive_n=1,
                            min_baseline_samples=2)

    def result(overall, overflow=False, degraded=False):
        return vc.ChannelResult(
            channel=0, unit='mm/s2', overflow=overflow, degraded=degraded,
            time_data=np.zeros(4), time_vec=np.zeros(4), samplerate=8192,
            freq=np.zeros(4), spectrum=np.zeros(4), peaks=np.array([], dtype=int),
            overall=overall, timestamp=datetime.now(), rel_time=0.0, status='OKAY',
        )

    # Warm the baseline up on clean frames.
    for _ in range(10):
        hook.on_results([result(1.0)], None)

    # A clipped frame reading 10x high must not fire.
    event = hook.on_results([result(10.0, overflow=True)], None)
    assert event is None, 'anomaly hook fired on an overflowed (clipped) frame'

    event = hook.on_results([result(10.0, degraded=True)], None)
    assert event is None, 'anomaly hook fired on a degraded frame'


def test_f5_flagged_frames_do_not_poison_the_baseline():
    """A clipped frame must not be folded into the EWMA baseline either."""
    from rev80.monitor.anomaly import RmsThresholdHook

    hook = RmsThresholdHook(rms_threshold_pct=10.0, consecutive_n=1,
                            min_baseline_samples=2)

    def result(overall, overflow=False):
        return vc.ChannelResult(
            channel=0, unit='mm/s2', overflow=overflow, degraded=False,
            time_data=np.zeros(4), time_vec=np.zeros(4), samplerate=8192,
            freq=np.zeros(4), spectrum=np.zeros(4), peaks=np.array([], dtype=int),
            overall=overall, timestamp=datetime.now(), rel_time=0.0, status='OKAY',
        )

    for _ in range(10):
        hook.on_results([result(1.0)], None)
    before = hook.baseline_snapshot()[0]
    hook.on_results([result(1000.0, overflow=True)], None)
    after = hook.baseline_snapshot()[0]
    assert after == pytest.approx(before), (
        f'baseline moved from {before:.6f} to {after:.6f} on a clipped frame'
    )


def test_f5_monitor_writer_stores_validity_flags(tmp_path):
    """monitor/writer.py has its own _write_channel_group that wrote no flags."""
    import h5py
    from rev80.monitor.writer import _write_channel_group

    dc = make_collector(maxfreq=2000, binsize=2.0)
    sample = make_sample(dc, tone(dc, 200.0, 1.0), overflow=True, degraded=True)

    path = tmp_path / 'w.h5'
    with h5py.File(path, 'w') as f:
        _write_channel_group(f, 0, sample)
    with h5py.File(path, 'r') as f:
        attrs = f['0'].attrs
        assert bool(attrs['overflow']) is True, 'monitor writer lost the overflow flag'
        assert bool(attrs['degraded']) is True, 'monitor writer lost the degraded flag'


def test_f5_overflow_mask_is_latched_across_accumulation():
    """An overflow in a callback that does not complete a block must not be lost."""
    import ctypes
    from rev80.picoscope import PicoScopeStream

    cfg = vc.AcquisitionSettings()
    cfg.maxfreq = 200
    cfg.binsize = 2.0
    cfg.enabled_channels = [0]

    received = []
    stream = PicoScopeStream(cfg, lambda samp: received.append(samp))
    stream._maxADC = ctypes.c_int16(32767)
    stream._stream_start = 0.0

    raw_bs = cfg.blocksize * stream._effective_osr
    chunk = max(1, raw_bs // 4)

    # Fill the driver buffer with a benign ramp.
    for ch in stream._driver_buffers:
        stream._driver_buffers[ch][:] = 1000

    # First callback carries the overflow bit but does not complete a block.
    stream._streaming_callback(None, chunk, 0, 1, 0, 0, 0, None)
    assert not received, 'block completed too early; adjust chunk size'
    # Subsequent callbacks are clean but do complete the block.
    while not received:
        stream._streaming_callback(None, chunk, 0, 0, 0, 0, 0, None)

    assert received[0]['overflow_mask'] & 1, (
        'overflow raised mid-accumulation was lost — the mask must be latched '
        'with |= across the accumulation window'
    )


def test_s09_overflow_warns_once_per_channel_per_stream(caplog):
    """Sustained clipping must log once per channel, not once per callback.

    The old `elif ch in self._overflow_warned: remove(ch)` fired precisely when
    a channel was STILL clipping (the first branch being False only because it
    had already been warned), re-arming the warning every other callback. At a
    1 ms poll interval that floods the rotating log during exactly the event
    being diagnosed, and contradicts the class docstring's "once per channel
    per stream start".
    """
    import ctypes
    import logging
    from rev80.picoscope import PicoScopeStream

    cfg = vc.AcquisitionSettings()
    cfg.maxfreq = 200
    cfg.binsize = 2.0
    cfg.enabled_channels = [0, 1]

    stream = PicoScopeStream(cfg, lambda samp: None)
    stream._maxADC = ctypes.c_int16(32767)
    stream._stream_start = 0.0
    for ch in stream._driver_buffers:
        stream._driver_buffers[ch][:] = 1000

    def warnings_for(ch: int) -> int:
        needle = f'ADC overflow on Channel {chr(65 + ch)}'
        return sum(1 for r in caplog.records if needle in r.getMessage())

    with caplog.at_level(logging.WARNING):
        # Sustained clipping on channel 0 across many callbacks.
        for _ in range(20):
            stream._streaming_callback(None, 8, 0, 0b01, 0, 0, 0, None)
        assert warnings_for(0) == 1, (
            f'sustained clipping logged {warnings_for(0)} warnings; expected 1 '
            f'per channel per stream'
        )
        assert warnings_for(1) == 0

        # Channel 0 stops clipping: the inhibit must clear.
        for _ in range(5):
            stream._streaming_callback(None, 8, 0, 0b00, 0, 0, 0, None)
        assert warnings_for(0) == 1

        # A NEW overflow event on the same channel must warn again.
        for _ in range(5):
            stream._streaming_callback(None, 8, 0, 0b01, 0, 0, 0, None)
        assert warnings_for(0) == 2, (
            'a channel that stopped clipping and then clipped again must warn '
            'a second time; the inhibit never cleared'
        )

        # And a different channel warns independently.
        for _ in range(5):
            stream._streaming_callback(None, 8, 0, 0b10, 0, 0, 0, None)
        assert warnings_for(1) == 1


# ===========================================================================
# F-6 — The acquisition dialog computes sample rate with 2x, not 2.56x
# ===========================================================================

@pytest.mark.parametrize('maxfreq', [200, 500, 1000, 2000, 5000, 10000])
@pytest.mark.parametrize('binsize', [0.5, 2.0, 10.0])
def test_f6_dialog_preview_matches_acquisition_settings(maxfreq, binsize):
    """The dialog must not duplicate the samplerate formula."""
    from rev80.gui import derive_acquisition_preview

    cfg = vc.AcquisitionSettings()
    cfg.maxfreq = maxfreq
    cfg.binsize = binsize
    preview = derive_acquisition_preview(maxfreq, binsize)

    assert preview['samplerate'] == cfg.samplerate, (
        f'dialog previews {preview["samplerate"]} S/s, instrument runs at '
        f'{cfg.samplerate} S/s'
    )
    assert preview['blocksize'] == cfg.blocksize
    assert preview['n_fft_bins'] == cfg.n_fft_bins
    assert preview['acq_time'] == pytest.approx(cfg.acquisition_period)
    assert preview['mem_bytes'] == cfg.memory_bytes


# ===========================================================================
# F-7 — The PSD cache key omits binsize and samplerate
# ===========================================================================

def test_f7_psd_cache_invalidates_on_binsize_change():
    """Changing binsize must actually recompute the spectrum.

    Exercised by going coarser (0.5 → 8 Hz). Going *finer* than the captured
    record supports is physically impossible — a stored 0.5 s block cannot
    yield 0.5 Hz bins no matter what is requested — so a coarsening change is
    what actually distinguishes a live recompute from a stale cache hit.
    """
    dc = make_collector(eu='mm/s2', target_unit='mm/s2', maxfreq=2000, binsize=0.5)
    sample = make_sample(dc, tone(dc, 200.0, 1.0, n=dc.config.blocksize))

    first = dc.process_sample(0, sample)
    n_first = len(first.freq)
    df_first = float(first.freq[1] - first.freq[0])
    assert df_first == pytest.approx(0.5)

    dc.config.binsize = 8.0
    second = dc.process_sample(0, sample)
    df_second = float(second.freq[1] - second.freq[0])

    assert df_second > df_first, (
        f'binsize 0.5 → 8.0 left the resolution at {df_second} Hz/bin '
        f'(was {df_first}); the PSD cache key ignores binsize'
    )
    assert len(second.freq) != n_first


def test_f7_resolution_never_claimed_finer_than_the_record_supports():
    """A stored block cannot be re-binned finer than its own length allows."""
    dc = make_collector(eu='mm/s2', target_unit='mm/s2', maxfreq=2000, binsize=2.0)
    sample = make_sample(dc, tone(dc, 200.0, 1.0, n=dc.config.blocksize))
    captured_df = dc.config.samplerate / sample.blocksize

    dc.config.binsize = 0.25          # ask for 8x finer than the record allows
    result = dc.process_sample(0, sample)
    df = float(result.freq[1] - result.freq[0])

    assert df == pytest.approx(captured_df), (
        f're-binning a {sample.blocksize}-sample record reported {df} Hz/bin; '
        f'the record only supports {captured_df} Hz/bin'
    )


def test_f7_psd_cache_invalidates_on_samplerate_change():
    """A sample captured at a different rate must not reuse a cached PSD."""
    dc = make_collector(eu='mm/s2', target_unit='mm/s2', maxfreq=2000, binsize=2.0)
    sample = make_sample(dc, tone(dc, 200.0, 1.0, n=dc.config.blocksize))
    first = dc.process_sample(0, sample)

    df_first = float(first.freq[1] - first.freq[0])

    # Same VibeSample object, re-tagged with a different capture rate. The bin
    # width scales with fs for a fixed segment length, so it is the observable
    # here — freq[-1] is not, since both spectra are now capped at maxfreq.
    sample.samplerate = dc.config.samplerate * 2
    second = dc.process_sample(0, sample)
    df_second = float(second.freq[1] - second.freq[0])

    assert df_second == pytest.approx(df_first * 2), (
        f'sample rate doubled but bin width went {df_first} -> {df_second}; '
        f'the PSD cache key omits samplerate'
    )


# ===========================================================================
# F-8 — Stated line count and bin width do not match the computed spectrum
# ===========================================================================

@pytest.mark.parametrize('maxfreq', [200, 500, 1000, 2000])
@pytest.mark.parametrize('binsize', [0.5, 2.0, 5.0, 20.0, 100.0])
def test_f8_line_count_matches_computed_spectrum(maxfreq, binsize):
    """config.n_fft_bins must equal the number of lines Welch actually returns."""
    dc = make_collector(eu='mm/s2', target_unit='mm/s2',
                        maxfreq=maxfreq, binsize=binsize)
    result = dc.process_sample(0, make_sample(dc, tone(dc, maxfreq / 4, 1.0)))
    assert result is not None
    assert len(result.freq) == dc.config.n_fft_bins, (
        f'F_max={maxfreq} df={binsize}: UI states {dc.config.n_fft_bins} lines, '
        f'spectrum has {len(result.freq)}'
    )


@pytest.mark.parametrize('maxfreq', [200, 500, 1000, 2000])
@pytest.mark.parametrize('binsize', [0.5, 2.0, 5.0, 20.0, 100.0])
def test_f8_actual_bin_width_is_at_least_as_fine_as_requested(maxfreq, binsize):
    """Actual resolution must never be coarser than what the user asked for."""
    dc = make_collector(eu='mm/s2', target_unit='mm/s2',
                        maxfreq=maxfreq, binsize=binsize)
    result = dc.process_sample(0, make_sample(dc, tone(dc, maxfreq / 4, 1.0)))
    assert result is not None
    df_actual = float(result.freq[1] - result.freq[0])
    assert df_actual <= binsize * 1.0001, (
        f'F_max={maxfreq} requested {binsize} Hz/bin, got {df_actual:.4f} Hz/bin '
        f'({(df_actual - binsize) / binsize:+.2%})'
    )
    assert df_actual == pytest.approx(dc.config.binsize_actual, rel=1e-9), (
        'config.binsize_actual must report the resolution actually delivered'
    )


# ===========================================================================
# F-9 — Spectrum is displayed out to fs/2, where alias rejection is ~12 dB
# ===========================================================================

@pytest.mark.parametrize('maxfreq', [200, 1000, 2000])
def test_f9_spectrum_truncated_at_maxfreq(maxfreq):
    """The guard band between F_max and fs/2 must never be displayed.

    F_max = fs/2.56 exists precisely so the region where the anti-alias
    filter has not yet reached full attenuation is not shown as measurement.
    """
    dc = make_collector(eu='mm/s2', target_unit='mm/s2',
                        maxfreq=maxfreq, binsize=2.0)
    result = dc.process_sample(0, make_sample(dc, tone(dc, maxfreq / 4, 1.0)))
    assert result is not None

    assert float(result.freq[-1]) <= maxfreq * 1.0001, (
        f'spectrum extends to {result.freq[-1]:.1f} Hz, past F_max={maxfreq} Hz '
        f'into the guard band (fs/2 = {dc.config.samplerate / 2:.0f} Hz)'
    )
    assert len(result.spectrum) == len(result.freq)


def test_f9_peaks_exclude_the_guard_band():
    """find_peaks must not report peaks from the untrustworthy guard band."""
    dc = make_collector(eu='mm/s2', target_unit='mm/s2', maxfreq=2000, binsize=2.0)
    fs = dc.config.samplerate
    # Real tone in-band plus a strong tone inside the guard band (F_max..fs/2).
    guard_freq = (2000 + fs / 2) / 2
    data = tone(dc, 500.0, 1.0) + tone(dc, guard_freq, 5.0)
    result = dc.process_sample(0, make_sample(dc, data))
    assert result is not None

    if len(result.peaks):
        peak_freqs = result.freq[result.peaks]
        assert float(np.max(peak_freqs)) <= 2000 * 1.0001, (
            f'peak reported at {np.max(peak_freqs):.1f} Hz, inside the guard band'
        )
