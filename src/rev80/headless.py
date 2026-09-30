"""Headless front end: runs Monitor Mode with no GUI.

Finds a PicoScope (or uses the simulated sensor with --device sim), loads the
saved configuration and records until SIGINT or SIGTERM. Each session goes to
~/Documents/Rev80/data/monitor/{session_id}/session.h5 (v6, the same format
as the GUI), unless --output or monitor.output_dir sets another parent
directory. Entry points: `rev80-headless`, `rev80 headless`,
`python -m rev80.headless`.
"""

from __future__ import annotations

import argparse
import logging
import sys

# All heavy imports (rev80, numpy, scipy, …) are deferred into run() and
# the info-command helpers so that --help and the info flags return instantly.

log = logging.getLogger(__name__)


# ── Info commands ──────────────────────────────────────────────────────────────

def _list_devices() -> int:
    import rev80
    sensors = rev80.VibeSensor.find()
    if rev80.PICOSCOPE_DRIVER_MISSING:
        print("PicoScope driver not installed — cannot enumerate hardware devices.")
        print("Install it with:  sudo ./drivers/install-picoscope4000a-driver.sh")
        return 1
    if not sensors:
        print("No PicoScope devices found.")
        return 0
    print(f"Found {len(sensors)} PicoScope(s):\n")
    for i, s in enumerate(sensors):
        ch = f"{s.num_channels} ch" if s.num_channels > 1 else "1 ch"
        print(f"  [{i}]  {s.model_name:<24}  s/n {s.serial_number:<16}  {ch}")
    print()
    return 0


def _list_sensors() -> int:
    from rev80.config import config_dir
    from rev80.scope_sensor_registry import ScopeSensorRegistry
    reg = ScopeSensorRegistry(config_dir() / "scope_sensors.yaml")
    sensors = reg.all()
    if not sensors:
        print("Sensor library is empty.")
        print(f"  Edit: {config_dir() / 'scope_sensors.yaml'}")
        return 0
    print(f"Sensor library — {len(sensors)} sensor(s):\n")
    hdr = f"  {'Name':<28}  {'Sensitivity':>14}  Engineering Units"
    print(hdr)
    print("  " + "─" * (len(hdr) - 2))
    for s in sensors:
        sens = f"{s.sensitivity} mV/{s.engineering_units}"
        print(f"  {s.name:<28}  {sens:>14}  {s.engineering_units}")
    print()
    return 0


def _edit_config() -> int:
    import os
    import subprocess
    from rev80.config import acquisition_config_path, ensure_acquisition_config
    ensure_acquisition_config()
    path   = acquisition_config_path()
    editor = os.environ.get("EDITOR", os.environ.get("VISUAL", "nano"))
    print(f"Opening {path} with {editor} …")
    result = subprocess.run([editor, str(path)])
    return result.returncode


# ── Helpers used only during a live session ────────────────────────────────────

def _build_session(collector, args, session_id, anom_cfg=None, mon_cfg=None):
    """Assemble this run's MonitorSession from the CLI args and config.

    The construction itself is `monitor.session.session_from`, shared with the
    GUI -- this only decides which of the args and config values feed it.
    """
    from rev80.monitor.session import session_from

    anom_cfg = anom_cfg or {}
    mon_cfg = mon_cfg or {}
    return session_from(
        collector         = collector,
        session_id        = session_id,
        interval_s        = float(args.interval),
        pre_buffer_s      = float(args.pre_buffer),
        burst_duration_s  = float(args.burst_duration),
        # From acquisition.yaml, not a literal: this limit stops an unattended
        # burst from growing without limit, and the summary prints it.
        max_burst_s       = float(mon_cfg.get("max_burst_s", 600.0)),
        output_dir        = args.output,
        compression       = "none" if args.no_compress else "gzip",
        cooldown_enabled  = bool(anom_cfg.get("cooldown_enabled", False)),
        cooldown_s        = float(anom_cfg.get("cooldown_s", 0.0)),
    )


