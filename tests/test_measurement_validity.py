"""Accuracy of the measurement chain under input that a real machine produces.

Tones are off-bin where a test checks leakage, and start at a non-zero phase.
A bin-centred tone makes the FFT wrap error zero and hides integration defects.
Put new amplitude assertions in this file, not in test_sample.py.
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


# Default start phase of generated tones, in radians. Not 0: at phase 0, x[0]
# equals the DC level, which hides a high-pass seeded from x[0]. On AWG
# loopback (447.3 Hz), x[0] was 36 to 305 mV; the block mean was -0.06 to -0.21 mV.
DEFAULT_PHASE = 0.7


def tone(dc, freq: float, amp: float = 1.0, offset: float = 0.0,
         n: int | None = None, start_sample: int = 0,
         phase: float = DEFAULT_PHASE) -> np.ndarray:
    """A sine of `amp` (0-peak) at `freq`, sampled at config.samplerate.

    `phase` is in radians. The analytic results do not depend on phase.
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


# Fractional bin offsets. 0.0 (on-bin) is not included: it hides wrap error.
OFFBIN_FRACTIONS = [0.37, 0.5, 0.13, 0.71]


# ===========================================================================
# Integration is accurate for off-bin tones
# (CONTRIBUTING.md, "E9. Tapers for integration")
# ===========================================================================

@pytest.mark.parametrize('frac', OFFBIN_FRACTIONS)
def test_integrated_velocity_overall_accurate_off_bin(frac):
    """Off-bin tone, acceleration to velocity: the overall equals the analytic RMS."""
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
def test_integrated_displacement_overall_accurate_off_bin(frac):
    """Off-bin tone, acceleration to displacement: the overall equals the analytic RMS.

    Double integration amplifies wrap leakage by 1/w^2.
    """
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
def test_displacement_overall_accurate_at_specific_off_bin_frequencies(freq_hz):
    """The displacement overall is accurate at 61.0, 120.7 and 501.0 Hz (off-bin)."""
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
def test_integrated_velocity_waveform_peak_accurate_off_bin(frac):
    """The displayed velocity trace has no leakage ramp.

    Its peak equals the analytic 0-peak velocity amplitude.
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
def test_integrated_displacement_waveform_peak_accurate_off_bin(frac):
    """The displayed displacement trace has no leakage ramp (1/w^2 makes one dominate)."""
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


def test_integration_still_exact_for_bin_centred_tones():
    """A bin-centred tone (500 Hz) still integrates to the analytic RMS."""
    dc = make_collector(eu='mm/s2', target_unit='mm')
    result = dc.process_sample(0, make_sample(dc, tone(dc, 500.0, 1.0)))
    assert result is not None
    expected = true_rms(1.0, 500.0, 2)
    assert abs(rel_err(result.overall, expected)) < 0.02


def test_passthrough_overall_recovers_the_tone_rms_off_bin():
    """Order 0 reports the tone RMS A/sqrt(2), not the RMS of the record.

    Order 0 uses the same Hann-tapered, band-masked path as the other four
    orders. An off-bin record holds a non-integer number of cycles, so its own
    RMS has a partial-cycle bias (+0.097 % here). An untapered mask was rejected:
    a 30 Hz tone below a 100 Hz band edge leaked in at -22 dB (+2.7 % on the
    overall), against -84 dB with Hann. See CONTRIBUTING.md, "E9. Tapers for
    integration".
    """
    dc = make_collector(eu='mm/s2', target_unit='mm/s2')
    data = tone(dc, 120.7, 1.0)
    result = dc.process_sample(0, make_sample(dc, data))
    assert result is not None

    assert abs(rel_err(result.overall, true_rms(1.0, 120.7, 0))) < 1e-9

    # The record's own RMS is the biased quantity, and is measurably further off.
    record_rms = float(np.sqrt(np.mean(data ** 2)))
    assert abs(rel_err(record_rms, true_rms(1.0, 120.7, 0))) > 1e-4


@pytest.mark.parametrize('frac', [0.37, 0.5])
def test_integrated_velocity_overall_accurate_off_bin_with_highpass(frac):
    """Off-bin integration is accurate through the high-pass path (edge 10 Hz)."""
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


def test_highpass_removes_dc_offset_before_integration():
    """The high-pass removes a 1000 mV DC offset, so integration makes no ramp."""
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
# High-pass state: carried while streaming, seeded from the block mean on replay
# (CONTRIBUTING.md, "E8.1. Stateful filter" and "E8.2. Seed from the block mean")
# ===========================================================================

def test_highpass_state_persists_across_streaming_blocks():
    """The blocks of one continuous stream share the filter state.

    After block 0, each block reads the true peak. A reset in each block would
    put a start-up transient into every frame.
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


