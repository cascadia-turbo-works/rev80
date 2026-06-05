"""Tests for Phase 2 anomaly detection hooks in vibechecker.monitor.anomaly."""
from datetime import datetime, timezone

import numpy as np
import pytest

from vibechecker.monitor.anomaly import (
    AnomalyEvent,
    CompositeAnomalyHook,
    NullAnomalyHook,
    RmsThresholdHook,
    SpectralThresholdHook,
)
from vibechecker.sample import ChannelResult


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_result(channel=0, overall=0.1, n=64, samplerate=1000):
    freq = np.linspace(0, samplerate / 2, n // 2 + 1)
    spectrum = np.ones_like(freq) * 0.01
    return ChannelResult(
        channel=channel,
        unit='mV',
        overflow=False,
        time_data=np.ones(n) * overall,
        time_vec=np.arange(n) / samplerate,
        samplerate=samplerate,
        freq=freq,
        spectrum=spectrum,
        peaks=np.array([], dtype=int),
        overall=overall,
        timestamp=datetime.now(timezone.utc),
        rel_time=0.0,
        status='OKAY',
    )


def _send_frames(hook, results_list, n_frames):
    """Send n_frames identical result lists through the hook; return last event."""
    event = None
    for _ in range(n_frames):
        event = hook.on_results(results_list, frame_cache=None)
    return event


# ---------------------------------------------------------------------------
# RmsThresholdHook tests
# ---------------------------------------------------------------------------

class TestRmsThresholdHook:

    def test_rms_no_trigger_during_warmup(self):
        """29 frames at a fixed level must not trigger (min_baseline_samples=30)."""
        hook = RmsThresholdHook(
            rms_threshold_pct=10.0,
            consecutive_n=3,
            min_baseline_samples=30,
        )
        results = [_make_result(channel=0, overall=1.0)]
        # Send 29 frames — still inside warmup window
        events = [hook.on_results(results, None) for _ in range(29)]
        assert all(e is None for e in events)

    def test_rms_triggers_after_consecutive_n(self):
        """After warmup, exactly N consecutive above-threshold frames should fire."""
        consecutive_n = 3
        min_samples = 30
        hook = RmsThresholdHook(
            rms_threshold_pct=10.0,
            consecutive_n=consecutive_n,
            baseline_alpha=0.97,
            min_baseline_samples=min_samples,
        )
        baseline_val = 1.0
        results_normal = [_make_result(channel=0, overall=baseline_val)]

        # Burn through warmup at normal level
        for _ in range(min_samples):
            hook.on_results(results_normal, None)

        # Send N-1 above-threshold frames — should NOT fire yet
        high_val = baseline_val * 2.0  # 100 % above — well over 10 % threshold
        results_high = [_make_result(channel=0, overall=high_val)]
        for i in range(consecutive_n - 1):
            event = hook.on_results(results_high, None)
            assert event is None, f"Unexpected trigger at frame {i + 1}"

        # N-th frame should fire
        event = hook.on_results(results_high, None)
        assert event is not None
        assert isinstance(event, AnomalyEvent)
        assert event.channel == 0

    def test_rms_resets_on_normal_frame(self):
        """Counter resets when a below-threshold frame is seen; no trigger."""
        consecutive_n = 3
        min_samples = 30
        hook = RmsThresholdHook(
            rms_threshold_pct=10.0,
            consecutive_n=consecutive_n,
            baseline_alpha=0.97,
            min_baseline_samples=min_samples,
        )
        baseline_val = 1.0
        results_normal = [_make_result(channel=0, overall=baseline_val)]

        # Warmup
        for _ in range(min_samples):
            hook.on_results(results_normal, None)

        high_val = baseline_val * 2.0
        results_high = [_make_result(channel=0, overall=high_val)]

        # Send N-1 above-threshold frames
        for _ in range(consecutive_n - 1):
            assert hook.on_results(results_high, None) is None

        # Inject one normal frame — counter resets
        assert hook.on_results(results_normal, None) is None

        # Send N-1 above-threshold again — still should not trigger
        for _ in range(consecutive_n - 1):
            assert hook.on_results(results_high, None) is None

    def test_rms_trigger_reason_string(self):
        """Triggered event.reason must be a non-empty string."""
        min_samples = 5
        consecutive_n = 2
        hook = RmsThresholdHook(
            rms_threshold_pct=10.0,
            consecutive_n=consecutive_n,
            baseline_alpha=0.97,
            min_baseline_samples=min_samples,
        )
        results_normal = [_make_result(channel=0, overall=1.0)]
        for _ in range(min_samples):
            hook.on_results(results_normal, None)

        results_high = [_make_result(channel=0, overall=10.0)]
        event = None
        for _ in range(consecutive_n):
            event = hook.on_results(results_high, None)

        assert event is not None
        assert isinstance(event.reason, str)
        assert len(event.reason) > 0

    def test_rms_reset_baseline_clears_state(self):
        """After reset_baseline(), sending one frame must NOT trigger (warmup restarted)."""
        min_samples = 5
        hook = RmsThresholdHook(
            rms_threshold_pct=10.0,
            consecutive_n=2,
            baseline_alpha=0.97,
            min_baseline_samples=min_samples,
        )
        results_normal = [_make_result(channel=0, overall=1.0)]
        # Complete warmup
        for _ in range(min_samples):
            hook.on_results(results_normal, None)

        hook.reset_baseline()

        # One frame after reset — still in warmup, must not trigger
        results_high = [_make_result(channel=0, overall=100.0)]
        event = hook.on_results(results_high, None)
        assert event is None

    def test_rms_multichannel_triggers_on_first(self):
        """Only ch1 above threshold — returned event.channel == 1."""
        min_samples = 5
        consecutive_n = 2
        hook = RmsThresholdHook(
            rms_threshold_pct=10.0,
            consecutive_n=consecutive_n,
            baseline_alpha=0.97,
            min_baseline_samples=min_samples,
        )
        results_normal_ch0 = _make_result(channel=0, overall=1.0)
        results_normal_ch1 = _make_result(channel=1, overall=1.0)

        # Warmup both channels
        for _ in range(min_samples):
            hook.on_results([results_normal_ch0, results_normal_ch1], None)

        # ch0 stays normal, ch1 goes high
        ch0_normal = _make_result(channel=0, overall=1.0)
        ch1_high = _make_result(channel=1, overall=10.0)

        event = None
        for _ in range(consecutive_n):
            event = hook.on_results([ch0_normal, ch1_high], None)

        assert event is not None
        assert event.channel == 1


# ---------------------------------------------------------------------------
# SpectralThresholdHook tests
# ---------------------------------------------------------------------------

def _make_spectral_result(channel=0, spectrum_scale=1.0, n=64, samplerate=1000):
    """ChannelResult with a flat spectrum of spectrum_scale amplitude."""
    freq = np.linspace(0, samplerate / 2, n // 2 + 1)
    spectrum = np.ones_like(freq) * spectrum_scale
    return ChannelResult(
        channel=channel, unit='mV', overflow=False,
        time_data=np.ones(n), time_vec=np.arange(n) / samplerate,
        samplerate=samplerate, freq=freq, spectrum=spectrum,
        peaks=np.array([], dtype=int), overall=spectrum_scale,
        timestamp=datetime.now(timezone.utc), rel_time=0.0, status='OKAY',
    )


class TestSpectralThresholdHook:

    def test_warmup_suppresses_triggers(self):
        """During warmup (min_baseline_samples frames not yet seen), never triggers."""
        hook = SpectralThresholdHook(
            spectral_threshold_pct=10.0,
            consecutive_n=1,
            min_baseline_samples=5,
        )
        # Feed huge spectrum — should still not trigger during warmup
        results = [_make_spectral_result(channel=0, spectrum_scale=1000.0)]
        events = [hook.on_results(results, None) for _ in range(4)]
        assert all(e is None for e in events)

    def test_triggers_above_threshold(self):
        """After set_baseline seeds the EWMA, sustained 10× excess triggers."""
        hook = SpectralThresholdHook(
            spectral_threshold_pct=50.0,   # 50% deviation threshold
            consecutive_n=3,
            baseline_alpha=0.99,
            min_baseline_samples=1,
        )
        # Seed baseline at scale=0.01
        hook.set_baseline([_make_spectral_result(channel=0, spectrum_scale=0.01)])

        # Feed 10× the baseline (1000% deviation, way above 50% threshold)
        high = _make_spectral_result(channel=0, spectrum_scale=0.1)
        event = None
        for _ in range(3):
            event = hook.on_results([high], None)

        assert event is not None
        assert isinstance(event, AnomalyEvent)
        assert event.channel == 0
        assert 'Spectral' in event.reason

    def test_no_trigger_below_threshold(self):
        """Deviation below threshold never triggers even over many frames."""
        hook = SpectralThresholdHook(
            spectral_threshold_pct=100.0,  # need 100% deviation to trigger
            consecutive_n=3,
            baseline_alpha=0.99,
            min_baseline_samples=1,
        )
        hook.set_baseline([_make_spectral_result(channel=0, spectrum_scale=0.01)])

        # 1.5× baseline = 50% deviation — below 100% threshold
        low = _make_spectral_result(channel=0, spectrum_scale=0.015)
        events = [hook.on_results([low], None) for _ in range(5)]
        assert all(e is None for e in events)

    def test_fmin_fmax_masks_out_of_band_excess(self):
        """Excess only outside [fmin, fmax] must not trigger."""
        n, samplerate = 64, 1000
        freq = np.linspace(0, samplerate / 2, n // 2 + 1)

        hook = SpectralThresholdHook(
            spectral_threshold_pct=50.0,
            consecutive_n=3,
            baseline_alpha=0.99,
            min_baseline_samples=1,
            fmin=100.0,
            fmax=200.0,
        )

        baseline_spectrum = np.ones_like(freq) * 0.01
        hook.set_baseline([ChannelResult(
            channel=0, unit='mV', overflow=False,
            time_data=np.ones(n), time_vec=np.arange(n) / samplerate,
            samplerate=samplerate, freq=freq, spectrum=baseline_spectrum,
            peaks=np.array([], dtype=int), overall=0.01,
            timestamp=datetime.now(timezone.utc), rel_time=0.0, status='OKAY',
        )])

        # Massive excess but only above 400 Hz — outside the [100, 200] band
        out_of_band = baseline_spectrum.copy()
        out_of_band[freq > 400.0] = 100.0

        result = ChannelResult(
            channel=0, unit='mV', overflow=False,
            time_data=np.ones(n), time_vec=np.arange(n) / samplerate,
            samplerate=samplerate, freq=freq, spectrum=out_of_band,
            peaks=np.array([], dtype=int), overall=1.0,
            timestamp=datetime.now(timezone.utc), rel_time=0.0, status='OKAY',
        )
        events = [hook.on_results([result], None) for _ in range(5)]
        assert all(e is None for e in events)

    def test_none_fmin_fmax_uses_full_range(self):
        """fmin=None, fmax=None (YAML null) covers the full spectrum."""
        hook = SpectralThresholdHook(
            spectral_threshold_pct=50.0,
            consecutive_n=2,
            baseline_alpha=0.99,
            min_baseline_samples=1,
            fmin=None,
            fmax=None,
        )
        hook.set_baseline([_make_spectral_result(channel=0, spectrum_scale=0.01)])
        high = _make_spectral_result(channel=0, spectrum_scale=1.0)  # 100× = 9900%
        event = None
        for _ in range(2):
            event = hook.on_results([high], None)
        assert event is not None

    def test_reset_clears_ewma_and_reenters_warmup(self):
        """After reset_baseline(), the hook re-enters warmup and won't trigger."""
        hook = SpectralThresholdHook(
            spectral_threshold_pct=50.0,
            consecutive_n=1,
            baseline_alpha=0.99,
            min_baseline_samples=3,
        )
        hook.set_baseline([_make_spectral_result(channel=0, spectrum_scale=0.01)])
        hook.reset_baseline()

        # Massive spectrum — but back in warmup, no trigger
        high = _make_spectral_result(channel=0, spectrum_scale=1000.0)
        events = [hook.on_results([high], None) for _ in range(2)]
        assert all(e is None for e in events)


# ---------------------------------------------------------------------------
# CompositeAnomalyHook tests
# ---------------------------------------------------------------------------

class TestCompositeAnomalyHook:

    def test_composite_returns_first_event(self):
        """RMS hook fires first; event.reason should mention 'RMS'."""
        rms_hook = RmsThresholdHook(
            rms_threshold_pct=10.0,
            consecutive_n=2,
            min_baseline_samples=5,
        )
        spectral_hook = SpectralThresholdHook(spectral_threshold_pct=50.0, consecutive_n=2)
        composite = CompositeAnomalyHook([rms_hook, spectral_hook])

        results_normal = [_make_result(channel=0, overall=1.0)]
        for _ in range(5):
            composite.on_results(results_normal, None)

        results_high = [_make_result(channel=0, overall=10.0)]
        event = None
        for _ in range(2):
            event = composite.on_results(results_high, None)

        assert event is not None
        assert 'RMS' in event.reason

    def test_composite_falls_through(self):
        """Two NullAnomalyHooks → composite always returns None."""
        composite = CompositeAnomalyHook([NullAnomalyHook(), NullAnomalyHook()])
        result = composite.on_results([_make_result()], None)
        assert result is None

    def test_composite_reset_baseline_propagates(self):
        """reset_baseline() should be called on both child hooks."""
        rms_hook = RmsThresholdHook(min_baseline_samples=5, consecutive_n=2)
        spectral_hook = SpectralThresholdHook(consecutive_n=2)
        composite = CompositeAnomalyHook([rms_hook, spectral_hook])

        # Warm up rms_hook
        results = [_make_result(channel=0, overall=1.0)]
        for _ in range(5):
            composite.on_results(results, None)

        # Set spectral baseline (seeds EWMA and skips warmup)
        spectral_hook.set_baseline(results)
        assert spectral_hook._n_samples.get(0, 0) >= spectral_hook._min_samples

        composite.reset_baseline()

        # After reset: EWMA state should be cleared
        assert spectral_hook._n_samples.get(0, 0) == 0

        # After reset: rms_hook warmup should restart — sending one huge frame
        # must not trigger since we are back in warmup
        results_high = [_make_result(channel=0, overall=1000.0)]
        event = composite.on_results(results_high, None)
        assert event is None
