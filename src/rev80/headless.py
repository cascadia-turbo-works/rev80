"""
rev80 headless mode — interval datalogger with no GUI.

Discovers a PicoScope (or uses the simulated sensor), loads the saved device
config, and runs Monitor Mode indefinitely.  All captured data is written to
~/Documents/Rev80/data/monitor/{session_id}/session.h5 (override with
--output) in the same v5 format as the GUI. Sessions can be browsed and
loaded in the GUI session browser afterwards.

Usage
-----
    python -m rev80.headless [options]
    rev80-headless [options]       # if installed via pip
    rev80 headless [options]       # equivalent, via the unified `rev80` CLI

Quick info commands (return immediately, no hardware required — also
available on the top-level `rev80` command, without the GUI launching):
    rev80-headless --list-devices
    rev80-headless --list-sensors
    rev80-headless --edit-config
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

def _build_session(collector, args, session_id, anom_cfg=None):
    from datetime import datetime, timezone
    from pathlib import Path
    import rev80

    cfg     = collector.config
    block_s = cfg.blocksize / cfg.samplerate if cfg.samplerate else 1.0
    pre_n   = max(1, int(args.pre_buffer / block_s))

    session_dir = (
        Path(args.output) / session_id
        if args.output
        else rev80.data_dir() / "monitor" / session_id
    )

    ch_snapshot: dict = {}
    for ch in cfg.enabled_channels:
        sc = collector.scope_sensors.get(ch)
        ch_snapshot[str(ch)] = {
            "name":            cfg.name_for(ch),
            "unit":            "mV",
            "coupling":        cfg.coupling_for(ch),
            "voltage_range":   cfg.voltage_range_for(ch),
            "scope_sensor_id": sc.id if sc else "",
            "target_unit":     cfg.target_unit_for(ch),
            "amplitude_mode":  cfg.amplitude_mode_for(ch),
        }

    seen: set = set()
    sensor_snapshot: dict = {}
    for sc in collector.scope_sensors.values():
        if sc.id not in seen:
            seen.add(sc.id)
            sensor_snapshot[sc.id] = sc.to_dict()

    anom_cfg = anom_cfg or {}

    from rev80.monitor.session import MonitorSession
    return MonitorSession(
        session_id        = session_id,
        start_time        = datetime.now(timezone.utc),
        interval_s        = float(args.interval),
        pre_buffer_frames = pre_n,
        burst_duration_s  = float(args.burst_duration),
        max_burst_s       = 600.0,
        session_dir       = session_dir,
        compression       = "none" if args.no_compress else "gzip",
        compression_level = 4,
        cooldown_enabled  = bool(anom_cfg.get("cooldown_enabled", False)),
        cooldown_s        = float(anom_cfg.get("cooldown_s", 0.0)),
        acq_snapshot      = cfg.to_dict(),
        channel_snapshot  = ch_snapshot,
        sensor_snapshot   = sensor_snapshot,
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

    hooks: list = []
    warmup = int(anom_cfg.get("warmup", 10))

    if anom_cfg.get("enabled", False):
        hook_type = anom_cfg.get("hook_type", "rms").lower()

        if hook_type in ("rms", "both"):
            period = config.acquisition_period
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
                rms_alpha = float(anom_cfg.get("rms_alpha", 0.97))
            hooks.append(RmsThresholdHook(
                rms_threshold_pct    = float(anom_cfg.get("rms_pct", 10.0)),
                consecutive_n        = consecutive_n,
                baseline_alpha       = rms_alpha,
                min_baseline_samples = warmup,
            ))
        if hook_type in ("spectral", "both"):
            if "spec_ewma_time" in anom_cfg and period > 0:
                spec_alpha = ewma_alpha_from_time(float(anom_cfg["spec_ewma_time"]), period)
            else:
                spec_alpha = float(anom_cfg.get("spec_alpha", 0.995))
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


def _apply_overrides(config, args) -> None:
    if args.maxfreq:
        config.maxfreq = float(args.maxfreq)
    if args.binsize:
        config.binsize = float(args.binsize)
    if args.channels:
        config.enabled_channels = sorted(set(int(c) for c in args.channels))


# ── Session summary ────────────────────────────────────────────────────────────

def _print_session_summary(sensor, config, args, mon_cfg, anom_cfg, device_path) -> None:
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
        f"{config.name_for(ch)} (ch{ch})" for ch in config.enabled_channels
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
            print(f"    Anomaly   RMS  threshold={anom_cfg.get('rms_pct', 10):.4g}%  "
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
    if args.channels:
        enabled_set = set(int(c) for c in args.channels)
        changed = False
        for ch, info in device_cfg.get("channels", {}).items():
            want = ch in enabled_set
            if info.get("enabled") != want:
                info["enabled"] = want
                changed = True
        if changed:
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

    # Load per-channel fields from device config; derive enabled_channels from 'enabled' flag
    enabled_channels = []
    for ch_key, info in device_cfg.get("channels", {}).items():
        ch = int(ch_key)
        if info.get("enabled", False):
            enabled_channels.append(ch)
        if info.get("voltage_range") is not None:
            config.channel_voltage_ranges[ch] = info["voltage_range"]
        if info.get("coupling"):
            config.channel_couplings[ch] = info["coupling"]
        if info.get("channel_name"):
            config.channel_names[ch] = info["channel_name"]
        if info.get("target_unit"):
            config.channel_target_units[ch] = info["target_unit"]
        if info.get("amplitude_mode"):
            config.channel_amplitude_modes[ch] = info["amplitude_mode"]
    if enabled_channels:
        config.enabled_channels = sorted(enabled_channels)

    # CLI overrides (maxfreq, binsize; --channels already applied above)
    if args.maxfreq:
        config.maxfreq = float(args.maxfreq)
    if args.binsize:
        config.binsize = float(args.binsize)

    collector = DataCollector()
    collector.config = config
    collector.init_trend_channels()

    # ── Summary + confirmation gate ───────────────────────────────────────────
    anom_cfg = mon_cfg.get("anomaly", {})
    _print_session_summary(sensor, config, args, mon_cfg, anom_cfg, device_path)
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
    session    = _build_session(collector, args, session_id, anom_cfg)
    monitor    = MonitorController()

    anomaly_hook = _build_anomaly_hook(anom_cfg, config, pre_buffer_s=float(args.pre_buffer))

    collector.resize_frame_cache(max(config.cache_frames, session.pre_buffer_frames))
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

        lines = [f"\033[2K\r\033[90m[{h:02d}:{m:02d}:{s:02d}]  "
                 f"cap #{snap['capture_count']}  "
                 f"next {snap['next_capture_s']:.0f}s  "
                 f"{snap['total_bytes'] / 1e6:.1f} MB{burst_tag}\033[0m"]

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
                      help="Seed ~/.config/rev80/ with default config files and exit")
    info.add_argument("--list-devices", action="store_true",
                      help="List connected PicoScope devices and exit")
    info.add_argument("--list-sensors", action="store_true",
                      help="List IEPE sensors in the library and exit")
    info.add_argument("--edit-config",  action="store_true",
                      help="Open acquisition.yaml in $EDITOR and exit")

    # Session options
    sess = parser.add_argument_group("session options")
    sess.add_argument("--interval",       type=float, default=None, metavar="SECS",
                      help="Capture interval (default: from device config or 3600)")
    sess.add_argument("--pre-buffer",     type=float, default=None, metavar="SECS",
                      help="Pre-trigger buffer duration (default: from config or 60)")
    sess.add_argument("--burst-duration", type=float, default=None, metavar="SECS",
                      help="Burst capture duration (default: from config or 60)")
    sess.add_argument("--output",         type=str,   default=None, metavar="DIR",
                      help="Override output root directory")
    sess.add_argument("--no-compress",    action="store_true",
                      help="Disable gzip compression")
    sess.add_argument("--start-now",      action="store_true",
                      help="Skip the pre-start confirmation prompt")

    # Device / acquisition options
    acq = parser.add_argument_group("acquisition options")
    acq.add_argument("--device",   type=str,   default=None, metavar="SERIAL",
                     help="PicoScope serial number, or 'sim' for simulation")
    acq.add_argument("--channels", type=int,   nargs="+",   metavar="N",
                     help="Channel indices to enable (e.g. --channels 0 1)")
    acq.add_argument("--maxfreq",  type=float, default=None, metavar="HZ",
                     help="Max analysis frequency override (Hz)")
    acq.add_argument("--binsize",  type=float, default=None, metavar="HZ",
                     help="Frequency resolution override (Hz)")
    acq.add_argument("--debug",    action="store_true",
                     help="Verbose logging to stderr")

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
    sys.excepthook = rev80.exception_handler
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
            "  --edit-config     open default.yaml in $EDITOR"
        ),
        parents=[build_option_parser()],
    )
    args = parser.parse_args()
    sys.exit(run_headless(args))


if __name__ == "__main__":
    main()