def test_highpass_state_persists_across_blocks_with_dc_offset():
    """With a 1000 mV DC offset, blocks after block 0 read the true RMS within 1 %."""
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


def test_replay_processing_is_order_independent():
    """Replay gives the same result for a stored frame in any processing order.

    Browse mode processes cached frames out of order, so streaming filter
    state must not leak into replay.
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
def test_highpass_seed_correct_regardless_of_start_phase(phase, target):
    """An isolated block filters correctly at any start phase.

    A seed of sosfilt_zi * x[0] treats the first sample as the DC level. That
    is true only at a zero crossing: at phase pi/2 the filter decays a step
    that is not in the signal. The seed comes from the block mean.
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
def test_highpass_seed_correct_with_phase_and_dc_offset(phase):
    """With a phase offset and a 1000 mV DC offset, the seed follows the DC level.

    The seed must not follow the waveform excursion on top of the DC level.
    """
    dc = make_collector(eu='mm/s2', target_unit='mm/s2', maxfreq=2000,
                        binsize=2.0, highpass_enabled=True, highpass_fc=10.0)
    freq, amp, offset = 200.0, 1.0, 1000.0

    data = tone(dc, freq, amp, offset=offset, phase=phase)
    result = dc.process_sample(0, make_sample(dc, data))
    assert result is not None

    expected = amp / np.sqrt(2)
    err = rel_err(result.overall, expected)
    # Tight: a seed from x[0] gives +1.017 % here; a seed from the mean, -0.000 %.
    assert abs(err) < 0.005, (
        f'overall at phase {phase:.3f} with {offset} mV DC offset '
        f'(x[0]={data[0]:.3f}, mean={data.mean():.3f}): expected '
        f'{expected:.6f}, got {result.overall:.6f} ({err:+.2%})'
    )


def test_first_streaming_block_highpass_seeded_from_dc_not_first_sample():
    """Block 0 of a live stream is seeded from the DC level, not from x[0]."""
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


def test_replayed_frame_has_no_highpass_startup_transient():
    """An isolated stored frame with a DC offset filters without a step transient."""
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
# The reported sample rate is the achieved rate
# (CONTRIBUTING.md, "E5. Report the achieved rate")
# ===========================================================================

def test_reported_samplerate_matches_actual_hardware_rate():
    """PicoScopeStream reports the achieved raw rate / OSR, not the requested rate.

    The driver quantises the streaming interval and writes back the value it
    used. This test models a whole-microsecond interval, so that the two rates
    differ by more than 1 %. The requested rate would scale every frequency.
    """
    from rev80.picoscope import STREAMING_CEILING_HZ, OSR_TARGET

    cfg = vc.AcquisitionSettings()
    cfg.maxfreq = 2000
    cfg.binsize = 2.0
    fs = cfg.samplerate                      # 5120 Hz
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
def test_reported_samplerate_consistent_across_all_presets(maxfreq):
    """At every preset, the reported rate equals the achieved raw rate / OSR."""
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
# Every F_max preset gets anti-alias filtering below the streaming ceiling
# (CONTRIBUTING.md, "E1. Streaming ceiling and the raw rate", "E6. Oversampling ratio")
# ===========================================================================

