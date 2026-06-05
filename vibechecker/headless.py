"""
vibechecker headless mode — interval datalogger with no GUI.

Discovers a PicoScope (or uses the simulated sensor), loads the saved device
config, and runs Monitor Mode indefinitely.  All captured data is written to
DEVDATA/monitor/{session_id}/session.h5 in the same v5 format as the GUI.
Sessions can be browsed and loaded in the GUI session browser afterwards.

Usage
-----
    python -m vibechecker.headless [options]
    vibechecker-headless [options]       # if installed via pip

Quick info commands (return immediately, no hardware required):
    vibechecker-headless --list-devices
    vibechecker-headless --list-sensors
    vibechecker-headless --edit-config
"""

from __future__ import annotations

import argparse
import sys

# All heavy imports (vibechecker, numpy, scipy, …) are deferred into run() and
# the info-command helpers so that --help and the info flags return instantly.


# ── Info commands ──────────────────────────────────────────────────────────────

def _list_devices() -> int:
    import vibechecker
    sensors = vibechecker.VibeSensor.find()
    if vibechecker.PICOSCOPE_DRIVER_MISSING:
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
    from vibechecker.config import config_dir
    from vibechecker.scope_sensor_registry import ScopeSensorRegistry
    reg = ScopeSensorRegistry(config_dir() / "scope_sensors.yaml")
    sensors = reg.all()
    if not sensors:
        print("Sensor library is empty.")
        print(f"  Edit: {config_dir() / 'scope_sensors.yaml'}")
        return 0
    print(f"Sensor library — {len(sensors)} sensor(s):\n")
    hdr = f"  {'Name':<28}  {'Sensitivity':>14}  {'Units':<8}  Target"
    print(hdr)
    print("  " + "─" * (len(hdr) - 2))
    for s in sensors:
        target = f"→ {s.target_unit}" if s.target_unit else ""
        sens   = f"{s.sensitivity} mV/{s.engineering_units}"
        print(f"  {s.name:<28}  {sens:>14}  {s.engineering_units:<8}  {target}")
    print()
    return 0


def _edit_config() -> int:
    import os
    import subprocess
    from vibechecker.config import config_dir, default_config_path, ensure_default_config
    ensure_default_config()
    path   = default_config_path()
    editor = os.environ.get("EDITOR", os.environ.get("VISUAL", "nano"))
    print(f"Opening {path} with {editor} …")
    result = subprocess.run([editor, str(path)])
    return result.returncode


# ── Helpers used only during a live session ────────────────────────────────────

def _build_session(collector, args, session_id):
    from datetime import datetime, timezone
    from pathlib import Path
    import vibechecker

    cfg     = collector.config
    block_s = cfg.blocksize / cfg.samplerate if cfg.samplerate else 1.0
    pre_n   = max(1, int(args.pre_buffer / block_s))

    session_dir = (
        Path(args.output) / session_id
        if args.output
        else vibechecker.data_dir() / "monitor" / session_id
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

    from vibechecker.monitor.session import MonitorSession
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
        acq_snapshot      = cfg.to_dict(),
        channel_snapshot  = ch_snapshot,
        sensor_snapshot   = sensor_snapshot,
    )


def _apply_overrides(config, args) -> None:
    if args.maxfreq:
        config.maxfreq = float(args.maxfreq)
    if args.binsize:
        config.binsize = float(args.binsize)
    if args.channels:
        config.enabled_channels = sorted(set(int(c) for c in args.channels))