def _build_anomaly_hook(anom_cfg: dict, config, pre_buffer_s: float = 0.0):
    """Build the composite anomaly hook from monitor.anomaly config.

    The `enabled` switch gates the EWMA-based hooks (RMS / Spectral); the
    fixed-level threshold trigger has its own independent enable switches and
    fires regardless of `enabled`.
    """
    from rev80.monitor.anomaly import (
        CompositeAnomalyHook, FixedThresholdHook, NullAnomalyHook,
        RmsThresholdHook, SpectralThresholdHook, ewma_alpha_from_time,
    )
    from rev80.util import DEFAULT_RMS_ALPHA, DEFAULT_SPEC_ALPHA, canonical_hook_type

    hooks: list = []
    warmup = int(anom_cfg.get("warmup", 10))

    if anom_cfg.get("enabled", False):
        hook_type = canonical_hook_type(anom_cfg.get("hook_type", "rms"))
        # Keep this above the hook_type branches: the RMS and the spectral
        # branch both read `period`.
        period = config.acquisition_period

        if hook_type in ("rms", "both"):
            rms_s  = float(anom_cfg.get("rms_s", 3.0))
            consecutive_n = max(1, round(rms_s / period) + 1) if period > 0 else 1
            if rms_s > 0.25 * pre_buffer_s:
                log.warning(
                    "Monitor anomaly: RMS sustained time %.3gs exceeds 25%% of the "
                    "pre-trigger buffer (%.3gs) — the t=0 frame will eat into the "
                    "pre-anomaly context captured in each burst", rms_s, pre_buffer_s,
                )
            if "rms_ewma_time" in anom_cfg and period > 0:
                rms_alpha = ewma_alpha_from_time(float(anom_cfg["rms_ewma_time"]), period)
            else:
                rms_alpha = float(anom_cfg.get("rms_alpha", DEFAULT_RMS_ALPHA))
            hooks.append(RmsThresholdHook(
                rms_threshold_pct    = float(anom_cfg.get("rms_pct", 50.0)),
                consecutive_n        = consecutive_n,
                baseline_alpha       = rms_alpha,
                min_baseline_samples = warmup,
            ))
        if hook_type in ("spectral", "both"):
            if "spec_ewma_time" in anom_cfg and period > 0:
                spec_alpha = ewma_alpha_from_time(float(anom_cfg["spec_ewma_time"]), period)
            else:
                spec_alpha = float(anom_cfg.get("spec_alpha", DEFAULT_SPEC_ALPHA))
            hooks.append(SpectralThresholdHook(
                spectral_threshold_pct = float(anom_cfg.get("spec_pct",   50.0)),
                consecutive_n          = int(anom_cfg.get("spec_n",       10)),
                baseline_alpha         = spec_alpha,
                min_baseline_samples   = warmup,
                fmin                   = anom_cfg.get("spec_fmin",  None),
                fmax                   = anom_cfg.get("spec_fmax",  None),
            ))

    upper_on = bool(anom_cfg.get("fixed_upper_enabled", False))
    lower_on = bool(anom_cfg.get("fixed_lower_enabled", False))
    if upper_on or lower_on:
        hooks.append(FixedThresholdHook(
            upper_limit = float(anom_cfg.get("fixed_upper_value", 1.0))  if upper_on else None,
            upper_unit  = str(anom_cfg.get("fixed_upper_unit",    "in/s")),
            lower_limit = float(anom_cfg.get("fixed_lower_value", 0.05)) if lower_on else None,
            lower_unit  = str(anom_cfg.get("fixed_lower_unit",    "in/s")),
        ))

    if not hooks:
        return NullAnomalyHook()
    if len(hooks) == 1:
        return hooks[0]
    log.info(f"Anomaly detection enabled: {len(hooks)} hook(s)")
    return CompositeAnomalyHook(hooks)