@pytest.mark.parametrize('maxfreq', vc.MAXFREQ_PRESETS)
def test_every_maxfreq_preset_has_antialias_headroom(maxfreq):
    """Every F_max preset gets an OSR of 2 or more, below the streaming ceiling.

    antialias_decimate() does nothing at factor 1, so an OSR of 1 means that
    there is no anti-alias filter.
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


def test_presets_are_gated_against_streaming_ceiling():
    """No MAXFREQ_PRESETS entry needs more than the streaming ceiling at 2x oversampling."""
    from rev80.picoscope import STREAMING_CEILING_HZ

    for maxfreq in vc.MAXFREQ_PRESETS:
        cfg = vc.AcquisitionSettings()
        cfg.maxfreq = maxfreq
        assert cfg.samplerate * 2 <= STREAMING_CEILING_HZ, (
            f'preset F_max={maxfreq:.0f} Hz cannot support even 2x oversampling '
            f'({cfg.samplerate * 2} Hz > {STREAMING_CEILING_HZ} Hz)'
        )


# ===========================================================================
# Overflow and degraded frames: shown and stored, not trended or alarmed on
# ===========================================================================

def test_overflow_and_degraded_flags_survive_hdf5_round_trip(tmp_path):
    """The overflow and degraded flags are written to HDF5 and read back."""
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


def test_overflow_and_degraded_frames_excluded_from_trend():
    """A clipped or degraded frame does not become a trend point."""
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


def test_anomaly_hook_ignores_overflow_and_degraded_frames():
    """A clipped or degraded frame does not fire the RMS hook.

    A clipped frame reads high, with harmonic distortion.
    """
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


def test_overflow_frames_do_not_poison_anomaly_baseline():
    """A clipped frame does not move the EWMA baseline."""
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


def test_monitor_writer_stores_overflow_and_degraded_flags(tmp_path):
    """monitor.writer._write_channel_group stores the overflow and degraded flags."""
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


def test_overflow_mask_latched_across_block_accumulation():
    """An overflow in a callback that does not complete a block is kept (latched)."""
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

    # Fill the driver buffer with a constant 1000 counts.
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


def test_overflow_warns_once_per_channel_per_stream(caplog):
    """Sustained clipping logs one warning per channel, not one per callback.

    The warning is armed again when the channel stops clipping, so a new
    overflow event logs again. A warning in each callback would fill the
    rotating log during the event that the operator must diagnose.
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
# The Acquisition dialog preview uses the AcquisitionSettings formulas
# ===========================================================================

@pytest.mark.parametrize('maxfreq', [200, 500, 1000, 2000, 5000, 10000])
@pytest.mark.parametrize('binsize', [0.5, 2.0, 10.0])
def test_acquisition_dialog_preview_matches_settings(maxfreq, binsize):
    """derive_acquisition_preview gives the same values as AcquisitionSettings."""
    pytest.importorskip("dearpygui")
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
# The PSD cache key includes the bin size and the sample rate
# ===========================================================================

def test_psd_cache_invalidates_on_binsize_change():
    """A bin size change from 0.5 Hz to 8 Hz recomputes the spectrum.

    The test makes the bins coarser, because a stored block cannot give bins
    finer than its length allows.
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


def test_resolution_never_claimed_finer_than_the_record_supports():
    """A stored block is not re-binned finer than its own length allows."""
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


def test_psd_cache_invalidates_on_samplerate_change():
    """A sample with a different sample rate does not use a cached PSD."""
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
# The stated line count and bin width match the computed spectrum
# (CONTRIBUTING.md, "E11. Display rate, block size and line count")
# ===========================================================================

@pytest.mark.parametrize('maxfreq', [200, 500, 1000, 2000])
@pytest.mark.parametrize('binsize', [0.5, 2.0, 5.0, 20.0, 100.0])
def test_line_count_matches_computed_spectrum(maxfreq, binsize):
    """config.n_fft_bins equals the number of lines that Welch returns."""
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
def test_actual_bin_width_is_at_least_as_fine_as_requested(maxfreq, binsize):
    """The delivered bin width is not coarser than requested; binsize_actual states it."""
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
# The spectrum and the peaks stop at F_max
# ===========================================================================

@pytest.mark.parametrize('maxfreq', [200, 1000, 2000])
def test_spectrum_truncated_at_maxfreq(maxfreq):
    """The guard band between F_max and fs/2 is not displayed.

    In the guard band the anti-alias filter is not at full attenuation.
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


def test_peaks_exclude_the_guard_band():
    """No peak is reported in the guard band, also for a 5x stronger tone there."""
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
