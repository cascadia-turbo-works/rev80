"""
Hardware integration tests for PicoScope 4000A.

Requires a PicoScope 4000A with its signal generator output looped back
to Channel A.  Tests are automatically skipped if no hardware is detected.

Run hardware tests only:
    pytest tests/test_picoscope_hw.py -v

Run alongside the full suite (hardware tests skip if scope absent):
    pytest tests/ -v
"""

import ctypes
import time

import numpy as np
import pytest

import vibechecker as vc
from vibechecker.picoscope import PicoScopeStream

# ---------------------------------------------------------------------------
# Signal generator parameters  (siggen output → Channel A loopback)
# ---------------------------------------------------------------------------
SIGGEN_FREQ_HZ   = 500.0
SIGGEN_PKTOPK_UV = 1_000_000   # 1.0 Vpp (0.5 V amplitude)
SIGGEN_OFFSET_UV = 0            # AC-coupled input — offset stripped by coupling cap
CHANNEL_RANGE    = 8            # PS4000A_5V (index 8, ±5 V)

# Tolerance for FFT peak identification
FREQ_TOL_HZ = 20.0              # acceptable deviation from SIGGEN_FREQ_HZ

STREAM_SAMPLERATE = 50_000      # 50 kHz → Nyquist 25 kHz, resolves 500 Hz cleanly
STREAM_BLOCKSIZE  = 50_000      # 1 s capture window

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
    return any(not s.is_simulation for s in vc.VibeSensor.find())


def _get_hardware_sensor() -> vc.VibeSensor | None:
    for s in vc.VibeSensor.find():
        if not s.is_simulation:
            return s
    return None


hardware_skip = pytest.mark.skipif(
    not _hardware_available(),
    reason='No PicoScope hardware detected — connect scope and retry',
)


def _make_stream_config() -> vc.AcquisitionSettings:
    """Return AcquisitionSettings tuned for 500 Hz detection at 50 kHz."""
    cfg = vc.AcquisitionSettings()
    # Set samplerate and blocksize directly to avoid setter cascades
    cfg._fs = STREAM_SAMPLERATE
    cfg._ns = STREAM_BLOCKSIZE
    cfg.butter_fc     = 10.0      # remove DC; well below 500 Hz
    cfg.voltage_range = CHANNEL_RANGE
    cfg.coupling      = 'AC'
    return cfg


def _collect_with_siggen(siggen_cfg: dict | None = SIGGEN_CFG) -> vc.VibeSample | None:
    """
    Collect one VibeSample via the full DataCollector pipeline with siggen loopback.
    The siggen is started on the same device handle as streaming.
    Always disconnects and closes the device before returning.
    """
    sensor = _get_hardware_sensor()
    if sensor is None:
        return None
    config = _make_stream_config()
    dc = vc.DataCollector(config=config)
    dc.connect_sensor(sensor, siggen_config=siggen_cfg)
    try:
        return dc.collect_sample()
    finally:
        dc.disconnect_sensor()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@hardware_skip
class TestPicoScopeHardwareStream:

    sample: vc.VibeSample

    @classmethod
    def setup_class(cls):
        """Collect one shared sample for tests that only need a single capture."""
        sample = _collect_with_siggen()
        assert sample is not None, (
            'setup_class: no sample collected — verify scope connection and loopback cable'
        )
        cls.sample = sample

    def test_collect_sample_returns_vibesample(self):
        """Full pipeline via PicoScopeStream with siggen loopback."""
        assert self.sample is not None, (
            'No sample received — verify scope connection and loopback cable'
        )
        assert isinstance(self.sample, vc.VibeSample)

    def test_sample_unit_is_mv(self):
        """PicoScopeStream must tag samples as mV."""
        assert self.sample.unit == 'mV'

    def test_sample_blocksize_matches_config(self):
        """sample.data length must equal the requested blocksize."""
        assert self.sample.blocksize == STREAM_BLOCKSIZE

    def test_siggen_loopback_produces_nonzero_signal(self):
        """Signal generator loopback must produce a measurable AC voltage (>50 mV peak)."""
        sensor = _get_hardware_sensor()
        config = _make_stream_config()
        config.butter_fc = None   # disable HP filter — keep raw signal level
        dc = vc.DataCollector(config=config)
        dc.connect_sensor(sensor, siggen_config=SIGGEN_CFG)
        try:
            sample = dc.collect_sample()
        finally:
            dc.disconnect_sensor()

        if sample is None:
            pytest.skip('Hardware unavailable')

        peak_mv = np.max(np.abs(sample.data))
        assert peak_mv > 50.0, (
            f'Peak signal only {peak_mv:.1f} mV — siggen loopback may not be connected. '
            f'Expected ~{SIGGEN_PKTOPK_UV / 2000:.0f} mV amplitude'
        )

    def test_fft_peak_at_siggen_frequency(self):
        """
        End-to-end: siggen → Channel A → PicoScopeStream → VibeSample.fft()
        must return dominant peak at SIGGEN_FREQ_HZ ± FREQ_TOL_HZ.
        """
        cfg = _make_stream_config()
        fft_df, peaks = self.sample.fft(cfg)
        assert fft_df is not None and peaks is not None, 'fft() returned None'
        assert len(peaks) > 0, 'No peaks found in FFT'

        top_freq = float(fft_df.iloc[peaks[0]]['freq'])
        assert abs(top_freq - SIGGEN_FREQ_HZ) <= FREQ_TOL_HZ, (
            f'Dominant peak at {top_freq:.1f} Hz, expected {SIGGEN_FREQ_HZ} Hz '
            f'(±{FREQ_TOL_HZ} Hz). Check siggen loopback.'
        )

    def test_samplerate_close_to_requested(self):
        """PS4000A achieves the requested sample rate within 5 %."""
        deviation = abs(self.sample.samplerate - STREAM_SAMPLERATE) / STREAM_SAMPLERATE
        assert deviation < 0.05, (
            f'sample.samplerate={self.sample.samplerate} deviates more than 5 % from '
            f'requested {STREAM_SAMPLERATE}'
        )

    def test_stream_start_stop_cycle(self):
        """start() / stop() / start() cycle must reuse the device handle without error."""
        config = _make_stream_config()
        received = []
        stream = PicoScopeStream(config, lambda s: received.append(s),
                                  siggen_config=SIGGEN_CFG)
        block_duration = STREAM_BLOCKSIZE / STREAM_SAMPLERATE  # 1 s

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