def _persist_channel_override(device_cfg: dict, channels) -> bool:
    """Write a --channels override into the device config. True if it changed.

    The override stays: it edits `devices/*.yaml`, so the next run without the
    flag keeps the same selection. Tachometer channels are skipped, because
    the loaders always enable a tachometer channel and would ignore the flag.
    A `--channels` list without the tachometer channel removes it for this run
    only (`_apply_overrides`).
    """
    from rev80.config import channel_role_state

    wanted = set(int(c) for c in channels)
    changed = False
    for ch, info in device_cfg.get("channels", {}).items():
        role, _, _ = channel_role_state(info)
        if role == 'tachometer':
            continue
        want = int(ch) in wanted
        if info.get("enabled") != want:
            info["enabled"] = want
            changed = True
    return changed


def _apply_channel_config(config, device_cfg: dict) -> dict:
    """Load per-channel fields from a device config into `config`.

    Sets `enabled_channels` from each channel's role and `enabled` flag, and
    returns {ch: TachSettings} for the tachometer channels. It returns the
    calibration and does not apply it, because the collector does not exist
    yet. A tachometer channel gets no target unit and no amplitude mode. The
    role decision is the shared one in `rev80.config`; do not copy it here.
    """
    from rev80.config import channel_role_state

    enabled_channels = []
    tach_settings = {}
    for ch_key, info in device_cfg.get("channels", {}).items():
        ch = int(ch_key)
        role, settings, enabled = channel_role_state(info)
        if role == 'tachometer':
            config.channel_roles[ch] = role
            tach_settings[ch] = settings
            if not info.get("tach"):
                # The defaults work, but the operator expects a saved
                # calibration. Do not use the defaults without a warning.
                log.warning(
                    "Channel %d is a tachometer with no saved calibration; "
                    "using defaults (adaptive threshold, rising, 1 pulse/rev). "
                    "Set it up in the GUI's Tachometer tab.", ch)
        else:
            config.channel_roles.pop(ch, None)
        if enabled:
            enabled_channels.append(ch)
        if info.get("voltage_range") is not None:
            config.channel_voltage_ranges[ch] = info["voltage_range"]
        if info.get("coupling"):
            config.channel_couplings[ch] = info["coupling"]
        if info.get("channel_name"):
            config.channel_names[ch] = info["channel_name"]
        if role != 'tachometer':
            # A tachometer has no sensor, engineering unit or amplitude mode.
            if info.get("target_unit"):
                config.channel_target_units[ch] = info["target_unit"]
            if info.get("amplitude_mode"):
                config.channel_amplitude_modes[ch] = info["amplitude_mode"]
    if enabled_channels:
        config.enabled_channels = sorted(enabled_channels)
    return tach_settings


def _apply_overrides(config, args) -> None:
    if args.maxfreq:
        config.maxfreq = float(args.maxfreq)
    if args.binsize:
        config.binsize = float(args.binsize)
    if args.channels:
        before_tach = set(config.tach_channels)
        config.enabled_channels = sorted(set(int(c) for c in args.channels))
        # Obey the override, but warn when it removes a tachometer channel:
        # rpm is then NaN on every capture, and an enabled speed gate fails
        # closed, so no frame is trended or alarmed on.
        dropped = sorted(before_tach - set(config.enabled_channels))
        if dropped:
            log.warning(
                "--channels excludes tachometer channel(s) %s. Running without "
                "a speed reference: rpm is not recorded, and if the speed gate "
                "is enabled it fails closed and nothing will be trended or "
                "alarmed on.", ", ".join(str(c) for c in dropped))


# ── Session summary ────────────────────────────────────────────────────────────

