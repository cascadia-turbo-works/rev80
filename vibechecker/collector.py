# Data Collector

import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Dict, Union

import h5py
import numpy as np
import scipy.signal

import vibechecker
from vibechecker._paths import data_dir
from vibechecker.scope_sensor import ScopeSensor

log = vibechecker.get_logger("collector")

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
        sensor: Union[vibechecker.VibeSensor, None] = None,
        config: Union[vibechecker.AcquisitionSettings, None] = None,
    ):

        self.sensor: Union[vibechecker.VibeSensor, None] = None
        self.stream = None
        self.datadir: Path = data_dir()
        self.data: Dict = {}
        self.config = config if config else vibechecker.AcquisitionSettings()
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
        from vibechecker.util import UNIT_TO_SI, AMPLITUDE_SCALE, integration_steps
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
            amp_factor = AMPLITUDE_SCALE.get(amp_mode, np.sqrt(2))
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

    def connect_sensor(self, sensor: vibechecker.VibeSensor, siggen_config: dict | None = None):
        """Connect to a device and initialise its stream."""
        if not isinstance(sensor, vibechecker.VibeSensor):
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
        samples: dict[int, vibechecker.VibeSample] = {}

        samplerate = samp.get("samplerate", self.config.samplerate)
        for i, ch in enumerate(channels):
            col  = min(i, data_arr.shape[1] - 1)
            data = np.ascontiguousarray(data_arr[:, col], dtype=np.float64)
            samples[ch] = vibechecker.VibeSample(
                status=samp["status"],
                _timestamp=samp["timestamp"],
                samplerate=samplerate,
                unit="mV",
                overflow=bool(overflow_mask & (1 << ch)),
                data=data,
                rel_time=samp["rel_time"],
                label=f"Ch{chr(65 + ch)}",
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

    def process_sample(self, ch: int, sample: 'vibechecker.VibeSample') -> 'vibechecker.ChannelResult | None':
        """Filter, compute PSD, 5-order mV overalls, and convert to display units.

        Side-effects on sample (cached after first call per config):
          - psd_mv / freq_hz / _psd_config_key
          - overall_ampl_by_integration_order — (5,) RMS overalls in mV, orders −2…+2
        """
        from vibechecker.util import UNIT_TO_SI, AMPLITUDE_SCALE, integration_steps

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
        nyq            = samplerate / 2.0

        # ── 1. Butterworth filter ─────────────────────────────────────
        filtered_mv = sample.data.copy()
        order = config._BUTTER_ORDER
        if config.highpass_enabled and config.highpass_fc < nyq:
            sos = scipy.signal.butter(order, config.highpass_fc,
                                      btype='highpass', fs=samplerate, output='sos')
            filtered_mv = scipy.signal.sosfilt(sos, filtered_mv)
        if config.lowpass_enabled and config.lowpass_fc < nyq:
            sos = scipy.signal.butter(order, config.lowpass_fc,
                                      btype='lowpass', fs=samplerate, output='sos')
            filtered_mv = scipy.signal.sosfilt(sos, filtered_mv)

        # ── 2. Welch PSD in mV² — compute once, cache on sample ──────
        psd_key = (config.fft_window, config.welch_overlap,
                   config.highpass_enabled, config.highpass_fc,
                   config.lowpass_enabled, config.lowpass_fc)
        if sample.psd_mv is None or sample._psd_config_key != psd_key:
            nfft     = int(samplerate / config.binsize)
            nperseg  = nfft
            noverlap = min(sample.blocksize - 1, int(nperseg * config.welch_overlap))
            freq_hz, psd_mv = scipy.signal.welch(
                filtered_mv, fs=float(samplerate),
                window=config.fft_window, nperseg=nperseg, noverlap=noverlap,
                nfft=nfft, scaling='spectrum', detrend='linear', average='mean',
            )
            sample.psd_mv          = psd_mv
            sample.freq_hz         = freq_hz
            sample._psd_config_key = psd_key

            # ── 3. 5-order mV RMS overalls, orders −2…+2 ─────────────
            pos = freq_hz > 0   # DC bin excluded from integration factors
            for i, n_ord in enumerate(range(-2, 3)):   # i=0 → ord=-2, i=2 → ord=0
                if n_ord != 0:
                    omega        = np.zeros_like(psd_mv)
                    omega[pos]   = (2 * np.pi * freq_hz[pos]) ** (2 * n_ord)
                    psd_ord      = psd_mv * omega
                else:
                    psd_ord = psd_mv
                band = np.sqrt(np.maximum(psd_ord, 0.0))
                sample.overall_ampl_by_integration_order[i] = float(np.sqrt(np.sum(np.square(band))))
        else:
            freq_hz = sample.freq_hz
            psd_mv  = sample.psd_mv

        # ── 4. Integrate / scale mV² PSD → target-unit² PSD ─────────
        n_steps = integration_steps(sensor_eu, effective_tgt)
        if n_steps != 0:
            omega_factor       = np.zeros_like(psd_mv)
            pos                = freq_hz > 0
            omega_factor[pos]  = (2 * np.pi * freq_hz[pos]) ** (2 * n_steps)
            integrated_psd     = psd_mv * omega_factor
        else:
            integrated_psd = psd_mv.copy()

        # mV² → EU²: /sensitivity²;  EU² → target²: (SI[EU]/SI[target])²
        src_si = UNIT_TO_SI.get(sensor_eu, 1.0)
        tgt_si = UNIT_TO_SI.get(effective_tgt, 1.0)
        calibrated_psd = integrated_psd * (src_si / tgt_si / sensitivity_mv) ** 2

        # ── 5. Amplitude spectrum in target unit + amp mode ───────────
        amp_factor   = AMPLITUDE_SCALE.get(amp_mode, np.sqrt(2))
        spectrum_amp = np.sqrt(np.maximum(calibrated_psd, 0.0)) * amp_factor

        # ── 6. Peaks ──────────────────────────────────────────────────
        peaks, _ = scipy.signal.find_peaks(spectrum_amp, distance=5)
        peaks     = np.array(peaks[np.argsort(-spectrum_amp[peaks])])

        # ── 7. Overall amplitude in target unit ───────────────────────
        band     = spectrum_amp
        band_rms = band / amp_factor
        overall  = float(np.sqrt(np.sum(np.square(band_rms)))) * amp_factor

        # ── 8. Time-domain signal — inline FFT integration ───────────
        # Separate rfft of filtered_mv preserves phase; Welch above cannot
        # be reused because segment-averaging discards phase information.
        N          = sample.blocksize
        rfft_mv    = np.fft.rfft(filtered_mv)
        freq_td    = np.fft.rfftfreq(N, d=1.0 / samplerate)
        eu_scale   = src_si / tgt_si / sensitivity_mv
        if n_steps != 0:
            omega_td    = 2 * np.pi * freq_td
            omega_td[0] = 1.0
            transfer       = np.power(1j * omega_td, n_steps)
            transfer[0]    = 0.0
            rfft_target    = rfft_mv * transfer * eu_scale
        else:
            rfft_target = rfft_mv * eu_scale
        time_signal = np.fft.irfft(rfft_target, n=N)

        return vibechecker.ChannelResult(
            channel=ch, unit=effective_tgt, overflow=sample.overflow,
            time_data=time_signal, time_vec=sample.time_vec, samplerate=samplerate,
            freq=freq_hz, spectrum=spectrum_amp, peaks=peaks, overall=overall,
            timestamp=sample._timestamp, rel_time=sample.rel_time, status=sample.status,
        )

    def process_samples(self) -> list['vibechecker.ChannelResult']:
        """Process the current frame; return one ChannelResult per enabled channel.

        Uses the latest frame when streaming; uses _cache_cursor when browsing.
        Appends to trend only during streaming.
        """
        cache = self.data["frame_cache"]
        if not cache:
            return []
        idx   = -1 if self.is_streaming else -1 - self._cache_cursor
        frame = cache[idx]
        results: list[vibechecker.ChannelResult] = []
        for ch in sorted(self.config.enabled_channels):
            sample = frame.get(ch)
            if sample is None or sample.blocksize <= 1:
                continue
            result = self.process_sample(ch, sample)
            if result is None:
                continue
            if self.is_streaming:
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
        """Save frame cache and trend history to an HDF5 file (v3 format).

        Layout::

            /metadata                               group
            /metadata.attrs                         version, notes
            /metadata/acquisition                   group
            /metadata/acquisition.attrs             maxfreq, binsize, fft_window,
                                                    welch_overlap, highpass_enabled,
                                                    highpass_fc, lowpass_enabled, lowpass_fc,
                                                    trend_max_points
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
        with h5py.File(target, "w") as f:
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
                    fg.create_group(str(ch)).create_dataset("data", data=sample.data)

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

        def decode(x):
            return x.decode() if isinstance(x, bytes) else str(x)

        self.data["frame_cache"].clear()
        self.trend = {}
        self._loaded_channel_sensor_configs = {}
        self._loaded_scope_sensors = {}

        with h5py.File(target, "r") as f:
            version = int(f["metadata"].attrs.get("version", 3))
            if version >= 4:
                self._load_v4(f, decode)
            else:
                self._load_v3(f, decode)
                # Promote v3 single-overall trend to v4 orders array (order-0 column only)
                for ch, td_old in self.data.pop("_trend_v3", {}).items():
                    if td_old.get("overall"):
                        M      = len(td_old["overall"])
                        orders = np.zeros((M, 5))
                        orders[:, 2] = np.array(td_old["overall"])  # col 2 = order 0
                        self.trend[ch] = {
                            "rel_times": np.array(td_old["rel_times"]),
                            "orders":    orders,
                        }

        n = len(self.data["frame_cache"])
        log.debug(f"Loaded {n} frames from {target}")

        if not n:
            return

        # Sync enabled_channels from frame data and clamp maxfreq to file samplerate
        all_channels: set[int] = set()
        file_samplerate: int = 0
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

    # ------------------------------------------------------------------
    # Private HDF5 format readers
    # ------------------------------------------------------------------

    def _load_v3(self, f: "h5py.File", decode) -> None:
        """Read v3 format: structured /metadata group, sensor library, shared trend axis."""
        meta_grp = f["metadata"]
        self.notes = decode(meta_grp.attrs.get("notes", ""))

        # Acquisition settings — replace config wholesale; channel dicts populated below
        if "acquisition" in meta_grp:
            acq_dict = {k: (None if v == "" else v) for k, v in meta_grp["acquisition"].attrs.items()}
            self.config = vibechecker.AcquisitionSettings.from_dict(acq_dict)

        # Scope sensor library — {sensor_id: dict}
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
                d["id"] = sid  # ensure id matches group name
                self._loaded_scope_sensors[sid] = d

        # Channel metadata — restore names, target units, and sensor configs
        ch_units: dict[int, str] = {}
        if "channels" in meta_grp:
            for ch_str, cg in meta_grp["channels"].items():
                ch = int(ch_str)
                name = decode(cg.attrs.get("name", ""))
                unit = decode(cg.attrs.get("unit", "mV"))
                target_unit = decode(cg.attrs.get("target_unit", ""))
                sensor_id = decode(cg.attrs.get("scope_sensor_id", ""))
                coupling = decode(cg.attrs.get("coupling", "AC"))
                voltage_range = int(cg.attrs.get("voltage_range", 7))
                amplitude_mode = decode(cg.attrs.get("amplitude_mode", ""))
                if name:
                    self.config.channel_names[ch] = name
                if target_unit:
                    self.config.channel_target_units[ch] = target_unit
                if amplitude_mode:
                    self.config.channel_amplitude_modes[ch] = amplitude_mode
                self.config.channel_couplings[ch] = coupling
                self.config.channel_voltage_ranges[ch] = voltage_range
                ch_units[ch] = unit
                if sensor_id and sensor_id in self._loaded_scope_sensors:
                    self._loaded_channel_sensor_configs[ch] = dict(self._loaded_scope_sensors[sensor_id])
                else:
                    self._loaded_channel_sensor_configs[ch] = {}

        # Frames
        if "frames" not in f:
            return
        for idx in sorted(f["frames"].keys(), key=int):
            fg = f["frames"][idx]
            ts_str = decode(fg.attrs["timestamp"])
            rel_time = float(fg.attrs["rel_time"])
            samplerate = int(fg.attrs["samplerate"])
            status = decode(fg.attrs["status"])
            try:
                timestamp = datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                timestamp = datetime.now()

            frame_samples: dict[int, vibechecker.VibeSample] = {}
            for ch_str, cg in fg.items():
                if not ch_str.isdigit():
                    continue
                ch = int(ch_str)
                data = np.ascontiguousarray(cg["data"][()], dtype=np.float64)
                # v3 files stored EU-converted data; load as-is with recorded unit
                unit = ch_units.get(ch, "mV")
                frame_samples[ch] = vibechecker.VibeSample(
                    status=status, _timestamp=timestamp, samplerate=samplerate,
                    unit=unit, overflow=False, data=data, rel_time=rel_time,
                )
            self.data["frame_cache"].append(frame_samples)

        # Trend — store in temporary key; load_data() promotes to self.trend
        if "trend" in f:
            trend_grp = f["trend"]
            shared_rel_times: list = []
            if "rel_times" in trend_grp:
                shared_rel_times = list(np.array(trend_grp["rel_times"][()]))
            v3_trend: dict = {}
            for ch_str, tg in trend_grp.items():
                if not ch_str.isdigit():
                    continue
                v3_trend[int(ch_str)] = {
                    "rel_times": shared_rel_times,
                    "overall":   list(np.array(tg["data"][()])),
                }
            self.data["_trend_v3"] = v3_trend

    def _load_v4(self, f: "h5py.File", decode) -> None:
        """Read v4 format: raw mV frames, per-channel (M,5) trend matrix."""
        # Metadata loading is identical to v3
        self._load_v3(f, decode)
        # _load_v3 stored trend in data["_trend_v3"] — discard it for v4 files
        self.data.pop("_trend_v3", None)

        # Overwrite frames with unit='mV' (v3 loader used ch_units which may be EU)
        # Re-load frames directly
        self.data["frame_cache"].clear()
        if "frames" in f:
            for idx in sorted(f["frames"].keys(), key=int):
                fg = f["frames"][idx]
                ts_str    = decode(fg.attrs["timestamp"])
                rel_time  = float(fg.attrs["rel_time"])
                samplerate = int(fg.attrs["samplerate"])
                status    = decode(fg.attrs["status"])
                try:
                    timestamp = datetime.fromisoformat(ts_str)
                except (ValueError, TypeError):
                    timestamp = datetime.now()
                frame_samples: dict[int, vibechecker.VibeSample] = {}
                for ch_str, cg in fg.items():
                    if not ch_str.isdigit():
                        continue
                    ch   = int(ch_str)
                    data = np.ascontiguousarray(cg["data"][()], dtype=np.float64)
                    frame_samples[ch] = vibechecker.VibeSample(
                        status=status, _timestamp=timestamp, samplerate=samplerate,
                        unit='mV', overflow=False, data=data, rel_time=rel_time,
                    )
                self.data["frame_cache"].append(frame_samples)

        # Trend — per-channel (M,5) orders matrix + rel_times
        if "trend" in f:
            for ch_str, cg in f["trend"].items():
                if not ch_str.isdigit():
                    continue
                ch = int(ch_str)
                self.trend[ch] = {
                    "rel_times": np.array(cg["rel_times"][()], dtype=np.float64),
                    "orders":    np.array(cg["orders"][()],    dtype=np.float64),
                }