# ── Main event loop ────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> int:
    import signal
    import threading
    from datetime import datetime, timezone

    import vibechecker
    import vibechecker.config as _cfg
    from vibechecker.collector import DataCollector
    from vibechecker.monitor.controller import MonitorController
    from vibechecker.sample import AcquisitionSettings

    shutdown = threading.Event()

    def _handle_signal(signum, frame):
        vibechecker.get_logger('vibechecker-cli').info(
            f"Signal {signum} received — shutting down after current interval…"
        )
        shutdown.set()

    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    log = vibechecker.get_logger('vibechecker-cli')

    # ── Discover device ───────────────────────────────────────────────────────
    if args.device and args.device.lower() == "sim":
        sensor = vibechecker.VibeSensor.simulated()
        log.info("Using simulated sensor")
    elif args.device:
        sensors = vibechecker.VibeSensor.find()
        sensor  = next((s for s in sensors if args.device in s.serial_number), None)
        if sensor is None:
            log.error(f"Device '{args.device}' not found. "
                      f"Available: {[s.serial_number for s in sensors]}")
            return 1
    else:
        sensors = vibechecker.VibeSensor.find()
        if vibechecker.PICOSCOPE_DRIVER_MISSING:
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

    # ── Load device config and build collector ────────────────────────────────
    device_cfg = _cfg.load_device_config(sensor.serial_number)
    mon_cfg    = device_cfg.get("monitor", {})

    if args.interval is None:
        args.interval      = float(mon_cfg.get("interval_s",      3600))
    if args.pre_buffer is None:
        args.pre_buffer    = float(mon_cfg.get("pre_buffer_s",    60))
    if args.burst_duration is None:
        args.burst_duration = float(mon_cfg.get("burst_duration_s", 60))
    if args.output is None and mon_cfg.get("output_dir"):
        args.output = mon_cfg["output_dir"]
    if not args.no_compress and mon_cfg.get("compression") == "none":
        args.no_compress = True

    config = AcquisitionSettings.from_dict(device_cfg.get("acquisition", {}))
    _apply_overrides(config, args)

    collector = DataCollector()
    collector.config = config
    collector.init_trend_channels()

    # ── Connect stream ────────────────────────────────────────────────────────
    collector.connect_sensor(sensor)
    collector.start_stream()
    log.info(f"Stream started — {config.samplerate} Hz, {config.blocksize} samples, "
             f"channels {config.enabled_channels}")

    # ── Build session ─────────────────────────────────────────────────────────
    session_id = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    session    = _build_session(collector, args, session_id)
    monitor    = MonitorController()

    collector.resize_frame_cache(max(config.cache_frames, session.pre_buffer_frames))
    monitor.start(session)

    anom_cfg = mon_cfg.get("anomaly", {})
    if anom_cfg.get("enabled", False):
        from vibechecker.monitor.anomaly import (
            CompositeAnomalyHook, RmsThresholdHook, SpectralThresholdHook,
        )
        hook_type = anom_cfg.get("hook_type", "RMS")
        hooks = []
        if hook_type in ("RMS", "Both"):
            hooks.append(RmsThresholdHook(
                rms_threshold_pct    = float(anom_cfg.get("rms_pct",    10.0)),
                consecutive_n        = int(anom_cfg.get("rms_n",        3)),
                baseline_alpha       = float(anom_cfg.get("rms_alpha",  0.97)),
                min_baseline_samples = int(anom_cfg.get("rms_warmup",   30)),
            ))
        if hook_type in ("Spectral", "Both"):
            hooks.append(SpectralThresholdHook(
                spectral_threshold_db = float(anom_cfg.get("spec_db",   3.0)),
                consecutive_n         = int(anom_cfg.get("spec_n",      3)),
                fmin                  = float(anom_cfg.get("spec_fmin", 0.0)),
                fmax                  = float(anom_cfg.get("spec_fmax", 0.0)),
            ))
        if hooks:
            monitor.set_anomaly_hook(CompositeAnomalyHook(hooks))
            monitor.arm()
            log.info(f"Anomaly detection armed: {hook_type}")

    print(f"\nvibechecker headless — session {session_id}")
    print(f"  interval  : {args.interval}s")
    print(f"  output    : {session.session_dir}")
    print(f"  channels  : {config.enabled_channels}")
    print(f"  t + Enter : trigger manual burst")
    print(f"  Ctrl+C    : stop\n")

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

        for r in results:
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
    print(f"\nSession complete.")
    print(f"  Captures : {snap['capture_count']}")
    print(f"  Bursts   : {snap['burst_count']}")
    print(f"  File     : {session.session_h5}")
    print(f"  Size     : {snap['total_bytes'] / 1e6:.1f} MB")
    return 0


# ── Argument parser ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="vibechecker-headless",
        description="vibechecker interval datalogger — no GUI required",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Quick info commands (return immediately, no hardware required):\n"
            "  --list-devices    enumerate connected PicoScopes\n"
            "  --list-sensors    show IEPE sensor library\n"
            "  --edit-config     open default.yaml in $EDITOR"
        ),
    )

    # Info commands — handled before any heavy import
    info = parser.add_argument_group("info commands")
    info.add_argument("--list-devices", action="store_true",
                      help="List connected PicoScope devices and exit")
    info.add_argument("--list-sensors", action="store_true",
                      help="List IEPE sensors in the library and exit")
    info.add_argument("--edit-config",  action="store_true",
                      help="Open default.yaml in $EDITOR and exit")

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

    args = parser.parse_args()

    # Info commands: minimal imports, return immediately
    if args.list_devices:
        sys.exit(_list_devices())
    if args.list_sensors:
        sys.exit(_list_sensors())
    if args.edit_config:
        sys.exit(_edit_config())

    # Full session: now pull in everything
    import vibechecker
    vibechecker.setup_logging(debug=args.debug)
    sys.excepthook = vibechecker.exception_handler
    vibechecker.get_logger().info("vibechecker headless started")

    sys.exit(run(args))


if __name__ == "__main__":
    main()
