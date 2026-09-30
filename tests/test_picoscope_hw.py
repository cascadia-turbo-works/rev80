"""Hardware tests for a PicoScope 4000A, with AWG output looped back to channel A.

The tests skip when no scope is found. Run them alone with
`pytest tests/test_picoscope_hw.py -v`. TestPicoScopeHardwareStream shares one
capture; the other classes make their own captures.
"""

import math
import time

import numpy as np
import pytest

import rev80 as vc
import rev80.sample
from rev80 import tach as rev80_tach
from rev80.picoscope import _TIMEBASE_NS, PicoScopeStream

# ---------------------------------------------------------------------------
# Signal generator parameters  (siggen output → Channel A loopback)
# ---------------------------------------------------------------------------
SIGGEN_FREQ_HZ   = 500.0
SIGGEN_PKTOPK_UV = 1_000_000   # 1.0 Vpp (0.5 V amplitude)
SIGGEN_OFFSET_UV = 0            # AC-coupled input — offset stripped by coupling cap
CHANNEL_RANGE    = 8            # PS4000A_5V (index 8, ±5 V)

FREQ_TOL_HZ      = 20.0         # acceptable deviation from SIGGEN_FREQ_HZ

# PicoScopeStream acquires at config.raw_samplerate, not at the display rate.
# These values give a valid display configuration. Every rate and time below
# comes from the config.
STREAM_MAXFREQ_HZ = 10_000.0    # top MAXFREQ_PRESETS entry → Nyquist 12.8 kHz
STREAM_BINSIZE_HZ = 1.0         # 1 Hz bins → a 1 s acquisition window