def _tach_summary_lines(config, tach_settings: dict) -> list:
    """The tachometer block of the session summary, or [] when none is fitted.

    Shows the calibration and both shaft-speed limits: the slowest shaft for
    the block length, and (above 1 pulse/rev) the full-accuracy limit
    computed from the raw rate. Headless has no Tachometer tab.
    """
    from rev80 import tach as _tach

    channels = [ch for ch in config.tach_channels if ch in tach_settings]
    if not channels:
        return []

    t_block = 1.0 / max(config.binsize, 1e-9)
    lines = ["  Tachometer"]
    for ch in channels:
        s = tach_settings[ch]
        ppr = max(1, int(s.pulses_per_rev))
        lines.append(
            f"    ch{ch} {config.name_for(ch)}   {s.threshold_mode} threshold, "
            f"{s.polarity}, {ppr} pulse/rev"
            + (f", reflector {s.reflector_size_mm:g} mm" if s.reflector_size_mm else "")
        )
        floor = _tach.slowest_rpm_for(t_block, ppr)
        lines.append(
            f"      Slowest shaft  {floor:,.0f} RPM  "
            f"({_tach.MIN_REVS:g} rev in a {t_block:.2f} s block)"
        )
        if ppr > 1:
            # Below MIN_SAMPLES_PER_PULSE the edge interpolation does not
            # find the sub-sample position, and the error rises to ~0.8%.
            ceiling = (config.raw_samplerate * 60.0
                       / (_tach.MIN_SAMPLES_PER_PULSE * ppr))
            lines.append(
                f"      Full accuracy  to {ceiling:,.0f} RPM  "
                f"({_tach.MIN_SAMPLES_PER_PULSE} samples/pulse at {ppr}/rev); "
                f"above it, ~0.8%"
            )
    return lines



def _print_session_summary(sensor, config, args, mon_cfg, anom_cfg, device_path,
                           tach_settings: dict | None = None) -> None:
    from rev80.config import acquisition_config_path

    interval_s    = args.interval
    burst_dur_s   = args.burst_duration
    pre_burst_s   = args.pre_buffer

    h, rem = divmod(int(interval_s), 3600)
    m, s   = divmod(rem, 60)
    interval_str = (
        f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s" if m else f"{s}s"
    )

    ch_labels = "  ".join(
        f"{config.name_for(ch)} (ch{ch})"
        + (" [tach]" if config.role_for(ch) == 'tachometer' else "")
        for ch in config.enabled_channels
    )
    anom_enabled = anom_cfg.get("enabled", False)
    hook_type    = anom_cfg.get("hook_type", "rms").upper()

    print(f"\n{'─' * 54}")
    print("  Rev80 headless")
    print(f"{'─' * 54}")
    print(f"  Device      {sensor.model_name}  s/n {sensor.serial_number}")
    print(f"  Channels    {ch_labels or '(none)'}")
    print(f"  Sample rate {config.samplerate} Hz   block {config.blocksize}   "
          f"resolution {config.binsize:.3g} Hz")
    print()
    for line in _tach_summary_lines(config, tach_settings or {}):
        print(line)
    if tach_settings:
        print()
    print("  Monitor")
    print(f"    Interval  {interval_str}  ({interval_s:.0f}s)")
    print(f"    Pre-burst {pre_burst_s:.0f}s   Burst {burst_dur_s:.0f}s  "
          f"max {mon_cfg.get('max_burst_s', 600):.0f}s")
    if anom_enabled:
        import math as _math
        from rev80.monitor.anomaly import ewma_alpha_from_time as _ewma
        warmup  = anom_cfg.get("warmup", 10)
        dt      = config.acquisition_period
        if hook_type in ("RMS", "BOTH"):
            if "rms_ewma_time" in anom_cfg and dt > 0:
                rms_tau   = float(anom_cfg["rms_ewma_time"])
                rms_alpha = _ewma(rms_tau, dt)
                alpha_str = f"ewma_time={rms_tau:.3g}s (α={rms_alpha:.4f})"
            else:
                rms_alpha = float(anom_cfg.get("rms_alpha", 0.97))
                rms_tau   = -dt / _math.log(rms_alpha) if rms_alpha < 1 else float("inf")
                alpha_str = f"α={rms_alpha:.4f} (τ={rms_tau:.3g}s)"
            print(f"    Anomaly   RMS  threshold={anom_cfg.get('rms_pct', 50):.4g}%  "
                  f"{alpha_str}  sustained={anom_cfg.get('rms_s', 3.0):.3g}s  warmup={warmup}")
        if hook_type in ("SPECTRAL", "BOTH"):
            if "spec_ewma_time" in anom_cfg and dt > 0:
                spec_tau   = float(anom_cfg["spec_ewma_time"])
                spec_alpha = _ewma(spec_tau, dt)
                alpha_str  = f"ewma_time={spec_tau:.3g}s (α={spec_alpha:.4f})"
            else:
                spec_alpha = float(anom_cfg.get("spec_alpha", 0.995))
                spec_tau   = -dt / _math.log(spec_alpha) if spec_alpha < 1 else float("inf")
                alpha_str  = f"α={spec_alpha:.4f} (τ={spec_tau:.3g}s)"
            fmin = anom_cfg.get("spec_fmin")
            fmax = anom_cfg.get("spec_fmax")
            band = (f"{fmin:.0f}–{fmax:.0f} Hz"
                    if fmin is not None and fmax is not None else "full band")
            print(f"    Anomaly   Spectral  threshold={anom_cfg.get('spec_pct', 50):.4g}%  "
                  f"{alpha_str}  n={anom_cfg.get('spec_n', 10)}  {band}  warmup={warmup}")
    else:
        print("    Anomaly   disabled")
    print()
    print("  Config files")
    print(f"    Acquisition  {acquisition_config_path()}")
    print(f"    Device       {device_path}")
    print(f"{'─' * 54}\n")


