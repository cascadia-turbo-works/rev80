# Data Collector

import threading
import time
import numpy as np
import scipy.signal
import h5py
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Union, Dict

from vibechecker._paths import data_dir

import vibechecker
from vibechecker.scope_sensor import ScopeSensor

log = vibechecker.get_logger('collector')

_FRAME_CACHE_SIZE = 32


class DataCollector:
    """Collect, filter, cache, and persist multi-channel vibration data.

    Pipeline
    --------
    Hardware callback → receive_data()
        per channel: mV→EU conversion + Butterworth filter → VibeSample
        → frame_cache.append(dict[int, VibeSample])
        → data_callback() → registered GUI callbacks
    """

    def __init__(self,
                 sensor: Union[vibechecker.VibeSensor, None] = None,
                 config: Union[vibechecker.AcquisitionSettings, None] = None):

        self.sensor: Union[vibechecker.VibeSensor, None] = None
        self.stream = None
        self.datadir: Path = data_dir()
        self.data: Dict = {}
        self.config = config if config else vibechecker.AcquisitionSettings()
        self.scope_sensors: dict[int, ScopeSensor] = {}
        self.callbacks: dict = {}
        self._cache_cursor: int = 0
        self.siggen_config: dict | None = None
        self._last_frame_t: float | None = None   # arrival time of previous frame
        self._lag_warn_t: float = 0.0             # wall time of last lag warning

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

        Priority: scope_sensor.effective_target_unit() > VibeSensor unit > 'mV'.
        """
        scope_sensor = self.scope_sensors.get(ch)
        if scope_sensor is not None:
            return scope_sensor.effective_target_unit()
        if self.sensor is not None:
            unit = getattr(self.sensor, 'unit', None)
            if isinstance(unit, list):
                return unit[min(ch, len(unit) - 1)]
            if unit is not None:
                return unit
        return 'mV'

    # ------------------------------------------------------------------
    # Stream state
    # ------------------------------------------------------------------

    @property
    def is_streaming(self):
        try:
            return self.sensor and self.stream and self.stream.active
        except Exception:
            log.error('Device connection may be interrupted')
            return False

    # ------------------------------------------------------------------
    # Data store
    # ------------------------------------------------------------------

    def reset_data_store(self):
        self.data = {
            'meta':        [],
            'frame_cache': deque(maxlen=_FRAME_CACHE_SIZE),  # dict[int, VibeSample]
            'frame_count': 0,
            'trend':       {},   # dict[int, {'rel_times': list, 'overall': list}]
        }
        self._cache_cursor = 0
        self.init_trend_channels()
        log.info('Reset data store.')

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
        self.config.enabled_channels = sorted(
            ch for ch in self.config.enabled_channels if ch in valid
        )
        if not self.config.enabled_channels:
            self.config.enabled_channels = [0]

        self.reset_data_store()
        log.info(f'Channel config reset for {num_channels}-channel device.')

    def init_trend_channels(self):
        """(Re-)initialise trend store keyed by current enabled_channels.

        Channels already in the store are preserved; new channels get empty
        lists; channels no longer enabled are dropped.
        """
        enabled = set(self.config.enabled_channels)
        self.data['trend'] = {
            ch: self.data['trend'].get(ch, {'rel_times': [], 'overall': []})
            for ch in sorted(enabled)
        }

    def update_trend(self, ch: int, rel_time: float, overall: float) -> None:
        """Append one (rel_time, overall) point for a channel; prune to cap."""
        if ch not in self.data['trend']:
            self.data['trend'][ch] = {'rel_times': [], 'overall': []}
        td = self.data['trend'][ch]
        td['rel_times'].append(rel_time)
        td['overall'].append(overall)
        cap = self.config.trend_max_points
        if len(td['rel_times']) > cap:
            td['rel_times'] = td['rel_times'][-cap:]
            td['overall'] = td['overall'][-cap:]

    def clear_trend(self) -> None:
        """Wipe all accumulated trend data (call after unit/freq-window changes)."""
        for ch in self.data['trend']:
            self.data['trend'][ch] = {'rel_times': [], 'overall': []}
        log.debug('Trend data cleared.')

    # ------------------------------------------------------------------
    # Frame cache navigation
    # ------------------------------------------------------------------

    def reprocess_last_block(self) -> None:
        """Re-deliver the currently displayed cached frame to GUI callbacks.

        Use after display settings change (units, sensor, freq window) while
        the stream is stopped to refresh plots without new hardware data.
        Bypasses data_callback to avoid appending a duplicate frame or
        resetting the browse cursor.
        """
        cache = self.data['frame_cache']
        if not cache:
            return
        idx = min(self._cache_cursor, len(cache) - 1)
        frame = cache[-(idx + 1)]
        for fn in self.callbacks.values():
            fn(frame)

    def browse_frame(self, delta: int) -> None:
        """Move the cache cursor by delta and redisplay.

        Positive delta goes older; negative goes newer.
        Only meaningful when the stream is stopped.
        """
        cache = self.data['frame_cache']
        if not cache:
            return
        self._cache_cursor = max(0, min(self._cache_cursor + delta,
                                        len(cache) - 1))
        self.reprocess_last_block()

    # ------------------------------------------------------------------
    # Sensor connection
    # ------------------------------------------------------------------

    def connect_sensor(self, sensor: vibechecker.VibeSensor,
                       siggen_config: dict | None = None):
        """Connect to a device and initialise its stream."""
        if not isinstance(sensor, vibechecker.VibeSensor):
            raise TypeError(f'Attempted to select invalid sensor of {type(sensor)}')

        if self.stream is not None or self.sensor is not None:
            self.disconnect_sensor()

        if self.config is None:
            log.error('Attempted to connect sensor but no configuration set')
            return

        self.sensor = sensor
        self.stream = self.sensor.connect(self.config, self.receive_data,
                                          siggen_config=siggen_config)
        log.debug(f'Connected sensor {self.sensor}')

    def disconnect_sensor(self):
        if self.is_streaming:
            self.stop_stream()

        if self.stream is not None:
            self.stream.close()
            self.stream = None

        if self.sensor:
            log.debug(f'Disconnecting sensor {self.sensor}')
            self.sensor = None

    # ------------------------------------------------------------------
    # Stream control
    # ------------------------------------------------------------------

    def start_stream(self):
        """Initiate sensor stream."""
        if self.is_streaming:
            log.warning('Attempted Start Stream: Already Running')
            return
        if not self.stream:
            return
        try:
            self.stream.start()
        except Exception as e:
            self.disconnect_sensor()
            log.error(f'Error starting stream: {e}')
        log.debug('Stream started')

    def stop_stream(self):
        """Terminate sensor stream."""
        if not self.stream or not self.is_streaming:
            log.warning('Attempted Stop Stream: No stream running')
            return
        self.stream.stop()
        log.debug('Stream stopped')

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
        self.stream = sensor.connect(self.config, self.receive_data,
                                     siggen_config=self.siggen_config)
        if was_streaming:
            self.start_stream()

    # ------------------------------------------------------------------
    # Single-shot capture
    # ------------------------------------------------------------------

    def collect_sample(self) -> dict:
        """Collect one block from each enabled channel.

        Returns dict[int, VibeSample].  The captured frame is stored in
        frame_cache via the normal data_callback path.
        """
        if self.is_streaming:
            self.stop_stream()

        captured: dict = {}
        done = threading.Event()

        def _one_shot(samples: dict):
            captured.update(samples)
            done.set()

        self.callbacks['_collect_sample'] = _one_shot
        self.start_stream()
        done.wait(timeout=self.config.acquisition_period * 3)
        self.stop_stream()
        self.callbacks.pop('_collect_sample', None)

        return captured

    # ------------------------------------------------------------------
    # Data pipeline
    # ------------------------------------------------------------------

    def receive_data(self, samp: dict):
        """Preprocess one hardware block: fan out to per-channel VibeSamples.

        Applies per-channel mV→EU sensitivity conversion then an optional
        Butterworth highpass filter before forwarding to data_callback().
        """
        data_arr = np.asarray(samp['data'])
        unit_arr = samp['unit']
        channels = samp.get('channels', [0])

        # Ensure 2-D (blocksize, N_channels)
        if data_arr.ndim == 1:
            data_arr = data_arr[:, np.newaxis]

        overflow_mask: int = samp.get('overflow_mask', 0)
        samples: dict[int, vibechecker.VibeSample] = {}

        for i, ch in enumerate(channels):
            col  = min(i, data_arr.shape[1] - 1)
            data = data_arr[:, col].copy()
            unit = (unit_arr[ch] if isinstance(unit_arr, list) and ch < len(unit_arr)
                    else unit_arr[i] if isinstance(unit_arr, list) and i < len(unit_arr)
                    else unit_arr)

            # mV → EU via assigned ScopeSensor
            if unit == 'mV':
                scope_sensor = self.scope_sensors.get(ch)
                if scope_sensor is not None:
                    data = np.asarray(data, dtype=np.float64) / scope_sensor.sensitivity
                    unit = scope_sensor.engineering_units

            # Butterworth filters (SOS for numerical stability)
            data = np.asarray(data, dtype=np.float64)
            samplerate = samp.get('samplerate', self.config.samplerate)
            nyq = float(samplerate) / 2.0
            order = self.config._BUTTER_ORDER

            if self.config.highpass_enabled and self.config.highpass_fc < nyq:
                sos = scipy.signal.butter(order, self.config.highpass_fc,
                                          btype='highpass',
                                          fs=samplerate,
                                          output='sos')
                data = scipy.signal.sosfilt(sos, data)

            if self.config.lowpass_enabled and self.config.lowpass_fc < nyq:
                sos = scipy.signal.butter(order, self.config.lowpass_fc,
                                          btype='lowpass',
                                          fs=samplerate,
                                          output='sos')
                data = scipy.signal.sosfilt(sos, data)

            samples[ch] = vibechecker.VibeSample(
                samp['status'],
                samp['timestamp'],
                samplerate,
                unit,
                np.ascontiguousarray(data),
                samp['rel_time'],
            )

        samples['overflow'] = overflow_mask   # int bitmask, bit n → Ch n clipped
        self.data_callback(samples)

    def data_callback(self, samples: dict):
        """Store raw frame and deliver dict[int, VibeSample] to consumers."""
        t0 = time.monotonic()

        if samples:
            self.data['frame_cache'].append(samples)
            self.data['frame_count'] += 1
            self._cache_cursor = 0

        for fn in self.callbacks.values():
            fn(samples)

        # Warn when GUI processing time exceeds the hardware frame period —
        # frames are piling up faster than they're being rendered.
        # TODO: profile the full data-pipeline (receive_data → FFT → DPG plot
        #       update) to identify the dominant cost; consider decimating GUI
        #       updates (render every Nth frame) or offloading FFT to a worker
        #       thread to prevent the stream from starving.
        elapsed = time.monotonic() - t0
        if self._last_frame_t is not None:
            period = t0 - self._last_frame_t
            if elapsed > period:
                now = time.monotonic()
                if now - self._lag_warn_t >= 1.0:   # rate-limit to once per second
                    queued = max(1, round(elapsed / period))
                    log.warning(
                        f'Processing lag: {elapsed*1000:.0f} ms per frame, '
                        f'hardware period ~{period*1000:.0f} ms '
                        f'(~{queued} frame(s) behind)'
                    )
                    self._lag_warn_t = now
        self._last_frame_t = t0

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_data(self, target: Path):
        """Save frame cache and trend history to an HDF5 file.

        Layout::

            /frames/{i}/meta/{timestamp, rel_time, samplerate, status}
            /frames/{i}/channels/{ch}/data   (N,) float64
            /frames/{i}/channels/{ch}/unit   str
            /trend/{ch}/rel_times            (M,)
            /trend/{ch}/overall              (M,)
        """
        if target.exists():
            log.warning('Save target exists. Delete existing file before saving.')
            return

        frames = list(self.data['frame_cache'])
        with h5py.File(target, 'w') as f:
            frames_grp = f.create_group('frames')
            for i, frame_samples in enumerate(frames):
                fg = frames_grp.create_group(str(i))
                ch_only = {k: v for k, v in frame_samples.items() if isinstance(k, int)}
                first = next(iter(ch_only.values()))
                meta = fg.create_group('meta')
                meta.create_dataset('timestamp',  data=first.timestamp)
                meta.create_dataset('rel_time',   data=first.rel_time)
                meta.create_dataset('samplerate', data=first.samplerate)
                meta.create_dataset('status',     data=first.status)
                ch_grp = fg.create_group('channels')
                for ch, sample in ch_only.items():
                    cg = ch_grp.create_group(str(ch))
                    cg.create_dataset('data',     data=sample.data)
                    cg.create_dataset('unit',     data=sample.unit)
                    cg.create_dataset('modality', data=sample.modality)
                    cg.create_dataset('coupling', data=self.config.coupling_for(ch))

            trend_grp = f.create_group('trend')
            for ch, td in self.data['trend'].items():
                if td['rel_times']:
                    tg = trend_grp.create_group(str(ch))
                    tg.create_dataset('rel_times', data=np.array(td['rel_times']))
                    tg.create_dataset('overall',   data=np.array(td['overall']))

        log.info(f'Saved {len(frames)} frames to {target}')

    def load_data(self, target: Path):
        """Load frame cache and trend from an HDF5 file, then reprocess for display."""
        if not target.is_file():
            log.error(f'load_data: file does not exist: {target}')
            return

        def decode(x): return x.decode() if isinstance(x, bytes) else x

        self.data['frame_cache'].clear()
        self.data['trend'] = {}

        with h5py.File(target, 'r') as f:
            if 'frames' in f:
                frames_grp = f['frames']
                for idx in sorted(frames_grp.keys(), key=int):
                    fg = frames_grp[idx]
                    meta = fg['meta']
                    ts_str    = decode(meta['timestamp'][()])
                    rel_time  = float(meta['rel_time'][()])
                    samplerate = int(meta['samplerate'][()])
                    status    = decode(meta['status'][()])
                    try:
                        timestamp = datetime.fromisoformat(ts_str)
                    except (ValueError, TypeError):
                        timestamp = datetime.now()

                    frame_samples: dict[int, vibechecker.VibeSample] = {}
                    for ch_str, cg in fg['channels'].items():
                        ch = int(ch_str)
                        data     = np.ascontiguousarray(cg['data'][()],
                                                        dtype=np.float64)
                        unit     = decode(cg['unit'][()])
                        modality = decode(cg['modality'][()]) if 'modality' in cg \
                                   else 'acceleration'
                        frame_samples[ch] = vibechecker.VibeSample(
                            status=status,
                            _timestamp=timestamp,
                            samplerate=samplerate,
                            unit=unit,
                            data=data,
                            rel_time=rel_time,
                            modality=modality,
                        )
                    self.data['frame_cache'].append(frame_samples)

            if 'trend' in f:
                for ch_str, tg in f['trend'].items():
                    ch = int(ch_str)
                    self.data['trend'][ch] = {
                        'rel_times': list(np.array(tg['rel_times'][()])),
                        'overall':   list(np.array(tg['overall'][()])),
                    }

        n = len(self.data['frame_cache'])
        log.info(f'Loaded {n} frames from {target}')
        if n:
            self.reprocess_last_block()
