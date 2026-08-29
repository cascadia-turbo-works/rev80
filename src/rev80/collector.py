# Data Collector

import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Dict, Union

import h5py
import numpy as np
import scipy.signal

import rev80
from rev80 import _dsp
from rev80 import peaks as rev80_peaks
from rev80._paths import data_dir
from rev80.scope_sensor import ScopeSensor

log = rev80.get_logger("collector")


def _write_channel_group(h5_grp, ch: int, sample: 'rev80.VibeSample',
                         compression: str | None = None,
                         compression_opts: int | None = None) -> None:
    """Write one VibeSample's mV data into an h5py group.

    THE single channel-group writer, used by both DataCollector.save_data()
    and MonitorWriterThread. These were previously two separate functions that
    had silently diverged: the monitor copy wrote no validity flags at all, so
    every monitor session recorded clipped and rate-degraded captures as though
    they were clean. Keep them unified.
    """
    cg = h5_grp.create_group(str(ch))
    kw = {}
    if compression is not None:
        kw['compression'] = compression
        if compression_opts is not None:
            kw['compression_opts'] = compression_opts
    cg.create_dataset('data', data=np.asarray(sample.data, dtype=np.float64), **kw)
    cg.attrs['timestamp']  = sample.timestamp
    cg.attrs['rel_time']   = float(sample.rel_time)
    cg.attrs['samplerate'] = float(sample.samplerate)
    cg.attrs['status']     = str(sample.status)
    cg.attrs['overflow']   = bool(sample.overflow)
    cg.attrs['degraded']   = bool(sample.degraded)


