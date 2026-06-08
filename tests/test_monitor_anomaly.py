"""Tests for Phase 2 anomaly detection hooks in vibechecker.monitor.anomaly."""
import logging
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from vibechecker.monitor.anomaly import (
    AnomalyEvent,
    CompositeAnomalyHook,
    FixedThresholdHook,
    NullAnomalyHook,
    RmsThresholdHook,
    SpectralThresholdHook,
)
from vibechecker.sample import ChannelResult


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_result(channel=0, overall=0.1, n=64, samplerate=1000, unit='mV', rel_time=0.0):
    freq = np.linspace(0, samplerate / 2, n // 2 + 1)
    spectrum = np.ones_like(freq) * 0.01
    return ChannelResult(
        channel=channel,
        unit=unit,
        overflow=False,
        time_data=np.ones(n) * overall,
        time_vec=np.arange(n) / samplerate,
        samplerate=samplerate,
        freq=freq,
        spectrum=spectrum,
        peaks=np.array([], dtype=int),
        overall=overall,
        timestamp=datetime.now(timezone.utc),
        rel_time=rel_time,
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


# ---------------------------------------------------------------------------
# RmsThresholdHook — t=0 / streak-start tracking
# ---------------------------------------------------------------------------

class TestRmsStreakTracking:
    """The hook must remember the *first* anomalous frame as the t=0 reference,
    even though the event only fires `consecutive_n` frames later."""

    def test_trigger_rel_time_is_first_anomalous_frame(self):
        consecutive_n = 3
        min_samples = 5
        hook = RmsThresholdHook(
            rms_threshold_pct=10.0,
            consecutive_n=consecutive_n,
            min_baseline_samples=min_samples,
        )
        results_normal = [_make_result(channel=0, overall=1.0, rel_time=0.0)]
        for _ in range(min_samples):
            hook.on_results(results_normal, None)

        t0 = 100.0
        results_high_t0 = [_make_result(channel=0, overall=10.0, rel_time=t0)]
        results_high_t1 = [_make_result(channel=0, overall=10.0, rel_time=t0 + 1.0)]
        results_high_t2 = [_make_result(channel=0, overall=10.0, rel_time=t0 + 2.0)]

        assert hook.on_results(results_high_t0, None) is None
        assert hook.on_results(results_high_t1, None) is None
        event = hook.on_results(results_high_t2, None)

        assert event is not None
        assert event.trigger_rel_time == pytest.approx(t0)

    def test_trigger_time_captured_at_streak_start_not_at_fire(self):
        consecutive_n = 3
        min_samples = 5
        hook = RmsThresholdHook(
            rms_threshold_pct=10.0,
            consecutive_n=consecutive_n,
            min_baseline_samples=min_samples,
        )
        results_normal = [_make_result(channel=0, overall=1.0)]
        for _ in range(min_samples):
            hook.on_results(results_normal, None)

        results_high = [_make_result(channel=0, overall=10.0)]

        before_streak = datetime.now(timezone.utc)
        hook.on_results(results_high, None)               # frame 1 — streak starts
        after_streak_start = datetime.now(timezone.utc)
        time.sleep(0.05)
        hook.on_results(results_high, None)               # frame 2
        time.sleep(0.05)
        event = hook.on_results(results_high, None)       # frame 3 — fires

        assert event is not None
        # trigger_time reflects when the streak STARTED, not when the hook fired
        assert before_streak <= event.trigger_time <= after_streak_start
        assert event.trigger_time < datetime.now(timezone.utc) - timedelta(seconds=0.05)

    def test_streak_resets_on_normal_frame_clears_t0(self):
        """A below-threshold frame mid-streak clears the remembered t=0 reference."""
        consecutive_n = 3
        min_samples = 5
        hook = RmsThresholdHook(
            rms_threshold_pct=10.0,
            consecutive_n=consecutive_n,
            baseline_alpha=1.0,   # frozen baseline — isolates streak logic from EWMA drift
            min_baseline_samples=min_samples,
        )
        results_normal = [_make_result(channel=0, overall=1.0, rel_time=0.0)]
        for _ in range(min_samples):
            hook.on_results(results_normal, None)

        results_high_a = [_make_result(channel=0, overall=10.0, rel_time=10.0)]
        hook.on_results(results_high_a, None)
        assert 0 in hook._streak_start_rel

        hook.on_results(results_normal, None)             # resets the streak
        assert 0 not in hook._streak_start_rel

        results_high_b = [_make_result(channel=0, overall=10.0, rel_time=50.0)]
        hook.on_results(results_high_b, None)
        hook.on_results(results_high_b, None)
        event = hook.on_results(results_high_b, None)

        assert event is not None
        assert event.trigger_rel_time == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# FixedThresholdHook tests
# ---------------------------------------------------------------------------

class TestFixedThresholdHook:

    def test_upper_limit_triggers_when_exceeded(self):
        hook = FixedThresholdHook(upper_limit=1.0, upper_unit='in/s')
        results = [_make_result(channel=0, overall=2.0, unit='in/s')]
        event = hook.on_results(results, None)
        assert event is not None
        assert event.channel == 0
        assert 'upper' in event.reason.lower()

    def test_upper_limit_no_trigger_when_below(self):
        hook = FixedThresholdHook(upper_limit=1.0, upper_unit='in/s')
        results = [_make_result(channel=0, overall=0.5, unit='in/s')]
        assert hook.on_results(results, None) is None

    def test_lower_limit_triggers_when_below(self):
        hook = FixedThresholdHook(lower_limit=0.1, lower_unit='in/s')
        results = [_make_result(channel=0, overall=0.05, unit='in/s')]
        event = hook.on_results(results, None)
        assert event is not None
        assert 'lower' in event.reason.lower()

    def test_lower_limit_no_trigger_when_above(self):
        hook = FixedThresholdHook(lower_limit=0.1, lower_unit='in/s')
        results = [_make_result(channel=0, overall=1.0, unit='in/s')]
        assert hook.on_results(results, None) is None

    def test_fires_immediately_no_debounce(self):
        """Unlike the EWMA hooks, fixed thresholds fire on the very first frame."""
        hook = FixedThresholdHook(upper_limit=1.0, upper_unit='in/s')
        results = [_make_result(channel=0, overall=5.0, unit='in/s')]
        assert hook.on_results(results, None) is not None

    def test_converts_compatible_units(self):
        """1 in/s ≈ 25.4 mm/s — a channel reporting mm/s triggers against an in/s limit."""
        hook = FixedThresholdHook(upper_limit=1.0, upper_unit='in/s')
        results = [_make_result(channel=0, overall=30.0, unit='mm/s')]   # > 25.4 mm/s
        event = hook.on_results(results, None)
        assert event is not None

    def test_no_trigger_when_channel_unit_is_mv(self):
        """A channel without sensor/EU (raw 'mV') can't be evaluated — skipped, not crashed."""
        hook = FixedThresholdHook(upper_limit=1.0, upper_unit='in/s')
        results = [_make_result(channel=0, overall=999.0, unit='mV')]
        assert hook.on_results(results, None) is None

    def test_warns_once_per_channel_for_incompatible_units(self, caplog):
        """Mismatched modalities (e.g. velocity limit vs. an acceleration channel) warn once."""
        hook = FixedThresholdHook(upper_limit=1.0, upper_unit='in/s')
        results = [_make_result(channel=0, overall=999.0, unit='g')]
        with caplog.at_level(logging.WARNING):
            assert hook.on_results(results, None) is None
            assert hook.on_results(results, None) is None
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1

    def test_independent_upper_and_lower(self):
        """Both limits may be enabled at once; either may fire independently."""
        hook = FixedThresholdHook(upper_limit=2.0, upper_unit='in/s',
                                  lower_limit=0.1, lower_unit='in/s')
        below  = [_make_result(channel=0, overall=0.05, unit='in/s')]
        above  = [_make_result(channel=0, overall=3.0,  unit='in/s')]
        normal = [_make_result(channel=0, overall=1.0,  unit='in/s')]

        assert hook.on_results(normal, None) is None

        lower_event = hook.on_results(below, None)
        assert lower_event is not None
        assert 'lower' in lower_event.reason.lower()

        upper_event = hook.on_results(above, None)
        assert upper_event is not None
        assert 'upper' in upper_event.reason.lower()