# ── Main event loop ────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> int:
    import signal
    import threading
    from datetime import datetime, timezone

    import rev80
    import rev80.config as _cfg
    from rev80.collector import DataCollector
    from rev80.monitor.controller import MonitorController
    from rev80.monitor.session import required_cache_frames
    from rev80.sample import AcquisitionSettings

    shutdown = threading.Event()

    def _handle_signal(signum, frame):
        rev80.get_logger('rev80-cli').info(
            f"Signal {signum} received — shutting down after current interval…"
        )
        shutdown.set()

    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    log = rev80.get_logger('rev80-cli')

    # ── Discover device ───────────────────────────────────────────────────────
    if args.device and args.device.lower() == "sim":
        sensor = rev80.VibeSensor.simulated()
        log.info("Using simulated sensor")
    elif args.device:
        sensors = rev80.VibeSensor.find()
        sensor  = next((s for s in sensors if args.device in s.serial_number), None)
        if sensor is None:
            log.error(f"Device '{args.device}' not found. "
                      f"Available: {[s.serial_number for s in sensors]}")
            return 1
    else:
        sensors = rev80.VibeSensor.find()
        if rev80.PICOSCOPE_DRIVER_MISSING:
            print("ERROR: PicoScope driver not installed.", file=sys.stderr)
            print("       Install it with:", file=sys.stderr)
            print("         sudo ./drivers/install-picoscope4000a-driver.sh", file=sys.stderr)
            print("       Use --device sim to run without hardware.", file=sys.stderr)
            return 1
        if not sensors:
            print("ERROR: No PicoScope device found.", file=sys.stderr)
            print("       Check the USB connection and try again.", file=sys.stderr)
            print("       Use --device sim to run with a simulated sensor.", file=sys.stderr)
            return 1
        sensor = sensors[0]
        log.info(f"Found {sensor.model_name} s/n {sensor.serial_number}")

    # ── Load / create device config ───────────────────────────────────────────
    acq_cfg  = _cfg.load_acquisition_config()
    mon_cfg  = acq_cfg.get("monitor", {})

    device_path = _cfg.device_config_path(sensor.model_name, sensor.serial_number)
    if not device_path.exists():
        log.info("New device — generating config: %s", device_path)
        channels = _cfg.new_device_channels(sensor.num_channels)
        device_cfg = {'channels': channels, 'siggen': None}
        _cfg.save_device_config(sensor.model_name, sensor.serial_number, device_cfg)
        print(f"  Created device config: {device_path}")
    else:
        device_cfg = _cfg.load_device_config(sensor.model_name, sensor.serial_number)

    # Apply --channels override: update enabled flags and persist
    if args.channels and _persist_channel_override(device_cfg, args.channels):
        _cfg.save_device_config(sensor.model_name, sensor.serial_number, device_cfg)

    if args.interval is None:
        args.interval      = float(mon_cfg.get("interval_s",      600))
    if args.pre_buffer is None:
        args.pre_buffer    = float(mon_cfg.get("pre_burst_s",     30))
    if args.burst_duration is None:
        args.burst_duration = float(mon_cfg.get("burst_duration_s", 120))
    if args.output is None and mon_cfg.get("output_dir"):
        args.output = mon_cfg["output_dir"]
    if not args.no_compress and mon_cfg.get("compression") == "none":
        args.no_compress = True

    config = AcquisitionSettings.from_dict(acq_cfg.get("acquisition", {}))

    tach_settings = _apply_channel_config(config, device_cfg)
    _apply_overrides(config, args)

    collector = DataCollector()
    collector.config = config
    for ch, settings in tach_settings.items():
        if ch in config.enabled_channels:
            collector.set_tach_settings(ch, settings)
    collector.init_trend_channels()

    # ── Summary + confirmation gate ───────────────────────────────────────────
    anom_cfg = mon_cfg.get("anomaly", {})
    _print_session_summary(sensor, config, args, mon_cfg, anom_cfg, device_path,
                           tach_settings)
    if not getattr(args, 'start_now', False):
        try:
            input("Press Enter to start monitoring, or Ctrl+C to abort… ")
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            return 0
    print()

    # ── Connect stream ────────────────────────────────────────────────────────
    collector.connect_sensor(sensor)
    collector.start_stream()
    log.info(f"Stream started — {config.samplerate} Hz, {config.blocksize} samples, "
             f"channels {config.enabled_channels}")

    # ── Build session ─────────────────────────────────────────────────────────
    session_id = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    session    = _build_session(collector, args, session_id, anom_cfg, mon_cfg)
    monitor    = MonitorController()

    anomaly_hook = _build_anomaly_hook(anom_cfg, config, pre_buffer_s=float(args.pre_buffer))

    collector.resize_frame_cache(required_cache_frames(
        config.cache_frames, session.pre_buffer_frames))
    monitor.start(session, anomaly_hook=anomaly_hook)

    print(f"Session {session_id} — recording to {session.session_dir}")
    print("  t + Enter: manual burst   Ctrl+C: stop\n")

    # ── Keyboard input thread ─────────────────────────────────────────────────
    def _kbd_loop():
        while not shutdown.is_set():
            try:
                line = sys.stdin.readline()
            except Exception:
                break
            if not line:
                break
            if line.strip().lower().startswith('t'):
                if monitor.is_recording:
                    monitor.trigger_burst()
                    print("  [manual burst triggered]", flush=True)
                else:
                    print("  [not recording]", flush=True)

    threading.Thread(target=_kbd_loop, daemon=True, name="headless-kbd").start()

    # ── Event loop ────────────────────────────────────────────────────────────
    prev_captures  = 0
    prev_bursts    = 0
    _status_lines  = 0  # tracks how many lines to erase on next redraw

    def _print_status(results: list) -> None:
        nonlocal _status_lines
        snap    = monitor.status_snapshot()
        elapsed = snap["elapsed_s"]
        h, rem  = divmod(int(elapsed), 3600)
        m, s    = divmod(rem, 60)
        burst_tag = f"  \033[33m[BURST {snap['burst_remaining_s']:.0f}s]\033[0m" \
                    if snap["is_in_burst"] else ""

        # Shaft speed goes on the header line: a tachometer channel has no
        # ChannelResult. Show `--`, never `0`, when there is no reading:
        # "no signal" is not "stopped".
        rpm = next((r.rpm for r in results if getattr(r, 'rpm', None) is not None),
                   None)
        if config.tach_channels:
            gated = any(not getattr(r, 'speed_ok', True) for r in results)
            rpm_tag = (f"  {rpm:,.0f} RPM" if rpm is not None else "  -- RPM")
            if gated:
                rpm_tag += " \033[33m[off-speed]\033[0m"
        else:
            rpm_tag = ""

        lines = [f"\033[2K\r\033[90m[{h:02d}:{m:02d}:{s:02d}]  "
                 f"cap #{snap['capture_count']}  "
                 f"next {snap['next_capture_s']:.0f}s  "
                 f"{snap['total_bytes'] / 1e6:.1f} MB{rpm_tag}{burst_tag}\033[0m"]

        baseline = snap.get('baseline', {})
        for r in results:
            bl = baseline.get(r.channel)
            bl_str = f"  \033[90mbaseline={bl:.4g} {r.unit}\033[0m" if bl is not None else ""
            if r.peaks is not None and len(r.peaks):
                top = r.peaks[:3]
                peaks_str = "  ".join(
                    f"{r.freq[i]:.0f}Hz={r.spectrum[i]:.3g}" for i in top
                )
            else:
                peaks_str = ""
            lines.append(
                f"\033[2K\r  Ch{r.channel}  overall={r.overall:.4g} {r.unit}"
                + (f"  peaks: {peaks_str}" if peaks_str else "")
                + bl_str
            )

        # Erase previous block and redraw
        if _status_lines:
            sys.stdout.write(f"\033[{_status_lines}A")
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()
        _status_lines = len(lines)

    while not shutdown.is_set():
        if not collector.new_frame_event.wait(timeout=1.0):
            continue
        collector.new_frame_event.clear()

        results = collector.process_samples()
        if results:
            monitor.on_results(results, collector.data["frame_cache"])
            _print_status(results)

        snap = monitor.status_snapshot()

        if snap["capture_count"] != prev_captures:
            prev_captures = snap["capture_count"]
            elapsed = snap["elapsed_s"]
            h, rem  = divmod(int(elapsed), 3600)
            m, s    = divmod(rem, 60)
            log.info(
                f"capture #{prev_captures}  [{h:02d}:{m:02d}:{s:02d}]  "
                f"size={snap['total_bytes'] / 1e6:.1f} MB  "
                f"next={snap['next_capture_s']:.0f}s"
            )

        if snap["burst_count"] != prev_bursts:
            prev_bursts = snap["burst_count"]
            log.info(f"burst #{prev_bursts} complete  size={snap['total_bytes'] / 1e6:.1f} MB")

        if snap["error"]:
            log.error(f"Writer error: {snap['error']}")
            shutdown.set()

    # ── Clean shutdown ────────────────────────────────────────────────────────
    print("\nStopping…")
    monitor.stop()
    collector.stop_stream()

    snap = monitor.status_snapshot()
    print("\nSession complete.")
    print(f"  Captures : {snap['capture_count']}")
    print(f"  Bursts   : {snap['burst_count']}")
    print(f"  File     : {session.session_h5}")
    print(f"  Size     : {snap['total_bytes'] / 1e6:.1f} MB")
    return 0