class DataCollector:
    """Collect, filter, cache, and persist multi-channel vibration data.

    Pipeline
    --------
    Hardware callback → receive_data()
        per channel: mV→EU conversion + Butterworth filter → VibeSample
        → frame_cache.append(dict[int, VibeSample])
        → new_frame_event.set()

    The GUI render loop polls new_frame_event each tick and grabs
    frame_cache[-1] for display.  Programmatic consumers (collect_sample
    one-shot, test hooks) still use self.callbacks directly.
    """

    def __init__(
        self,
        sensor: Union[rev80.VibeSensor, None] = None,
        config: Union[rev80.AcquisitionSettings, None] = None,
    ):

        # Per-channel highpass filter state, carried across consecutive blocks
        # of one continuous stream (see filter_block). Keyed by channel; reset
        # on stream start and whenever the filter config changes.
        self._hp_zi: Dict[int, np.ndarray] = {}
        self._hp_zi_key: tuple | None = None
        self._hp_sos_cache: Dict[tuple, np.ndarray] = {}

        self.sensor: Union[rev80.VibeSensor, None] = None
        self.stream = None
        self.datadir: Path = data_dir()
        self.data: Dict = {}
        self.config = config if config else rev80.AcquisitionSettings()
        self.scope_sensors: dict[int, ScopeSensor] = {}
        self._cache_cursor: int = 0
        self.siggen_config: dict | None = None
        self._last_frame_t: float | None = None  # arrival time of previous frame
        self._lag_warn_t: float = 0.0  # wall time of last lag warning
        self.notes: str = ""
        self._loaded_channel_sensor_configs: dict[int, dict] = {}
        self._loaded_scope_sensors: dict[str, dict] = {}  # {sensor_id: ScopeSensor.to_dict()}

        # Event-based GUI signaling: set when a new frame is ready for display.
        # The GUI render loop polls this each tick and grabs frame_cache[-1].
        self.new_frame_event = threading.Event()

        if sensor is not None:
            self.connect_sensor(sensor)

        self.reset_data_store()

    # ------------------------------------------------------------------
    # Sensor assignment
    # ------------------------------------------------------------------

    def set_scope_sensor(self, channel: int, sensor: ScopeSensor | None) -> None:
        """Assign or clear a ScopeSensor on a channel for mV→EU conversion."""
        if sensor is None:
            self.scope_sensors.pop(channel, None)
        else:
            self.scope_sensors[channel] = sensor

    def get_active_eu(self, ch: int = 0) -> str:
        """Return the display/target unit for a channel.

        Returns 'mV' when no ScopeSensor is assigned — without a sensitivity
        value any unit conversion would be nonsensical.
        Priority when a sensor is present: channel_target_units > sensor.effective_target_unit().
        """
        scope_sensor = self.scope_sensors.get(ch)
        if scope_sensor is None:
            return "mV"
        ch_tu = self.config.channel_target_units.get(ch, "")
        if ch_tu:
            return ch_tu
        return scope_sensor.effective_target_unit()

    # ------------------------------------------------------------------
    # Stream state
    # ------------------------------------------------------------------

    @property
    def is_streaming(self):
        try:
            return self.sensor and self.stream and self.stream.active
        except Exception:
            log.error("Device connection may be interrupted")
            return False

    @property
    def stream_degraded(self):
        """True when the underlying stream has flagged sustained sub-rate throughput.

        Safe default False for streams with no concept of this (e.g. SimulatedSensor).
        """
        return getattr(self.stream, 'degraded', False)

    # ------------------------------------------------------------------
    # Data store
    # ------------------------------------------------------------------

    def reset_data_store(self):
        self.data = {
            "frame_cache": deque(maxlen=self.config.cache_frames),  # dict[int, VibeSample]
            "frame_count": 0,
        }
        self.trend: dict[int, dict[str, np.ndarray]] = {}
        self._cache_cursor = 0
        self.init_trend_channels()
        log.info("Reset data store.")

    def resize_frame_cache(self, n: int) -> None:
        """Rebuild frame_cache with a new maxlen, preserving the most recent frames."""
        existing = list(self.data["frame_cache"])
        self.data["frame_cache"] = deque(existing[-n:], maxlen=n)

    def reset_channel_config(self, num_channels: int) -> None:
        """Prune all per-channel state to match a new device's channel count.

        Removes scope_sensors, voltage range, and coupling entries for
        channels >= num_channels, then resets the data store so no stale
        multi-channel frames or trend data carry over to the new device.
        Enabled channels are clamped to the valid range; if none survive,
        channel 0 is re-enabled as a safe default.
        """
        valid = set(range(num_channels))

        # Prune scope_sensors
        for ch in list(self.scope_sensors):
            if ch not in valid:
                self.scope_sensors.pop(ch)

        # Prune per-channel acquisition settings
        for ch in list(self.config.channel_voltage_ranges):
            if ch not in valid:
                del self.config.channel_voltage_ranges[ch]
        for ch in list(self.config.channel_couplings):
            if ch not in valid:
                del self.config.channel_couplings[ch]

        # Clamp enabled_channels
        self.config.enabled_channels = sorted(ch for ch in self.config.enabled_channels if ch in valid)
        if not self.config.enabled_channels:
            self.config.enabled_channels = [0]

        self.reset_data_store()
        log.info(f"Channel config reset for {num_channels}-channel device.")

    def init_trend_channels(self):
        """(Re-)initialise trend store keyed by current enabled_channels.

        Channels already in the store are preserved; new channels get empty
        arrays; channels no longer enabled are dropped.
        """
        enabled = set(self.config.enabled_channels)
        self.trend = {
            ch: self.trend.get(ch, {
                "rel_times": np.empty(0),
                "orders":    np.empty((0, 5)),
            }) for ch in sorted(enabled)
        }

    # ------------------------------------------------------------------
    # Highpass filtering
    # ------------------------------------------------------------------

    def reset_filter_state(self) -> None:
        """Drop carried highpass state (stream start / reconnect / config change)."""
        self._hp_zi.clear()

    def _filter_key(self, samplerate: float) -> tuple:
        """Identity of the filter that would be applied at this rate."""
        return (bool(self.config.highpass_enabled), float(self.config.highpass_fc),
                int(self.config._BUTTER_ORDER), float(samplerate))

    def _highpass_sos(self, samplerate: float) -> 'np.ndarray | None':
        """Butterworth SOS for the current config, recomputed only when it changes."""
        key = self._filter_key(samplerate)
        if not self.config.highpass_enabled or self.config.highpass_fc >= samplerate / 2.0:
            return None
        cached = self._hp_sos_cache.get(key)
        if cached is None:
            cached = scipy.signal.butter(
                self.config._BUTTER_ORDER, self.config.highpass_fc,
                btype='highpass', fs=samplerate, output='sos',
            )
            self._hp_sos_cache.clear()      # only ever one live config
            self._hp_sos_cache[key] = cached
        return cached

    def filter_block(self, ch: int, data: np.ndarray, samplerate: float,
                     stateful: bool) -> np.ndarray:
        """Highpass one block of mV data.

        Causal (sosfilt), not zero-phase: sosfiltfilt effectively doubles the
        filter order (forward + backward pass), which resonates badly for a low
        cutoff relative to a short block (e.g. 10 Hz over a 1 s block — only 10
        cutoff-cycles of margin). Confirmed on real hardware data: sosfiltfilt
        overshot the raw signal by 35-45% at the block edges with any padtype.

        But plain `sosfilt(sos, x)` with no initial condition restarts the
        filter from rest at every block, injecting a startup transient into
        every frame of a continuous stream. Measured on a 200 Hz tone, block 1
        of 4, high-pass at 10 Hz:

                                      no zi      steady-state zi + carry
            waveform peak            +9.41%          -0.00%
            RMS, 1000 mV DC offset  +14321.74%       -0.00%
            displacement overall     +19.15%         +0.02%
            ... with DC offset    +1472786.72%       +0.02%

        Two regimes:

        * ``stateful=True`` — consecutive blocks of one live stream. The final
          filter state of each block seeds the next, so the boundary is
          seamless. Only receive_data uses this, exactly once per frame and in
          order.
        * ``stateful=False`` — a stored frame replayed from HDF5, or a frame
          re-filtered because the config changed after capture. These are NOT
          a continuous stream and are re-processed out of order, so no state
          may be carried between them or replay stops being deterministic.
          The filter is instead seeded from the block's DC content — see
          _seed_zi.
        """
        sos = self._highpass_sos(samplerate)
        if sos is None:
            return np.asarray(data, dtype=np.float64).copy()

        x = np.ascontiguousarray(data, dtype=np.float64)
        if stateful:
            key = self._filter_key(samplerate)
            zi = self._hp_zi.get(ch)
            if zi is None or self._hp_zi_key != key:
                if self._hp_zi_key != key:
                    self._hp_zi.clear()
                self._hp_zi_key = key
                zi = self._seed_zi(sos, x)
            y, self._hp_zi[ch] = scipy.signal.sosfilt(sos, x, zi=zi)
            return y

        y, _ = scipy.signal.sosfilt(sos, x, zi=self._seed_zi(sos, x))
        return y

    @staticmethod
    def _seed_zi(sos: np.ndarray, x: np.ndarray) -> np.ndarray:
        """Initial filter state for a block with no usable history.

        Seeded from the block MEAN, not from x[0]. scipy's documented idiom is
        sosfilt_zi(sos) * x[0], which is correct when the first sample
        represents the signal's baseline — true for a step response, false for
        anything oscillatory. A vibration block is a waveform swinging about
        its DC level, so x[0] is an arbitrary point on that swing, and seeding
        with it tells the high-pass that the signal has been sitting at that
        value forever. The filter then decays a step that was never there.

        Measured on four consecutive real captures (PicoScope 4424A, 447.3 Hz
        loopback tone, 1 Vpp, fs=8333.25, 10 Hz high-pass). Block mean was
        -0.06..-0.21 mV in every block — the true DC — while x[0] ranged over
        36..305 mV. Error against a fully-settled continuous-filter reference:

            order          zi * x[0]        zi * mean(x)     warm-up pass
            acceleration     +0.39%           -0.00%           +0.00%
            velocity        +23.01%           -0.06%           -0.07%
            displacement  +4297.20%           -2.22%          +61.10%
            waveform         57.63%            0.51%            6.37%

        (worst block shown per row.) A warm-up pass — filtering the block once
        and reusing its final state as the initial state — was also tried and
        is measurably WORSE than the mean, because it imposes a periodic
        assumption the block does not satisfy.

        Residual displacement error on an isolated block is irreducible: at
        447 Hz the doubly-integrated result is dominated by near-DC noise whose
        continuation simply is not present in a single block. It only affects
        block 0 of a stream and replayed frames; once state is carried, blocks
        1+ match the settled reference to +-0.000%.
        """
        return scipy.signal.sosfilt_zi(sos) * float(np.mean(x))

    def filtered_data_for(self, ch: int, sample: 'rev80.VibeSample') -> np.ndarray:
        """Highpassed mV for a sample, using the ingestion-time result if valid.

        receive_data pre-filters live frames with carried state. If that cached
        result was produced by the filter config now in force, reuse it —
        re-filtering here would be both wasteful and, for a streaming frame,
        wrong (the state has already moved on). Otherwise the sample is being
        replayed or the config changed since capture, so filter it statelessly.
        """
        key = self._filter_key(sample.samplerate)
        if sample.filtered_mv is not None and sample._filter_config_key == key:
            return sample.filtered_mv
        filtered = self.filter_block(ch, sample.data, sample.samplerate, stateful=False)
        sample.filtered_mv        = filtered
        sample._filter_config_key = key
        return filtered

    def update_trend(self, ch: int, rel_time: float, orders: np.ndarray) -> None:
        """Append one timestamped 5-order overall vector (mV RMS) for a channel."""
        if ch not in self.trend:
            self.trend[ch] = {"rel_times": np.empty(0), "orders": np.empty((0, 5))}
        td = self.trend[ch]
        td["rel_times"] = np.append(td["rel_times"], rel_time)
        td["orders"]    = np.vstack([td["orders"], orders.reshape(1, 5)])
        cap = self.config.trend_max_points
        if len(td["rel_times"]) > cap:
            td["rel_times"] = td["rel_times"][-cap:]
            td["orders"]    = td["orders"][-cap:]

    def clear_trend(self) -> None:
        """Wipe all accumulated trend data."""
        for ch in self.trend:
            self.trend[ch] = {"rel_times": np.empty(0), "orders": np.empty((0, 5))}
        log.debug("Trend data cleared.")

    def get_trend_for_display(self) -> dict[int, tuple[list[float], list[float]]]:
        """Return {ch: (rel_times, displayed_values)} scaled to current display settings.

        All unit/sensitivity/amplitude-mode conversion is handled here so the
        GUI never needs to import unit-conversion utilities.
        """
        from rev80.util import UNIT_TO_SI, amplitude_scale, integration_steps
        out: dict[int, tuple[list[float], list[float]]] = {}
        for ch in self.config.enabled_channels:
            td        = self.trend.get(ch, {})
            rel_times = td.get("rel_times", np.empty(0))
            orders    = td.get("orders",    np.empty((0, 5)))
            if len(rel_times) == 0:
                out[ch] = ([], [])
                continue

            scope_sensor   = self.scope_sensors.get(ch)
            sensor_eu      = scope_sensor.engineering_units if scope_sensor else 'mV'
            sensitivity_mv = scope_sensor.sensitivity       if scope_sensor else 1.0
            target_unit    = self.get_active_eu(ch)
            amp_mode       = self.config.amplitude_mode_for(ch) or '0-P'

            n_steps    = integration_steps(sensor_eu, target_unit)
            amp_factor = amplitude_scale(amp_mode)
            src_si     = UNIT_TO_SI.get(sensor_eu, 1.0)
            tgt_si     = UNIT_TO_SI.get(target_unit, 1.0)
            scale      = src_si / tgt_si / sensitivity_mv

            col       = max(0, min(4, n_steps + 2))   # −2→0, −1→1, 0→2, +1→3, +2→4
            displayed = list(orders[:, col] * scale * amp_factor)
            out[ch]   = (list(rel_times), displayed)
        return out

    # ------------------------------------------------------------------
    # Frame cache navigation
    # ------------------------------------------------------------------

    def reprocess_last_block(self) -> None:
        """Signal the GUI to redisplay the current cached frame.

        Use after display settings change (units, sensor, freq window) while
        the stream is stopped to refresh plots without new hardware data.
        Does not append a duplicate frame or reset the browse cursor.
        """
        cache = self.data["frame_cache"]
        if not cache:
            return
        self.new_frame_event.set()

    def browse_frame(self, delta: int) -> None:
        """Move the cache cursor by delta and redisplay.

        Positive delta goes older; negative goes newer.
        Only meaningful when the stream is stopped.
        """
        cache = self.data["frame_cache"]
        if not cache:
            return
        self._cache_cursor = max(0, min(self._cache_cursor + delta, len(cache) - 1))
        self.reprocess_last_block()

    # ------------------------------------------------------------------
    # Sensor connection
    # ------------------------------------------------------------------

    def connect_sensor(self, sensor: rev80.VibeSensor, siggen_config: dict | None = None):
        """Connect to a device and initialise its stream."""
        if not isinstance(sensor, rev80.VibeSensor):
            raise TypeError(f"Attempted to select invalid sensor of {type(sensor)}")

        if self.stream is not None or self.sensor is not None:
            self.disconnect_sensor()

        if self.config is None:
            log.error("Attempted to connect sensor but no configuration set")
            return

        self.sensor = sensor
        self.stream = self.sensor.connect(self.config, self.receive_data, siggen_config=siggen_config)
        log.debug(f"Connected sensor {self.sensor}")

    def disconnect_sensor(self):
        if self.is_streaming:
            self.stop_stream()

        if self.stream is not None:
            self.stream.close()
            self.stream = None

        if self.sensor:
            log.debug(f"Disconnecting sensor {self.sensor}")
            self.sensor = None

    # ------------------------------------------------------------------
    # Stream control
    # ------------------------------------------------------------------

    def start_stream(self):
        """Initiate sensor stream."""
        if self.is_streaming:
            log.warning("Attempted Start Stream: Already Running")
            return
        if not self.stream:
            return
        # A new stream is a new continuous signal — drop any filter state
        # carried over from the previous one.
        self.reset_filter_state()
        try:
            self.stream.start()
        except Exception as e:
            self.disconnect_sensor()
            log.error(f"Error starting stream: {e}")
        log.debug("Stream started")

    def stop_stream(self):
        """Terminate sensor stream."""
        if not self.stream or not self.is_streaming:
            log.warning("Attempted Stop Stream: No stream running")
            return
        self.stream.stop()
        log.debug("Stream stopped")

    def reconnect_stream(self):
        """Close and recreate the stream with current config.

        Call this after modifying config.enabled_channels so hardware
        (e.g. PicoScopeStream) picks up the new channel list.
        """
        if self.sensor is None:
            return
        sensor = self.sensor
        was_streaming = self.is_streaming
        if was_streaming:
            self.stop_stream()
        if self.stream is not None:
            self.stream.close()
            self.stream = None
        self.stream = sensor.connect(self.config, self.receive_data, siggen_config=self.siggen_config)
        if was_streaming:
            self.start_stream()

    # ------------------------------------------------------------------
    # Single-shot capture
    # ------------------------------------------------------------------

    def collect_sample(self) -> dict:
        """Collect one block from each enabled channel.

        Returns dict[int, VibeSample].  The captured frame is stored in
        frame_cache and signalled via new_frame_event, consistent with the
        normal streaming path.
        """
        if self.is_streaming:
            self.stop_stream()

        self.new_frame_event.clear()
        self.start_stream()
        timed_out = not self.new_frame_event.wait(timeout=self.config.acquisition_period * 3)
        self.stop_stream()

        if timed_out:
            log.warning("collect_sample timed out waiting for a frame")
            return {}

        cache = self.data["frame_cache"]
        return dict(cache[-1]) if cache else {}

    # ------------------------------------------------------------------
    # Data pipeline
    # ------------------------------------------------------------------

    def receive_data(self, samp: dict):
        """Preprocess one hardware block: fan out to per-channel VibeSamples.

        Applies per-channel mV→EU sensitivity conversion then an optional
        Butterworth highpass filter before forwarding to _data_callback().
        """
        data_arr = np.asarray(samp["data"])
        channels = samp.get("channels", [0])

        # Ensure 2-D (blocksize, N_channels)
        if data_arr.ndim == 1:
            data_arr = data_arr[:, np.newaxis]

        overflow_mask: int = samp.get("overflow_mask", 0)
        degraded: bool = samp.get("degraded", False)
        samples: dict[int, rev80.VibeSample] = {}

        samplerate = samp.get("samplerate", self.config.samplerate)
        for i, ch in enumerate(channels):
            col  = min(i, data_arr.shape[1] - 1)
            data = np.ascontiguousarray(data_arr[:, col], dtype=np.float64)
            # Filter here, at ingestion: this runs exactly once per frame and
            # in stream order, which is what carrying the filter state across
            # block boundaries requires. process_sample may be called many
            # times on the same frame (re-render, unit change) and in any
            # order when browsing, so it must not advance the state.
            filtered = self.filter_block(ch, data, samplerate, stateful=True)
            samples[ch] = rev80.VibeSample(
                status=samp["status"],
                _timestamp=samp["timestamp"],
                samplerate=samplerate,
                unit="mV",
                overflow=bool(overflow_mask & (1 << ch)),
                degraded=degraded,
                data=data,
                rel_time=samp["rel_time"],
                label=f"Ch{chr(65 + ch)}",
                filtered_mv=filtered,
                _filter_config_key=self._filter_key(samplerate),
            )

        self._data_callback(samples)

    def _data_callback(self, samples: dict):
        """Store raw frame and signal that new data is available.

        Appends the frame to frame_cache, then sets new_frame_event so
        the GUI render loop can pick up the latest frame on its next tick.
        All consumers — GUI, collect_sample, tests — read from frame_cache
        via new_frame_event rather than receiving samples directly.
        """
        if samples:
            self.data["frame_cache"].append(samples)
            self.data["frame_count"] += 1
            self._cache_cursor = 0

        self.new_frame_event.set()

    # ------------------------------------------------------------------
    # Sample processing
    # ------------------------------------------------------------------

    def process_sample(self, ch: int, sample: 'rev80.VibeSample') -> 'rev80.ChannelResult | None':
        """Filter, compute PSD, 5-order mV overalls, and convert to display units.

        Side-effects on sample (cached after first call per config):
          - psd_mv / freq_hz / _psd_config_key
          - overall_ampl_by_integration_order — (5,) RMS overalls in mV, orders −2…+2
        """
        from rev80.util import UNIT_TO_SI, amplitude_scale, integration_steps

        if sample.blocksize <= 1:
            return None

        scope_sensor   = self.scope_sensors.get(ch)
        sensor_eu      = scope_sensor.engineering_units if scope_sensor else 'mV'
        sensitivity_mv = scope_sensor.sensitivity       if scope_sensor else 1.0
        amp_mode       = self.config.amplitude_mode_for(ch) or '0-P'
        target_unit    = self.get_active_eu(ch)
        effective_tgt  = target_unit if target_unit else sensor_eu
        config         = self.config
        samplerate     = sample.samplerate

        # ── 1. Butterworth filter ─────────────────────────────────────
        # Filtering happens in filter_block(); see there for why the filter is
        # causal-with-carried-state rather than zero-phase. Streaming frames
        # arrive pre-filtered from receive_data (state carried across blocks);
        # replayed frames are filtered here, statelessly.
        filtered_mv = self.filtered_data_for(ch, sample)

        # Frequency-domain integration/differentiation is done on a *tapered*
        # block. The DFT treats the record as periodic, so an un-windowed block
        # spanning a non-integer number of cycles carries a step discontinuity
        # at the wrap point. That step's spectrum is broadband and
        # low-frequency-weighted, and (j*omega)**n with n < 0 amplifies it by
        # 1/omega**|n| — exactly where it is worst. Un-windowed, a 501 Hz tone
        # read +4473.76% high in displacement overall; the on-bin case that the
        # old test suite exercised exclusively was the one case with zero error.
        # See rev80._dsp for the full measured table.
        N       = sample.blocksize
        freq_td = np.fft.rfftfreq(N, d=1.0 / samplerate)

        # Hann taper for the scalar overalls (step 3): dividing the resulting
        # RMS by the window's power gain recovers the unbiased broadband RMS.
        hann_w, hann_gain = _dsp.hann_taper(N)
        rfft_hann = np.fft.rfft(filtered_mv * hann_w)

        # ── 2. Welch PSD in mV² — compute once, cache on sample ──────
        # binsize and samplerate BOTH change the transform, so both belong in
        # the key. Without them, switching 2 Hz -> 0.5 Hz bins returned the
        # identical cached 2049-point, 2 Hz spectrum: the user believed they had
        # quadrupled the resolution and nothing had changed. Masked while
        # streaming (each new VibeSample starts with psd_mv=None), so it bit in
        # browse/offline mode and after loading a file.
        psd_key = (config.fft_window, config.welch_overlap,
                   config.highpass_enabled, config.highpass_fc,
                   config.binsize, sample.samplerate)
        if sample.psd_mv is None or sample._psd_config_key != psd_key:
            # Segment = the whole block, so the computed spectrum matches the
            # line count and bin width the UI states. See config.nperseg.
            nperseg  = min(config.nperseg, len(filtered_mv))
            noverlap = min(nperseg - 1, int(nperseg * config.welch_overlap))
            freq_hz, psd_mv = scipy.signal.welch(
                filtered_mv, fs=float(samplerate),
                window=config.fft_window, nperseg=nperseg, noverlap=noverlap,
                nfft=nperseg, scaling='spectrum', detrend='linear', average='mean',
            )
            sample.psd_mv          = psd_mv
            sample.freq_hz         = freq_hz
            sample._psd_config_key = psd_key

            # ── 3. 5-order mV RMS overalls via time-domain IFFT ──────
            # Using sqrt(mean(x²)) on the IFFT signal avoids the Welch window
            # normalisation artifact (Hann leakage inflates sqrt(sum(psd)) by
            # sqrt(3/2) for a pure tone).
            #
            # Order 0 is a plain passthrough: no transform happens, so there is
            # no wrap discontinuity to suppress and no window is applied. Every
            # other order integrates or differentiates in the frequency domain
            # and so runs on the Hann-tapered transform, with the window's power
            # gain divided back out to leave the RMS unbiased.
            for i, n_ord in enumerate(range(-2, 3)):
                if n_ord == 0:
                    sample.overall_ampl_by_integration_order[i] = float(
                        np.sqrt(np.mean(np.square(filtered_mv)))
                    )
                    continue
                time_ord = _dsp.integrate_rfft(rfft_hann, freq_td, n_ord, N)
                sample.overall_ampl_by_integration_order[i] = float(
                    np.sqrt(np.mean(np.square(time_ord))) / hann_gain
                )
        else:
            freq_hz = sample.freq_hz
            psd_mv  = sample.psd_mv

        # ── 4. Integrate / scale mV² PSD → target-unit² PSD ─────────
        n_steps = integration_steps(sensor_eu, effective_tgt)
        if abs(n_steps) > 2:
            log.error(
                f'process_sample ch={ch}: integration steps {n_steps} out of range [-2, 2] '
                f'({sensor_eu!r} → {effective_tgt!r}); skipping frame'
            )
            return None
        if n_steps != 0:
            omega_factor       = np.zeros_like(psd_mv)
            pos                = freq_hz > 0
            omega_factor[pos]  = (2 * np.pi * freq_hz[pos]) ** (2 * n_steps)
            if n_steps < 0:
                omega_factor[1] = 0.0   # also kill the 1x-binsize bin -- see step 3 comment
            integrated_psd     = psd_mv * omega_factor
        else:
            integrated_psd = psd_mv.copy()

        # mV² → EU²: /sensitivity²;  EU² → target²: (SI[EU]/SI[target])²
        src_si = UNIT_TO_SI.get(sensor_eu, 1.0)
        tgt_si = UNIT_TO_SI.get(effective_tgt, 1.0)
        calibrated_psd = integrated_psd * (src_si / tgt_si / sensitivity_mv) ** 2

        # ── 5. Amplitude spectrum in target unit + amp mode ───────────
        amp_factor   = amplitude_scale(amp_mode)
        spectrum_amp = np.sqrt(np.maximum(calibrated_psd, 0.0)) * amp_factor

        # ── 6. Truncate at F_max, then find peaks ─────────────────────
        # The whole point of the F_max = fs/2.56 convention is that the guard
        # band between F_max and fs/2 is never displayed: that is where the
        # anti-alias filter has not yet reached full attenuation. Measured
        # rejection at the frequency folding into the top of the band is
        # -21.8 dB, falling to effectively 0 dB at fs/2 — so content shown up
        # there is not a measurement, and find_peaks was happily reporting it
        # in the peaks table alongside real lines.
        keep_band    = freq_hz <= config.maxfreq
        freq_hz      = freq_hz[keep_band]
        spectrum_amp = spectrum_amp[keep_band]

        # Peak selection is significance-based, not top-N-by-amplitude: a line
        # is reported when it rises config.peak_threshold_db above its own
        # local noise floor, and the count is whatever that yields. The old
        # rule ranked by how loud a line's neighbourhood was — on
        # 'blower 4 - bearing DE.h5' ch2 it spent 6 of its top 12 on ripple in
        # the noisy top of the band and pushed the 1034/1088 Hz bearing
        # sidebands off a 6-row table. See rev80.peaks for the full rationale.
        #
        # n_segments feeds the median-to-mean correction on the floor estimate.
        # It is 1 for every shipped preset (nperseg == blocksize), but it is
        # derived rather than assumed: that invariant belongs to
        # AcquisitionSettings, not to the statistics.
        seg_len    = min(config.nperseg, len(filtered_mv))
        seg_step   = max(1, seg_len - min(seg_len - 1, int(seg_len * config.welch_overlap)))
        n_segments = 1 + max(0, len(filtered_mv) - seg_len) // seg_step
        peaks = rev80_peaks.select_peaks(
            spectrum_amp,
            window=config.fft_window,
            threshold_db=config.peak_threshold_db,
            n_segments=n_segments,
        )

        # ── 7. Overall amplitude in target unit ───────────────────────
        # Reuse the IFFT-based mV RMS cached in step 3; apply unit scale + amp mode.
        col_idx = n_steps + 2
        overall = float(
            sample.overall_ampl_by_integration_order[col_idx]
            * (src_si / tgt_si / sensitivity_mv)
            * amp_factor
        )

        # ── 8. Time-domain signal — inline FFT integration ───────────
        # The displayed trace cannot use the step-3 Hann taper: the taper would
        # be plainly visible as an amplitude envelope on the waveform the user
        # is reading. Instead this is overlap-save — a Tukey window (flat across
        # the middle, cosine-tapered at the edges) kills the wrap discontinuity,
        # and only the flat middle is returned. Inside that region the window is
        # exactly 1.0, so the returned samples are undistorted.
        #
        # Cost: for integrated/differentiated displays the trace covers the
        # middle 50% of the block rather than all of it. time_vec is truncated
        # to match, so it still carries true capture-relative timestamps.
        # Un-truncated, a doubly-integrated 61 Hz tone overshot its true 0-peak
        # amplitude by +1149%; this brings it to +1.47%.
        eu_scale = src_si / tgt_si / sensitivity_mv
        if n_steps != 0:
            keep        = _dsp.tukey_keep_slice(N)
            tukey_w     = _dsp.tukey_taper(N)
            rfft_tukey  = np.fft.rfft(filtered_mv * tukey_w)
            time_signal = _dsp.integrate_rfft(rfft_tukey, freq_td, n_steps, N)
            time_signal = time_signal[keep] * eu_scale
            time_vec    = sample.time_vec[keep]
        else:
            # Passthrough: no transform, no wrap discontinuity, full record.
            time_signal = filtered_mv * eu_scale
            time_vec    = sample.time_vec

        return rev80.ChannelResult(
            channel=ch, unit=effective_tgt, overflow=sample.overflow,
            degraded=sample.degraded,
            time_data=time_signal, time_vec=time_vec, samplerate=samplerate,
            freq=freq_hz, spectrum=spectrum_amp, peaks=peaks, overall=overall,
            timestamp=sample._timestamp, rel_time=sample.rel_time, status=sample.status,
        )

    def process_samples(self) -> list['rev80.ChannelResult']:
        """Process the current frame; return one ChannelResult per enabled channel.

        Uses the latest frame when streaming; uses _cache_cursor when browsing.
        Appends to trend only during streaming.
        """
        cache = self.data["frame_cache"]
        if not cache:
            return []
        if not self.is_streaming:
            # Clamp cursor to valid range when cache size changes (e.g. after loading a session)
            self._cache_cursor = min(self._cache_cursor, len(cache) - 1)
        idx   = -1 if self.is_streaming else -1 - self._cache_cursor
        frame = cache[idx]
        results: list[rev80.ChannelResult] = []
        for ch in sorted(self.config.enabled_channels):
            sample = frame.get(ch)
            if sample is None or sample.blocksize <= 1:
                continue
            result = self.process_sample(ch, sample)
            if result is None:
                continue
            if self.is_streaming:
                # A clipped or rate-degraded frame is not a measurement. Trending
                # it records a step change that never happened on the machine,
                # and the anomaly detector then fires a burst on it — the classic
                # spurious-alarm mechanism. The frame is still returned for
                # display (flagged), just never trended.
                if result.overflow or result.degraded:
                    log.debug(
                        f'ch={ch} frame at rel_time={result.rel_time:.3f}s excluded '
                        f'from trend (overflow={result.overflow}, '
                        f'degraded={result.degraded})'
                    )
                else:
                    self.update_trend(ch, result.rel_time,
                                      sample.overall_ampl_by_integration_order)
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    # File format version written by save_data.
    # v1 (legacy): metadata as child datasets, channels under 'channels/' subgroup,
    #   scope sensor as YAML text dataset.
    # v2 (intermediate): metadata in frame group .attrs, channel metadata in frame children,
    #   scope sensor fields as per-frame channel attrs, /acquisition group.
    # v3 (current): structured /metadata group; sensor library; channel config stored once;
    #   shared trend rel_times axis.
    _FILE_VERSION = 4

    def save_data(self, target: Path):
        """Save frame cache and trend history to an HDF5 file (v4 format).

        Layout::

            /metadata                               group
            /metadata.attrs                         version, notes
            /metadata/acquisition                   group
            /metadata/acquisition.attrs             maxfreq, binsize, fft_window,
                                                    welch_overlap, highpass_enabled,
                                                    highpass_fc, trend_max_points
            /metadata/scope_sensors/{id}            group (one per unique sensor used)
            /metadata/scope_sensors/{id}.attrs      name, id, sensitivity, engineering_units,
                                                    target_unit, notes
            /metadata/channels/{ch}                 group (one per enabled channel)
            /metadata/channels/{ch}.attrs           name, unit, coupling, voltage_range,
                                                    scope_sensor_id, target_unit
            /frames/{i}                             group
            /frames/{i}.attrs                       timestamp, rel_time, samplerate, status
            /frames/{i}/{ch}/data                   (N,) float64
            /trend/rel_times                        (M,) float64  (shared time axis)
            /trend/{ch}/data                        (M,) float64  (channel overall amplitude)
        """
        frames = list(self.data["frame_cache"])
        log.info(f"Writing {len(frames)} frames to {target}")
        try:
            f_handle = h5py.File(target, "w")
        except OSError as exc:
            log.error(f"save_data: failed to open {target} for writing: {exc}")
            raise
        with f_handle as f:
            # ── /metadata ──────────────────────────────────────────────
            meta_grp = f.create_group("metadata")
            meta_grp.attrs["version"] = self._FILE_VERSION
            meta_grp.attrs["notes"] = self.notes

            # /metadata/acquisition — scalar acq settings only (channel dicts in /metadata/channels)
            acq_grp = meta_grp.create_group("acquisition")
            cfg_dict = self.config.to_dict()
            for k, v in cfg_dict.items():
                if k in ("channel_names", "channel_target_units", "channel_amplitude_modes"):
                    continue  # stored per-channel in /metadata/channels
                acq_grp.attrs[k] = "" if v is None else v

            # /metadata/scope_sensors — sensor library: one subgroup per unique sensor
            ss_grp = meta_grp.create_group("scope_sensors")
            seen_ids: set[str] = set()
            for scope_s in self.scope_sensors.values():
                if scope_s.id not in seen_ids:
                    seen_ids.add(scope_s.id)
                    sg = ss_grp.create_group(scope_s.id)
                    for k, v in scope_s.to_dict().items():
                        sg.attrs[k] = v

            # /metadata/channels — channel config (constant for entire dataset)
            # Determine the actual sample unit per channel from the first available frame
            ch_sample_units: dict[int, str] = {}
            for frame_s in frames:
                for fch, fsamp in ((k, v) for k, v in frame_s.items() if isinstance(k, int)):
                    if fch not in ch_sample_units:
                        ch_sample_units[fch] = fsamp.unit
            ch_meta_grp = meta_grp.create_group("channels")
            for ch in self.config.enabled_channels:
                scope_s = self.scope_sensors.get(ch)
                cg = ch_meta_grp.create_group(str(ch))
                cg.attrs["name"] = self.config.name_for(ch)
                cg.attrs["unit"] = ch_sample_units.get(ch, scope_s.engineering_units if scope_s else "mV")
                cg.attrs["coupling"] = self.config.coupling_for(ch)
                cg.attrs["voltage_range"] = self.config.voltage_range_for(ch)
                cg.attrs["scope_sensor_id"] = scope_s.id if scope_s else ""
                cg.attrs["target_unit"] = self.config.target_unit_for(ch)
                cg.attrs["amplitude_mode"] = self.config.amplitude_mode_for(ch)

            # ── /frames ────────────────────────────────────────────────
            enabled = set(self.config.enabled_channels)
            frames_grp = f.create_group("frames")
            for i, frame_samples in enumerate(frames):
                fg = frames_grp.create_group(str(i))
                # Only save enabled channels — disabling a channel excludes it from the file
                ch_only = {k: v for k, v in frame_samples.items() if isinstance(k, int) and k in enabled}
                if not ch_only:
                    continue
                first = next(iter(ch_only.values()))
                fg.attrs["timestamp"] = first.timestamp
                fg.attrs["rel_time"] = first.rel_time
                fg.attrs["samplerate"] = first.samplerate
                fg.attrs["status"] = first.status
                for ch, sample in ch_only.items():
                    _write_channel_group(fg, ch, sample)

            # ── /trend ─────────────────────────────────────────────────
            # Each channel has its own rel_times axis + (M,5) orders matrix.
            # Columns of orders = integration orders −2,−1,0,+1,+2 in mV RMS.
            trend_grp = f.create_group("trend")
            for ch, td in self.trend.items():
                if ch in enabled and len(td["rel_times"]) > 0:
                    cg = trend_grp.create_group(str(ch))
                    cg.create_dataset("rel_times", data=td["rel_times"].astype(np.float64))
                    cg.create_dataset("orders",    data=td["orders"].astype(np.float64))

        log.info(f"Saved {len(frames)} frames to {target}")

    def load_data(self, target: Path):
        """Load frame cache and trend from an HDF5 file, then reprocess."""
        if not target.is_file():
            log.error(f"load_data: file does not exist: {target}")
            return

        log.info(f"Reading snapshot {target.name}")
        self.data["frame_cache"].clear()
        self.trend = {}
        self._loaded_channel_sensor_configs = {}
        self._loaded_scope_sensors = {}

        with h5py.File(target, "r") as f:
            version  = self._restore_metadata(f)
            ch_units = self._loaded_channel_units(f)

            # Frames — v4+ always mV; v3 used the recorded unit
            if "frames" in f:
                for idx in sorted(f["frames"].keys(), key=int):
                    frame = self._read_frame_group(f["frames"][idx], ch_units, version)
                    self.data["frame_cache"].append(frame)

            # Trend
            if "trend" in f:
                trend_grp = f["trend"]
                if version >= 4:
                    # Per-channel (M,5) orders matrix
                    for ch_str, cg in trend_grp.items():
                        if not ch_str.isdigit():
                            continue
                        ch = int(ch_str)
                        self.trend[ch] = {
                            "rel_times": np.array(cg["rel_times"][()], dtype=np.float64),
                            "orders":    np.array(cg["orders"][()],    dtype=np.float64),
                        }
                else:
                    # Shared time axis + per-channel scalar overalls; promote to (M,5)
                    shared_rel_times: list = []
                    if "rel_times" in trend_grp:
                        shared_rel_times = list(np.array(trend_grp["rel_times"][()]))
                    for ch_str, tg in trend_grp.items():
                        if not ch_str.isdigit():
                            continue
                        overall = list(np.array(tg["data"][()]))
                        if overall:
                            M      = len(overall)
                            orders = np.zeros((M, 5))
                            orders[:, 2] = np.array(overall)  # col 2 = order 0
                            self.trend[int(ch_str)] = {
                                "rel_times": np.array(shared_rel_times),
                                "orders":    orders,
                            }

        self._post_load()
        log.info(f"Loaded {len(self.data['frame_cache'])} frames from {target.name}")

    def _restore_metadata(self, f: 'h5py.File') -> int:
        """Restore AcquisitionSettings and sensor config from /metadata in an open HDF5 file.

        Returns the file version integer.  Side-effects:
          self.config, self.notes, self._loaded_scope_sensors,
          self._loaded_channel_sensor_configs updated in-place.
        """
        def decode(x):
            return x.decode() if isinstance(x, bytes) else str(x)

        version  = int(f["metadata"].attrs.get("version",
                       f["metadata"].attrs.get("file_version", 3)))
        meta_grp = f["metadata"]
        self.notes = decode(meta_grp.attrs.get("notes", ""))

        # Acquisition settings
        if "acquisition" in meta_grp:
            acq_dict = {k: (None if v == "" else v)
                        for k, v in meta_grp["acquisition"].attrs.items()}
            self.config = rev80.AcquisitionSettings.from_dict(acq_dict)

        # Scope sensor library — {sensor_id: dict}
        self._loaded_scope_sensors = {}
        if "scope_sensors" in meta_grp:
            for sid, sg in meta_grp["scope_sensors"].items():
                d: dict = {}
                for k, v in sg.attrs.items():
                    if isinstance(v, (bytes, np.bytes_)):
                        d[k] = v.decode()
                    elif isinstance(v, (np.integer,)):
                        d[k] = int(v)
                    elif isinstance(v, (np.floating,)):
                        d[k] = float(v)
                    else:
                        d[k] = v
                d["id"] = sid
                self._loaded_scope_sensors[sid] = d

        # Channel metadata — restore names, target units, and sensor configs
        self._loaded_channel_sensor_configs = {}
        if "channels" in meta_grp:
            for ch_str, cg in meta_grp["channels"].items():
                ch             = int(ch_str)
                name           = decode(cg.attrs.get("name", ""))
                target_unit    = decode(cg.attrs.get("target_unit", ""))
                sensor_id      = decode(cg.attrs.get("scope_sensor_id", ""))
                coupling       = decode(cg.attrs.get("coupling", "AC"))
                voltage_range  = int(cg.attrs.get("voltage_range", 7))
                amplitude_mode = decode(cg.attrs.get("amplitude_mode", ""))
                if name:
                    self.config.channel_names[ch] = name
                if target_unit:
                    self.config.channel_target_units[ch] = target_unit
                if amplitude_mode:
                    self.config.channel_amplitude_modes[ch] = amplitude_mode
                self.config.channel_couplings[ch]    = coupling
                self.config.channel_voltage_ranges[ch] = voltage_range
                if sensor_id and sensor_id in self._loaded_scope_sensors:
                    self._loaded_channel_sensor_configs[ch] = dict(
                        self._loaded_scope_sensors[sensor_id]
                    )
                else:
                    self._loaded_channel_sensor_configs[ch] = {}

        return version

    def _loaded_channel_units(self, f: 'h5py.File') -> dict[int, str]:
        """Return per-channel unit strings from /metadata/channels in an open file."""
        def decode(x):
            return x.decode() if isinstance(x, bytes) else str(x)

        ch_units: dict[int, str] = {}
        meta_grp = f.get("metadata")
        if meta_grp is not None and "channels" in meta_grp:
            for ch_str, cg in meta_grp["channels"].items():
                ch_units[int(ch_str)] = decode(cg.attrs.get("unit", "mV"))
        return ch_units

    def _read_frame_group(self, fg: 'h5py.Group', ch_units: dict[int, str],
                          version: int) -> dict[int, 'rev80.VibeSample']:
        """Read one HDF5 frame group into a dict[int, VibeSample]."""
        def decode(x):
            return x.decode() if isinstance(x, bytes) else str(x)

        ts_str     = decode(fg.attrs["timestamp"])
        rel_time   = float(fg.attrs["rel_time"])
        samplerate = float(fg.attrs["samplerate"])
        status     = decode(fg.attrs["status"])
        try:
            timestamp = datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            timestamp = datetime.now()

        frame_samples: dict[int, rev80.VibeSample] = {}
        for ch_str, cg in fg.items():
            if not ch_str.isdigit():
                continue
            ch   = int(ch_str)
            data = np.ascontiguousarray(cg["data"][()], dtype=np.float64)
            unit = "mV" if version >= 4 else ch_units.get(ch, "mV")
            # _write_channel_group has always stored these; they were simply
            # never read back, so every reloaded file looked clean no matter
            # what happened during capture. Older files predate the attrs.
            overflow = bool(cg.attrs.get("overflow", False))
            degraded = bool(cg.attrs.get("degraded", False))
            frame_samples[ch] = rev80.VibeSample(
                status=status, _timestamp=timestamp, samplerate=samplerate,
                unit=unit, overflow=overflow, degraded=degraded,
                data=data, rel_time=rel_time,
            )
        return frame_samples

    def _post_load(self) -> None:
        """Sync config from frame data and signal GUI after any load operation."""
        n = len(self.data["frame_cache"])
        log.debug(f"Loaded {n} frames into frame cache")
        self._cache_cursor = 0  # always start at the most-recent frame

        if not n:
            return

        # Sync enabled_channels from frame data and clamp maxfreq to file samplerate
        all_channels: set[int] = set()
        file_samplerate: float = 0.0
        for frame in self.data["frame_cache"]:
            for k, v in frame.items():
                if isinstance(k, int):
                    all_channels.add(k)
                    if v.samplerate > file_samplerate:
                        file_samplerate = v.samplerate

        if all_channels:
            self.config.enabled_channels = sorted(all_channels)

        if file_samplerate > 0 and self.config.samplerate < file_samplerate:
            self.config.maxfreq = file_samplerate / 2

        self.init_trend_channels()
        self.reprocess_last_block()

    def load_monitor_session(self, session_h5: Path) -> None:
        """Load all interval frames from a monitor session into frame_cache.

        Reads /metadata/ for config restore, then all /monitor/{N}/ groups in order.
        The frame_cache is resized to hold all N captures so every frame is browsable.
        """
        if not session_h5.is_file():
            log.error(f"load_monitor_session: file does not exist: {session_h5}")
            return

        log.info(f"Reading monitor session {session_h5.name}")
        self.data["frame_cache"].clear()
        self.trend = {}
        self._loaded_channel_sensor_configs = {}
        self._loaded_scope_sensors = {}

        import json as _json
        trend_rel_times: dict[int, list] = {}
        trend_overalls:  dict[int, list] = {}

        with h5py.File(session_h5, "r") as f:
            version  = self._restore_metadata(f)
            ch_units = self._loaded_channel_units(f)

            mon_grp = f.get("monitor")
            if mon_grp is None:
                log.error(f"load_monitor_session: no /monitor group in {session_h5}")
                return

            keys = sorted(mon_grp.keys(), key=int)
            self.resize_frame_cache(max(len(keys), 1))  # expand deque to hold all N captures
            for key in keys:
                grp = mon_grp[key]
                frame = self._read_frame_group(grp, ch_units, version)
                self.data["frame_cache"].append(frame)
                # Collect stored overall values for trend reconstruction
                rel_t = float(grp.attrs.get("rel_time", 0.0))
                try:
                    overall = _json.loads(grp.attrs.get("overall_json", "{}"))
                except Exception:
                    overall = {}
                for ch_str, val in overall.items():
                    ch = int(ch_str)
                    trend_rel_times.setdefault(ch, []).append(rel_t)
                    trend_overalls.setdefault(ch, []).append(float(val))

        n = len(self.data["frame_cache"])
        self._post_load()  # clears trend, reprocesses last frame
        log.info(f"Loaded {n} captures from {session_h5.name}")

        # Rebuild trend from stored overall_json — overwrites the single point
        # added by reprocess_last_block() with the full session history.
        #
        # overall_json values are in the TARGET unit recorded at capture time,
        # not raw mV.  get_trend_for_display() expects orders[:,col] in raw mV
        # (same as overall_ampl_by_integration_order), so we back-scale each
        # channel's values and place them in the correct column.
        from rev80.util import UNIT_TO_SI, amplitude_scale, integration_steps
        for ch, rel_times in trend_rel_times.items():
            overalls    = np.array(trend_overalls[ch])
            sensor_cfg  = self._loaded_channel_sensor_configs.get(ch, {})
            sensor_eu   = sensor_cfg.get('engineering_units', 'mV')
            sensitivity = float(sensor_cfg.get('sensitivity', 1.0))
            rec_tgt     = self.config.channel_target_units.get(ch, sensor_eu) or sensor_eu
            amp_mode    = self.config.channel_amplitude_modes.get(ch, '0-P') or '0-P'

            n_steps   = integration_steps(sensor_eu, rec_tgt)
            col       = max(0, min(4, n_steps + 2))
            src_si    = UNIT_TO_SI.get(sensor_eu, 1.0)
            tgt_si    = UNIT_TO_SI.get(rec_tgt,   1.0)
            amp_f     = amplitude_scale(amp_mode)
            scale     = src_si / tgt_si / sensitivity

            orders           = np.zeros((len(overalls), 5))
            # Reverse the display scaling so get_trend_for_display re-applies it correctly
            orders[:, col]   = overalls / (scale * amp_f) if (scale * amp_f) != 0 else overalls
            self.trend[ch]   = {
                "rel_times": np.array(rel_times),
                "orders":    orders,
            }
        if trend_rel_times:
            log.debug(f"Reconstructed trend from {n} monitor frame attrs")

    def load_monitor_capture(self, session_h5: Path, capture_index: int) -> None:
        """Load a single interval capture frame into frame_cache and trigger display.

        Reads /metadata/ for config restore, then /monitor/{capture_index}/ for data.
        """
        if not session_h5.is_file():
            log.error(f"load_monitor_capture: file does not exist: {session_h5}")
            return

        log.info(f"Loading capture {capture_index} from {session_h5.name}")

        self.data["frame_cache"].clear()
        self.trend = {}
        self._loaded_channel_sensor_configs = {}
        self._loaded_scope_sensors = {}

        with h5py.File(session_h5, "r") as f:
            version  = self._restore_metadata(f)
            ch_units = self._loaded_channel_units(f)

            mon_grp = f.get("monitor")
            if mon_grp is None:
                log.error(f"load_monitor_capture: no /monitor group in {session_h5}")
                return

            key = str(capture_index)
            if key not in mon_grp:
                log.error(
                    f"load_monitor_capture: capture {capture_index} not found in {session_h5}"
                )
                return

            frame = self._read_frame_group(mon_grp[key], ch_units, version)
            self.data["frame_cache"].append(frame)

        log.debug(f"Loaded monitor capture {capture_index} from {session_h5}")
        self._post_load()

    def load_monitor_burst(self, session_h5: Path, burst_id: str) -> None:
        """Load all frames from a burst event into frame_cache and trigger display.

        Reads /metadata/ for config restore, then /burst/{burst_id}/{0..N-1}/ for data.
        """
        if not session_h5.is_file():
            log.error(f"load_monitor_burst: file does not exist: {session_h5}")
            return

        log.info(f"Loading burst {burst_id!r} from {session_h5.name}")

        self.data["frame_cache"].clear()
        self.trend = {}
        self._loaded_channel_sensor_configs = {}
        self._loaded_scope_sensors = {}

        import json as _json
        trend_rel_times: dict[int, list] = {}
        trend_overalls:  dict[int, list] = {}

        with h5py.File(session_h5, "r") as f:
            version  = self._restore_metadata(f)
            ch_units = self._loaded_channel_units(f)

            burst_grp = f.get("burst")
            if burst_grp is None:
                log.error(f"load_monitor_burst: no /burst group in {session_h5}")
                return

            bid_grp = burst_grp.get(burst_id)
            if bid_grp is None:
                log.error(
                    f"load_monitor_burst: burst '{burst_id}' not found in {session_h5}"
                )
                return

            n_frames     = int(bid_grp.attrs.get("n_frames", len(bid_grp)))
            n_pretrigger = int(bid_grp.attrs.get("n_pretrigger_frames", 0))

            # Expand cache before the append loop so pre-trigger frames aren't
            # silently evicted when n_frames exceeds the current deque maxlen.
            self.resize_frame_cache(max(n_frames, 1))

            # Rebase rel_times so trigger frame = 0, pre-trigger = negative.
            # Use the trigger frame's own stored rel_time as origin (same time scale).
            import math as _math
            trigger_frame_grp = bid_grp.get(str(n_pretrigger))
            if trigger_frame_grp is not None:
                raw_trigger = float(trigger_frame_grp.attrs.get("rel_time", 0.0))
                trigger_rel = raw_trigger if _math.isfinite(raw_trigger) else 0.0
            else:
                trigger_rel = 0.0

            for fi in range(n_frames):
                fi_grp = bid_grp.get(str(fi))
                if fi_grp is None:
                    continue
                frame = self._read_frame_group(fi_grp, ch_units, version)
                # Rebase each VibeSample's rel_time to trigger=0 so the browse
                # cursor (which reads v.rel_time) aligns with the rebased trend.
                raw_rel_t_f = float(fi_grp.attrs.get("rel_time", 0.0))
                raw_rel_t = raw_rel_t_f if _math.isfinite(raw_rel_t_f) else 0.0
                rel_t = raw_rel_t - trigger_rel
                for s in frame.values():
                    if hasattr(s, 'rel_time'):
                        s.rel_time = rel_t
                self.data["frame_cache"].append(frame)
                # Per-frame overall for trend (all frames now have overall_json)
                raw_overall = fi_grp.attrs.get("overall_json", None)
                if raw_overall is not None:
                    try:
                        overall = _json.loads(raw_overall)
                        for ch_str, val in overall.items():
                            ch = int(ch_str)
                            trend_rel_times.setdefault(ch, []).append(rel_t)
                            trend_overalls.setdefault(ch, []).append(float(val))
                    except Exception:
                        pass

        n = len(self.data["frame_cache"])
        log.debug(f"Loaded {n} burst frames for '{burst_id}' from {session_h5}")
        self._post_load()

        # Rebuild trend from per-frame overall_json.
        # overall_json is in target EU — inverse-scale to raw mV so
        # get_trend_for_display() can apply the forward conversion correctly.
        import math as _math
        from rev80.util import UNIT_TO_SI, amplitude_scale, integration_steps
        for ch, rel_times in trend_rel_times.items():
            overalls = trend_overalls[ch]
            valid = [(t, v) for t, v in zip(rel_times, overalls)
                     if _math.isfinite(t) and _math.isfinite(v)]
            if not valid:
                continue
            vt, vv = zip(*valid)
            sensor_cfg  = self._loaded_channel_sensor_configs.get(ch, {})
            sensor_eu   = sensor_cfg.get('engineering_units', 'mV')
            sensitivity = float(sensor_cfg.get('sensitivity', 1.0))
            rec_tgt     = self.config.channel_target_units.get(ch, sensor_eu) or sensor_eu
            amp_mode    = self.config.channel_amplitude_modes.get(ch, '0-P') or '0-P'
            n_steps  = integration_steps(sensor_eu, rec_tgt)
            col      = max(0, min(4, n_steps + 2))
            src_si   = UNIT_TO_SI.get(sensor_eu, 1.0)
            tgt_si   = UNIT_TO_SI.get(rec_tgt,   1.0)
            amp_f    = amplitude_scale(amp_mode)
            scale    = src_si / tgt_si / sensitivity
            orders         = np.zeros((len(vv), 5))
            orders[:, col] = np.array(vv) / (scale * amp_f) if (scale * amp_f) != 0 else np.array(vv)
            self.trend[ch] = {"rel_times": np.array(vt), "orders": orders}
        if trend_rel_times:
            log.debug(f"Reconstructed burst trend from {len(trend_rel_times)} channels")

    def reprocess_session_trend(self, session_h5: Path,
                                 progress_cb=None) -> int:
        """Re-derive overall_json for every /monitor/N/ using the current config.

        Reads stored raw-mV arrays, runs process_sample() with the currently wired
        sensor config, and overwrites the overall_json attr on each capture group.
        Call after saving new sensor/channel config to keep the trend consistent.
        Returns the number of captures processed.
        """
        import json as _json
        from rev80.sample import VibeSample
        from datetime import datetime as _dt, timezone as _tz

        log.info(f"Reprocessing session trend in {session_h5.name}")
        with h5py.File(session_h5, "a") as f:
            mon_grp = f.get("monitor")
            if mon_grp is None:
                log.error(f"reprocess_session_trend: no /monitor group in {session_h5}")
                return 0
            keys = sorted(mon_grp.keys(), key=int)
            n    = len(keys)
            for i, key in enumerate(keys):
                grp     = mon_grp[key]
                overall = {}
                for ch_str in [k for k in grp.keys() if k.isdigit()]:
                    ch   = int(ch_str)
                    data = np.asarray(grp[ch_str]["data"][()], dtype=np.float64)
                    ts   = str(grp.attrs.get("timestamp", ""))
                    sr   = int(grp.attrs.get("samplerate", self.config.samplerate))
                    try:
                        ts_dt = _dt.fromisoformat(ts)
                    except ValueError:
                        # utcnow() is deprecated. Naive-UTC is preserved
                        # deliberately: making this aware would change the
                        # stored isoformat string and could raise TypeError
                        # against the naive timestamps read alongside it.
                        ts_dt = _dt.now(_tz.utc).replace(tzinfo=None)
                    sample = VibeSample(
                        status="OK", _timestamp=ts_dt,
                        samplerate=sr, unit="mV", overflow=False, data=data,
                    )
                    try:
                        result = self.process_sample(ch, sample)
                    except Exception as exc:
                        log.warning(f"reprocess_session_trend: skipped cap={key} ch={ch}: {exc}")
                        continue
                    if result is not None:
                        overall[str(ch)] = float(result.overall)
                grp.attrs["overall_json"] = _json.dumps(overall)
                if progress_cb:
                    progress_cb(i + 1, n)

        # Also reprocess per-frame overall_json inside each burst event
        with h5py.File(session_h5, "a") as f:
            burst_grp = f.get("burst")
            if burst_grp is not None:
                for burst_id, bid_grp in burst_grp.items():
                    if not hasattr(bid_grp, 'keys'):
                        continue
                    for fi_str in [k for k in bid_grp.keys() if k.isdigit()]:
                        fi_grp  = bid_grp[fi_str]
                        overall = {}
                        for ch_str in [k for k in fi_grp.keys() if k.isdigit()]:
                            ch   = int(ch_str)
                            data = np.asarray(fi_grp[ch_str]["data"][()], dtype=np.float64)
                            ts   = str(fi_grp.attrs.get("timestamp", ""))
                            sr   = int(fi_grp.attrs.get("samplerate", self.config.samplerate))
                            try:
                                ts_dt = _dt.fromisoformat(ts)
                            except ValueError:
                                # See note above: deliberately naive-UTC.
                                ts_dt = _dt.now(_tz.utc).replace(tzinfo=None)
                            sample = VibeSample(
                                status="OK", _timestamp=ts_dt,
                                samplerate=sr, unit="mV", overflow=False, data=data,
                            )
                            try:
                                result = self.process_sample(ch, sample)
                            except Exception as exc:
                                log.warning(f"reprocess_session_trend: skipped burst={burst_id} fi={fi_str} ch={ch}: {exc}")
                                continue
                            if result is not None:
                                overall[str(ch)] = float(result.overall)
                        fi_grp.attrs["overall_json"] = _json.dumps(overall)

        log.info(f"Reprocessed {n} captures in {session_h5.name}")
        return n