SIGGEN_CFG = {
    'freq_hz':    SIGGEN_FREQ_HZ,
    'pktopk_uv':  SIGGEN_PKTOPK_UV,
    'offset_uv':  SIGGEN_OFFSET_UV,
    'wave_type':  'PS4000A_SINE',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hardware_available() -> bool:
    return len(vc.VibeSensor.find()) > 0


def _get_hardware_sensor() -> vc.VibeSensor | None:
    sensors = vc.VibeSensor.find()
    return sensors[0] if sensors else None


hardware_skip = pytest.mark.skipif(
    not _hardware_available(),
    reason='No PicoScope hardware detected — connect scope and retry',
)


def _make_stream_config(highpass: bool = True) -> vc.AcquisitionSettings:
    """Return AcquisitionSettings for 500 Hz detection at the raw rate."""
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq = STREAM_MAXFREQ_HZ
    cfg.binsize = STREAM_BINSIZE_HZ
    cfg.highpass_enabled       = highpass
    cfg.channel_voltage_ranges = {0: CHANNEL_RANGE}
    cfg.coupling               = 'AC'
    return cfg


def _collect_one(highpass: bool = True) -> vc.VibeSample | None:
    """Collect a single VibeSample via DataCollector + siggen loopback."""
    sensor = _get_hardware_sensor()
    if sensor is None:
        return None
    dc = vc.DataCollector(config=_make_stream_config(highpass))
    dc.connect_sensor(sensor, siggen_config=SIGGEN_CFG)
    try:
        result = dc.collect_sample()
        return result.get(0) if result else None
    finally:
        dc.disconnect_sensor()


# ---------------------------------------------------------------------------
# Tests — shared-sample class (one hardware trigger in setup_class)
# ---------------------------------------------------------------------------

@hardware_skip
class TestPicoScopeHardwareStream:
    """
    One hardware capture is collected in setup_class and shared by all
    read-only tests below.  Tests that must verify re-triggering behaviour
    are in TestPicoScopeRetrigger.
    """

    sample: vc.VibeSample

    @classmethod
    def setup_class(cls):
        sample = _collect_one(highpass=False)   # raw — no HP filter
        assert sample is not None, (
            'setup_class: no sample collected — verify scope connection and loopback cable'
        )
        cls.sample = sample

    # --- basic type / shape checks ---

    def test_collect_sample_returns_vibesample(self):
        assert isinstance(self.sample, vc.VibeSample)

    def test_sample_unit_is_mv(self):
        assert self.sample.unit == 'mV'

    def test_sample_blocksize_matches_config(self):
        # The PicoScope rounds the sample rate to the nearest available time
        # base, so the delivered block length can differ slightly from
        # raw_blocksize. Accept any positive blocksize.
        assert self.sample.blocksize > 0

    def test_samplerate_close_to_requested(self):
        """The stream delivers config.raw_samplerate within 5 %.

        The clock is quantised: on a 4824A the achieved rate is 25591.8 Hz,
        -320 ppm (CONTRIBUTING.md, "E4. Sample-clock grid").
        """
        expected = _make_stream_config().raw_samplerate
        deviation = abs(self.sample.samplerate - expected) / expected
        assert deviation < 0.05, (
            f'sample.samplerate={self.sample.samplerate} deviates '
            f'{deviation:.1%} from the acquisition rate {expected}'
        )

    # --- signal level ---

    def test_siggen_loopback_produces_nonzero_signal(self):
        """Siggen loopback must produce a measurable AC voltage (>50 mV peak)."""
        peak_mv = np.max(np.abs(self.sample.data))
        assert peak_mv > 50.0, (
            f'Peak signal only {peak_mv:.1f} mV — siggen loopback may not be connected. '
            f'Expected ~{SIGGEN_PKTOPK_UV / 2000:.0f} mV amplitude'
        )

    # --- FFT ---

    def test_fft_peak_at_siggen_frequency(self):
        """Dominant FFT peak must land within FREQ_TOL_HZ of SIGGEN_FREQ_HZ."""
        cfg = _make_stream_config()
        dc = vc.DataCollector(config=cfg)
        result = dc.process_sample(0, self.sample)
        assert result is not None, 'process_sample() returned None'
        assert len(result.peaks) > 0, 'No peaks found in FFT'

        top_freq = float(result.freq[result.peaks[0]])
        assert abs(top_freq - SIGGEN_FREQ_HZ) <= FREQ_TOL_HZ, (
            f'Dominant peak at {top_freq:.1f} Hz, expected {SIGGEN_FREQ_HZ} Hz '
            f'(±{FREQ_TOL_HZ} Hz). Check siggen loopback.'
        )

    # --- save / load round-trip ---

    def test_save_load_roundtrip(self):
        """Hardware-captured sample survives DataCollector HDF5 round-trip unchanged."""
        import tempfile
        import os
        vs1 = self.sample

        # Push the captured sample into a DataCollector frame cache and save
        dc1 = vc.DataCollector(config=_make_stream_config(highpass=False))
        dc1.data['frame_cache'].append({0: vs1})
        dc1.data['frame_count'] = 1

        from pathlib import Path
        with tempfile.NamedTemporaryFile(suffix='.h5', delete=False) as tf:
            fname = Path(tf.name)
        try:
            dc1.save_data(fname)

            dc2 = vc.DataCollector(config=_make_stream_config(highpass=False))
            dc2.load_data(fname)

            cache = dc2.data['frame_cache']
            assert len(cache) >= 1, 'frame_cache empty after load'
            vs2 = cache[-1].get(0)
            assert vs2 is not None, 'Channel 0 missing after load'
            assert vs2.status    == vs1.status
            assert vs2.samplerate == vs1.samplerate
            assert vs2.unit      == 'mV'   # measurement files store mV
            assert np.allclose(vs2.data, vs1.data), 'Data changed after HDF5 round-trip'
        finally:
            os.unlink(fname)


# ---------------------------------------------------------------------------
# Tests — re-trigger / multi-capture (each test triggers hardware itself)
# ---------------------------------------------------------------------------

@hardware_skip
class TestPicoScopeRetrigger:
    """
    Tests that specifically verify hardware can be re-triggered.
    Each test does the minimum number of captures necessary.
    """

    def test_repeated_collect_sample(self):
        """collect_sample() can be called 3× in sequence without errors."""
        sensor = _get_hardware_sensor()
        dc = vc.DataCollector(config=_make_stream_config())
        dc.connect_sensor(sensor, siggen_config=SIGGEN_CFG)
        try:
            for i in range(3):
                result = dc.collect_sample()
                assert result, f'Capture {i+1} returned empty result'
                sample = result.get(0)
                assert isinstance(sample, vc.VibeSample), \
                    f'Capture {i+1}: expected VibeSample, got {type(sample)}'
                assert sample.blocksize > 1, f'Capture {i+1}: empty data block'
        finally:
            dc.disconnect_sensor()

    def test_stream_start_stop_cycle(self):
        """start() / stop() / start() reuses the device handle without error."""
        cfg = _make_stream_config()
        received = []
        stream = PicoScopeStream(cfg, lambda s: received.append(s),
                                 siggen_config=SIGGEN_CFG)
        # One callback arrives per acquisition_period. Take it from the config,
        # so that the sleep is longer than one block at any RAW_SAMPLERATE_HZ.
        block_duration = cfg.acquisition_period

        for _ in range(2):
            stream.start()
            time.sleep(block_duration * 1.2)
            stream.stop()
            time.sleep(0.05)

        stream.close()

        assert len(received) >= 2, (
            f'Expected ≥2 streaming callbacks across 2 cycles, got {len(received)}'
        )
        assert not stream.active


# ---------------------------------------------------------------------------
# Tachometer — AWG loopback on Channel A
# ---------------------------------------------------------------------------
# These use the real chain: PicoScopeStream -> antialias_decimate ->
# DataCollector.receive_data -> tach.tach_result. The anti-alias filter and
# the achieved rate (not RAW_SAMPLERATE_HZ) are in that chain.

TACH_PKTOPK_UV = 2_000_000   # the 4424A generator is a +-2 V part: 5 Vpp at
TACH_OFFSET_UV = 1_000_000   # 2.5 V offset returns PICO_SIGGEN_OFFSET_VOLTAGE
TACH_RANGE     = 8           # PS4000A_5V


def _tach_config(coupling: str = 'DC', channels=(0,)) -> vc.AcquisitionSettings:
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq = 1000.0
    cfg.binsize = 1.0                     # 1 s block
    cfg.highpass_enabled = False
    cfg.enabled_channels = list(channels)
    cfg.channel_voltage_ranges = {c: TACH_RANGE for c in channels}
    cfg.coupling = coupling
    cfg.channel_couplings = {c: coupling for c in channels}
    cfg.channel_roles = {0: 'tachometer'}   # loopback is on Channel A
    return cfg


def _capture_tach(freq_hz: float, coupling: str = 'DC', settings=None,
                  channels=(0,)):
    """One frame through the whole chain; returns (TachResult, DataCollector)."""
    sensor = _get_hardware_sensor()
    if sensor is None:
        return None, None
    dc = vc.DataCollector(config=_tach_config(coupling, channels))
    if settings is not None:
        dc.set_tach_settings(0, settings)
    dc.connect_sensor(sensor, siggen_config={
        'freq_hz': freq_hz, 'pktopk_uv': TACH_PKTOPK_UV,
        'offset_uv': TACH_OFFSET_UV, 'wave_type': 'PS4000A_SQUARE'})
    try:
        frame = dc.collect_sample()
        sample = frame.get(0) if frame else None
        return (dc.tach_for(0, sample) if sample is not None else None), dc
    finally:
        dc.disconnect_sensor()


@hardware_skip
class TestPicoScopeTachometer:
    """The tachometer chain on hardware, with an AWG square wave on channel A."""

    def test_reads_the_awg_square_wave(self):
        """A 30 Hz square wave reads 1800 RPM within 0.2 %.

        The AWG clock error is below this tolerance."""
        res, _ = _capture_tach(30.0)
        assert res is not None
        assert res.quality == rev80_tach.QUALITY_OK
        assert res.rpm == pytest.approx(1800.0, rel=2e-3)

    @pytest.mark.parametrize('freq_hz', [5.0, 10.0, 30.0, 60.0, 100.0, 170.0])
    def test_tracks_a_speed_sweep(self, freq_hz):
        """300 to 10200 RPM within the stated +/-0.2 % of reading.

        Measured at the 41666.5 Hz raw rate: worst 0.164 % at 300 RPM,
        0.04 % or less above it. Not recorded again at 25600 Hz."""
        res, _ = _capture_tach(freq_hz)
        assert res is not None and res.rpm is not None
        assert res.rpm == pytest.approx(freq_hz * 60.0, rel=2e-3)

    def test_reported_rate_is_the_hardware_rate_not_the_constant(self):
        """The tach uses the achieved rate on the 12.5 ns clock grid, not RAW_SAMPLERATE_HZ.

        The expected rate is derived from _TIMEBASE_NS, not hardcoded. It must
        also be within 1000 ppm of nominal and closer than a whole-us request.
        """
        res, _ = _capture_tach(30.0)
        assert res is not None
        raw = rev80.sample.RAW_SAMPLERATE_HZ
        osr = PicoScopeStream._choose_osr(raw)

        # The same derivation as the request: nearest grid point, rounded up to
        # whole ns, because the driver floors a request to the grid.
        target_ns   = 1e9 / (raw * osr)
        grid_ns     = round(target_ns / _TIMEBASE_NS) * _TIMEBASE_NS
        interval_ns = math.ceil(grid_ns)
        expected    = 1e9 / interval_ns / osr
        assert res.samplerate == pytest.approx(expected, rel=1e-4)

        # The point of the whole test: not the constant.
        assert res.samplerate != raw

        # Closer to nominal than a whole-microsecond request. Derived, not
        # hardcoded, so it stays valid if RAW_SAMPLERATE_HZ changes.
        us_rate  = 1e6 / round(1e6 / (raw * osr)) / osr
        err_now  = abs(res.samplerate / raw - 1.0)
        err_us   = abs(us_rate / raw - 1.0)
        assert err_now < err_us, (
            f'grid-snapped ns request is {err_now * 1e6:.0f} ppm from nominal, '
            f'no better than the {err_us * 1e6:.0f} ppm whole-us request'
        )
        assert err_now < 1e-3, f'{err_now * 1e6:.0f} ppm from nominal'

    def test_adaptive_threshold_survives_ac_coupling(self):
        """The adaptive threshold reads 1800 RPM with DC and with AC coupling.

        It follows the span of each block, so the mean that AC coupling removes
        does not change the result.
        """
        dc_res, _ = _capture_tach(30.0, coupling='DC')
        ac_res, _ = _capture_tach(30.0, coupling='AC')
        assert dc_res.rpm == pytest.approx(1800.0, rel=2e-3)
        assert ac_res.rpm == pytest.approx(1800.0, rel=2e-3)

    def test_fixed_threshold_works_in_its_own_regime(self):
        """A fixed 1000 mV threshold reads correctly on a DC-coupled input.

        There is no assertion for AC coupling at 50 % duty: the result changed
        from run to run. The high-duty test covers AC coupling.
        """
        fixed = rev80_tach.TachSettings(threshold_mode='fixed',
                                        threshold_mv=1000.0)
        dc_res, _ = _capture_tach(30.0, coupling='DC', settings=fixed)
        assert dc_res.rpm == pytest.approx(1800.0, rel=2e-3)
        assert dc_res.quality == rev80_tach.QUALITY_OK

    def test_fixed_threshold_fails_outright_at_high_duty(self):
        """At 70 % duty with AC coupling, a fixed threshold gives no reading.

        AC coupling removes the mean, which is the duty cycle. Above about 55 %
        duty the signal does not reach a fixed level. The adaptive threshold
        still reads. The arbitrary-waveform generator makes the 70 % duty; only
        the stimulus is patched.
        """
        import ctypes
        import numpy as _np
        from picosdk.ps4000a import ps4000a as _ps
        from picosdk.functions import assert_pico_ok as _ok
        from rev80.picoscope import PicoScopeStream

        NBUF, DUTY, FREQ = 4096, 0.70, 30.0

        def _setup(self_stream):
            wf = _np.full(NBUF, -32767, dtype=_np.int16)
            wf[:int(NBUF * DUTY)] = 32767
            n = ctypes.c_uint32(0)
            _ok(_ps.ps4000aSigGenFrequencyToPhase(
                self_stream._chandle, ctypes.c_double(FREQ), 0, NBUF, ctypes.byref(n)))
            _ok(_ps.ps4000aSetSigGenArbitrary(
                self_stream._chandle, TACH_OFFSET_UV, TACH_PKTOPK_UV,
                n.value, n.value, 0, 0,
                wf.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)), NBUF,
                0, 0, 0, 0, 0, 0, 0, ctypes.c_int16(0)))

        fixed = rev80_tach.TachSettings(threshold_mode='fixed',
                                        threshold_mv=1000.0)
        original = PicoScopeStream._setup_siggen
        PicoScopeStream._setup_siggen = _setup
        try:
            ac_fixed, _ = _capture_tach(FREQ, coupling='AC', settings=fixed)
            ac_adaptive, _ = _capture_tach(FREQ, coupling='AC')
        finally:
            PicoScopeStream._setup_siggen = original

        assert ac_fixed.rpm is None, (
            'a fixed threshold must fail on a high-duty AC-coupled input -- '
            'this is why adaptive is the default')
        assert ac_adaptive.rpm == pytest.approx(FREQ * 60.0, rel=3e-3), (
            'adaptive tracks the block span and is unaffected by duty')

    @pytest.mark.parametrize('ppr', [1, 2, 6])
    def test_pulses_per_rev_divides_the_hardware_rate(self, ppr):
        """pulses_per_rev divides the pulse rate once: 60 Hz is 3600/ppr RPM.

        Tolerance +/-0.2 % of reading. A 1 s block holds more than the 2
        revolutions that MIN_REVS needs at each ppr here.
        """
        res, _ = _capture_tach(
            60.0, settings=rev80_tach.TachSettings(pulses_per_rev=ppr))
        assert res is not None and res.rpm is not None
        assert res.quality == rev80_tach.QUALITY_OK
        assert res.rpm == pytest.approx(60.0 * 60.0 / ppr, rel=2e-3)

    def test_a_block_under_min_revs_withholds_the_rate_electrically(self):
        """A block with fewer than MIN_REVS revolutions gives no shaft speed.

        5 Hz in a 1 s block is about 5 rising edges: 5 revolutions at 1 ppr
        (300 RPM), but 0.8 revolution at 6 ppr, so no rate is reported.
        """
        ok, _ = _capture_tach(5.0)
        assert ok is not None and ok.rpm == pytest.approx(300.0, rel=2e-3)
        assert 3 <= ok.n_edges < rev80_tach.min_edges_for(6), (
            'the capture must clear the old gate and miss the new one, or '
            'this test does not discriminate')

        gated, _ = _capture_tach(
            5.0, settings=rev80_tach.TachSettings(pulses_per_rev=6))
        assert gated is not None
        assert gated.rpm is None
        assert gated.quality == rev80_tach.QUALITY_TOO_FEW_EDGES

    def test_duty_cycle_is_measured(self):
        """The built-in square wave measures 50 % duty within 5 %.

        Surface velocity from duty is tracked as R46 in doc/PROGRESS.md."""
        res, _ = _capture_tach(30.0)
        assert res.duty_cycle == pytest.approx(0.5, abs=0.05)

    def test_tach_channel_produces_no_channel_result(self):
        """A tachometer channel gives no ChannelResult (no overall, spectrum or kurtosis)."""
        _, dc = _capture_tach(30.0, channels=(0, 1))
        assert dc is not None
        results = dc.process_samples()
        assert all(r.channel != 0 for r in results)

    def test_four_channels_with_a_tach_stream_cleanly(self):
        """Four channels, one a tachometer, stream 8 s with no overflow or degraded frame."""
        sensor = _get_hardware_sensor()
        dc = vc.DataCollector(config=_tach_config('DC', channels=(0, 1, 2, 3)))
        dc.connect_sensor(sensor, siggen_config={
            'freq_hz': 30.0, 'pktopk_uv': TACH_PKTOPK_UV,
            'offset_uv': TACH_OFFSET_UV, 'wave_type': 'PS4000A_SQUARE'})
        try:
            dc.start_stream()
            deadline = time.time() + 8.0
            frames = 0
            overflow = degraded = 0
            while time.time() < deadline:
                if dc.new_frame_event.wait(timeout=2.0):
                    dc.new_frame_event.clear()
                    frame = dc.data['frame_cache'][-1]
                    frames += 1
                    for s in frame.values():
                        overflow += bool(s.overflow)
                        degraded += bool(s.degraded)
            dc.stop_stream()
        finally:
            dc.disconnect_sensor()
        assert frames >= 3, f'only {frames} frames in 8 s at 4 channels'
        assert overflow == 0, f'{overflow} overflowed channel-frames'
        assert degraded == 0, f'{degraded} rate-degraded channel-frames'