# ── Argument parser ────────────────────────────────────────────────────────────

def build_option_parser() -> argparse.ArgumentParser:
    """Argument definitions shared by `rev80-headless` and the `rev80 headless` subcommand."""
    parser = argparse.ArgumentParser(add_help=False)

    # Info commands — handled before any heavy import
    info = parser.add_argument_group("info commands")
    info.add_argument("--init-config",  action="store_true",
                      help="Write the default config files that do not exist "
                           "(~/.config/rev80/ on Linux) and exit")
    info.add_argument("--list-devices", action="store_true",
                      help="List connected PicoScope devices and exit")
    info.add_argument("--list-sensors", action="store_true",
                      help="List IEPE sensors in the library and exit")
    info.add_argument("--edit-config",  action="store_true",
                      help="Open acquisition.yaml in $EDITOR and exit")

    # Session options
    sess = parser.add_argument_group("session options")
    sess.add_argument("--interval",       type=float, default=None, metavar="SECS",
                      help="Seconds between captures (default: monitor.interval_s "
                           "in acquisition.yaml; built-in 600)")
    sess.add_argument("--pre-buffer",     type=float, default=None, metavar="SECS",
                      help="Pre-trigger time kept in each burst (default: "
                           "monitor.pre_burst_s in acquisition.yaml; built-in 30)")
    sess.add_argument("--burst-duration", type=float, default=None, metavar="SECS",
                      help="Burst length after the trigger (default: "
                           "monitor.burst_duration_s in acquisition.yaml; built-in 120)")
    sess.add_argument("--output",         type=str,   default=None, metavar="DIR",
                      help="Parent directory for session folders (default: "
                           "monitor.output_dir, else ~/Documents/Rev80/data/monitor)")
    sess.add_argument("--no-compress",    action="store_true",
                      help="Disable gzip compression. Known defect: the first "
                           "write fails and the session stops")
    sess.add_argument("--start-now",      action="store_true",
                      help="Skip the pre-start confirmation prompt")

    # Device / acquisition options
    acq = parser.add_argument_group("acquisition options")
    acq.add_argument("--device",   type=str,   default=None, metavar="SERIAL",
                     help="PicoScope serial number (or part of it), or 'sim' "
                          "for the simulated sensor (default: first device found)")
    acq.add_argument("--channels", type=int,   nargs="+",   metavar="N",
                     help="Channel indices to enable, 0 = A (e.g. --channels 0 1). "
                          "Saved to the device config for later runs")
    acq.add_argument("--maxfreq",  type=float, default=None, metavar="HZ",
                     help="F_max override in Hz (maximum 10000)")
    acq.add_argument("--binsize",  type=float, default=None, metavar="HZ",
                     help="Frequency resolution override in Hz")
    acq.add_argument("--debug",    action="store_true",
                     help="Debug-level logging on the console (stdout)")

    return parser


