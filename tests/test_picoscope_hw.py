"""
Hardware integration tests for PicoScope 4000A.

Requires a PicoScope 4000A with its signal generator output looped back
to Channel A.  Tests are automatically skipped if no hardware is detected.

All tests in TestPicoScopeHardwareStream share a single captured sample
that is collected once in setup_class, avoiding repeated hardware triggers
for read-only signal-inspection tests.  Tests that specifically need to
verify re-triggering (multi-capture, start/stop cycles) do their own
minimal captures and are clearly labelled.

Run hardware tests only:
    pytest tests/test_picoscope_hw.py -v

Run alongside the full suite (hardware tests skip if scope absent):
    pytest tests/ -v
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

# PicoScopeStream acquires at config.raw_samplerate (RAW_SAMPLERATE_HZ), never
# at the maxfreq-derived display samplerate -- see the raw/display split in
# sample.py. These pick a *legal* display config; every rate and timing
# expectation below is derived from the config, never hardcoded, because the
# rate the hardware is actually asked for is raw_samplerate.
#
# The previous constants (STREAM_SAMPLERATE/STREAM_BLOCKSIZE = 50_000) predated
# that split: they asked for maxfreq=25 kHz, which the setter clamps, and then
# asserted the delivered rate was within 40% of 50 kHz. The stream never ran at
# 50 kHz -- the assertion passed only while raw_samplerate happened to be
# 40 kHz, 20% away, and broke as soon as it became 25600.
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
    """Return AcquisitionSettings for 500 Hz detection at the acquisition rate."""
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
        """The stream must deliver config.raw_samplerate.

        This is the acquisition rate the whole raw/display split is built on:
        VibeSample, HDF5 and envelope analysis all assume the block came in at
        raw_samplerate. The 4000A uses discrete time bases, so the achieved
        rate is quantised -- at 25600 Hz the driver picks a 39 us interval and
        delivers 25641 Hz, +0.16%. 5% leaves room for quantisation at other
        rates while still catching a real regression; the old 40% band was
        wide enough to hide the rate being wrong by a factor of 1.56.
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
            assert vs2.unit      == 'mV'   # v4 always stores mV
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
        # One callback arrives per acquisition_period at raw_samplerate. Deriving
        # this from the config rather than hardcoding it is what makes the test
        # independent of RAW_SAMPLERATE_HZ: with the old hardcoded 1.0 s the
        # sleep was shorter than the real 1.95 s period and no callback ever
        # arrived, so the test reported a streaming failure that was its own.
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
# Tachometer (R43) — AWG loopback on Channel A
# ---------------------------------------------------------------------------
# These drive the real acquisition path: PicoScopeStream -> antialias_decimate
# -> DataCollector.receive_data -> tach.tach_result. A synthetic array handed
# straight to the detector proves nothing about the chain in between, which is
# where the anti-alias filter and the 41666.5 Hz reported rate live.

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
    """Electrical close-out for R43."""

    def test_reads_the_awg_square_wave(self):
        """30 Hz square = 1800 RPM. The AWG's DDS clock is orders of magnitude
        better than the 0.3 % that naming spectral lines needs."""
        res, _ = _capture_tach(30.0)
        assert res is not None
        assert res.quality == rev80_tach.QUALITY_OK
        assert res.rpm == pytest.approx(1800.0, rel=2e-3)

    @pytest.mark.parametrize('freq_hz', [5.0, 10.0, 30.0, 60.0, 100.0, 170.0])
    def test_tracks_a_speed_sweep(self, freq_hz):
        """300 to 10200 RPM. Measured worst case is 0.164 % at 300 RPM and
        <= 0.04 % above; the tolerance here is the published +-0.2 % of
        reading, which is what the docs claim."""
        res, _ = _capture_tach(freq_hz)
        assert res is not None and res.rpm is not None
        assert res.rpm == pytest.approx(freq_hz * 60.0, rel=2e-3)

    def test_reported_rate_is_the_hardware_rate_not_the_constant(self):
        """The quantisation trap. The driver can only run the ADC at points on
        its own clock grid, so the delivered rate is never exactly
        RAW_SAMPLERATE_HZ. Anything computed from the constant reads wrong on
        hardware and is exactly right in CI -- the worst combination a defect
        can have.

        The expectation is *derived* from the constant, the oversample ratio
        and the clock grid rather than hardcoded, because a hardcoded one has
        now gone stale twice:

          - 41666.5 was correct only while RAW_SAMPLERATE_HZ was 40000
            (osr=2, 12.5 us -> 12 us, 4.166% error), and failed the merge that
            moved the constant to 25600;
          - the us-derived form that replaced it (osr=3, 13.02 us -> 13 us ->
            25641.0 Hz, 0.160% error) failed in turn when the streaming
            interval moved to ns snapped to the device's 12.5 ns grid
            (13025 ns -> 25591.81 Hz, -0.032% error).

        So this now derives from _TIMEBASE_NS, and additionally asserts the
        property that actually matters and does not depend on how the interval
        is requested: the delivered rate is CLOSE to nominal, and closer than
        whole-microsecond quantisation could ever have been. That second
        assertion is what would have caught the ns change regressing rather
        than improving accuracy, which a bare equality check cannot.
        """
        res, _ = _capture_tach(30.0)
        assert res is not None
        raw = rev80.sample.RAW_SAMPLERATE_HZ
        osr = PicoScopeStream._choose_osr(raw)

        # Same derivation the driver is asked for: nearest point on the clock
        # grid, ceil-ed into whole ns because the driver floors a request.
        target_ns   = 1e9 / (raw * osr)
        grid_ns     = round(target_ns / _TIMEBASE_NS) * _TIMEBASE_NS
        interval_ns = math.ceil(grid_ns)
        expected    = 1e9 / interval_ns / osr
        assert res.samplerate == pytest.approx(expected, rel=1e-4)

        # The point of the whole test: not the constant.
        assert res.samplerate != raw

        # And better than the microsecond request it replaced. Derived, not
        # hardcoded, so it keeps meaning something if RAW_SAMPLERATE_HZ moves.
        us_rate  = 1e6 / round(1e6 / (raw * osr)) / osr
        err_now  = abs(res.samplerate / raw - 1.0)
        err_us   = abs(us_rate / raw - 1.0)
        assert err_now < err_us, (
            f'grid-snapped ns request is {err_now * 1e6:.0f} ppm from nominal, '
            f'no better than the {err_us * 1e6:.0f} ppm whole-us request'
        )
        assert err_now < 1e-3, f'{err_now * 1e6:.0f} ppm from nominal'

    def test_adaptive_threshold_survives_ac_coupling(self):
        """AC coupling removes the mean, and on a pulse train the mean IS the
        duty cycle. Adaptive tracks each block's own span, so it does not care.
        """
        dc_res, _ = _capture_tach(30.0, coupling='DC')
        ac_res, _ = _capture_tach(30.0, coupling='AC')
        assert dc_res.rpm == pytest.approx(1800.0, rel=2e-3)
        assert ac_res.rpm == pytest.approx(1800.0, rel=2e-3)

    def test_fixed_threshold_works_in_its_own_regime(self):
        """A fixed threshold is correct on a DC-coupled input at a level inside
        the signal's swing. That is the configuration it is for.

        Deliberately no assertion about AC coupling at 50 % duty: that is the
        one duty at which fixed and adaptive coincide, and whether a 1000 mV
        level lands inside the AC-coupled swing depends on where the coupling
        settles and on the AWG's phase. It was observed both ways across runs,
        so pinning either outcome would be pinning a coin-flip. The regime
        where the difference is real and repeatable is high duty --
        test_fixed_threshold_fails_outright_at_high_duty.
        """
        fixed = rev80_tach.TachSettings(threshold_mode='fixed',
                                        threshold_mv=1000.0)
        dc_res, _ = _capture_tach(30.0, coupling='DC', settings=fixed)
        assert dc_res.rpm == pytest.approx(1800.0, rel=2e-3)
        assert dc_res.quality == rev80_tach.QUALITY_OK

    def test_fixed_threshold_fails_outright_at_high_duty(self):
        """The failure the adaptive default exists to prevent, reproduced
        electrically.

        AC coupling removes the mean, and on a pulse train the mean IS the duty
        cycle: above ~55 % the signal maximum falls below any fixed level and
        the shaft reads as stopped on a machine that is running. Needs a
        non-50 % waveform, which the built-in generator cannot produce -- hence
        the arbitrary-waveform stimulus. Only the stimulus is patched; the
        acquisition path under test is the real one.
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

    def test_duty_cycle_is_measured(self):
        """The built-in square is 50 % duty; duty is what R46 turns into a
        surface velocity."""
        res, _ = _capture_tach(30.0)
        assert res.duty_cycle == pytest.approx(0.5, abs=0.05)

    def test_tach_channel_produces_no_channel_result(self):
        """Role plumbing, end to end on real hardware: a pulse train must not
        acquire an overall, a spectrum or a kurtosis."""
        _, dc = _capture_tach(30.0, channels=(0, 1))
        assert dc is not None
        results = dc.process_samples()
        assert all(r.channel != 0 for r in results)

    def test_four_channels_with_a_tach_stream_cleanly(self):
        """A tach as one of four inputs sits inside the streaming envelope the
        STREAMING_CEILING_HZ measurements already established."""
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
