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

import time

import numpy as np
import pytest

import rev80 as vc
from rev80.picoscope import PicoScopeStream

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