def run_headless(args: argparse.Namespace) -> int:
    """Dispatch a parsed headless namespace: info command, or a full monitor session."""
    # Info commands: minimal imports, return immediately
    if args.init_config:
        from rev80.__main__ import _init_config
        return _init_config()
    if args.list_devices:
        return _list_devices()
    if args.list_sensors:
        return _list_sensors()
    if args.edit_config:
        return _edit_config()

    # Full session: now pull in everything
    import rev80
    import rev80.config as _cfg_boot
    _cfg_boot.ensure_config_dir()
    rev80.setup_logging(debug=args.debug)
    # sys.excepthook, threading.excepthook and faulthandler: an exception in
    # any thread, and a hard crash, reach the log.
    rev80.install_excepthooks()
    rev80.get_logger().info("rev80 headless started")

    return run(args)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="rev80-headless",
        description="Rev80 interval datalogger — no GUI required",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Quick info commands (return immediately, no hardware required):\n"
            "  --list-devices    enumerate connected PicoScopes\n"
            "  --list-sensors    show IEPE sensor library\n"
            "  --edit-config     open acquisition.yaml in $EDITOR"
        ),
        parents=[build_option_parser()],
    )
    args = parser.parse_args()
    sys.exit(run_headless(args))


if __name__ == "__main__":
    main()
