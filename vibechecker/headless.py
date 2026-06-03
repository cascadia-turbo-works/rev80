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

Options
-------
    --interval SECS         Capture interval (default: 3600)
    --pre-buffer SECS       Pre-trigger buffer duration (default: 60)
    --burst-duration SECS   Burst capture duration (default: 60)
    --output DIR            Override output root directory
    --device SERIAL         Force a specific PicoScope serial, or 'sim'
    --channels N [N ...]    Channel indices to enable (e.g. --channels 0 1)
    --maxfreq HZ            Max analysis frequency override
    --binsize HZ            Frequency resolution override
    --no-compress           Disable gzip compression
    --debug                 Verbose logging to stderr
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import vibechecker
import vibechecker.config as _cfg
from vibechecker.collector import DataCollector
from vibechecker.monitor.controller import MonitorController
from vibechecker.monitor.session import MonitorSession
from vibechecker.sample import AcquisitionSettings

log = vibechecker.get_logger(__name__)

_SHUTDOWN = False


def _handle_signal(signum, frame):
    global _SHUTDOWN
    log.info(f"Received signal {signum} — shutting down after current interval…")
    _SHUTDOWN = True


def _build_session(collector: DataCollector, args: argparse.Namespace,
                   session_id: str) -> MonitorSession:
    """Construct a MonitorSession from the live collector state + CLI args."""
    cfg = collector.config
    block_s = cfg.blocksize / cfg.samplerate if cfg.samplerate else 1.0
    pre_buffer_n = max(1, int(args.pre_buffer / block_s))

    if args.output:
        session_dir = Path(args.output) / session_id
    else:
        session_dir = vibechecker.data_dir() / "monitor" / session_id

    acq_snapshot = cfg.to_dict()

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

    return MonitorSession(
        session_id        = session_id,
        start_time        = datetime.now(timezone.utc),
        interval_s        = float(args.interval),
        pre_buffer_frames = pre_buffer_n,
        burst_duration_s  = float(args.burst_duration),
        max_burst_s       = 600.0,
        session_dir       = session_dir,
        compression       = "none" if args.no_compress else "gzip",
        compression_level = 4,
        acq_snapshot      = acq_snapshot,
        channel_snapshot  = ch_snapshot,
        sensor_snapshot   = sensor_snapshot,
    )


def _apply_overrides(config: AcquisitionSettings, args: argparse.Namespace) -> None:
    """Apply CLI overrides to AcquisitionSettings in-place."""
    if args.maxfreq:
        config.maxfreq = float(args.maxfreq)
    if args.binsize:
        config.binsize = float(args.binsize)
    if args.channels:
        config.enabled_channels = sorted(set(int(c) for c in args.channels))


def run(args: argparse.Namespace) -> int:
    """Main headless loop. Returns exit code."""
    global _SHUTDOWN

    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # ── Discover device ───────────────────────────────────────────────────────
    if args.device and args.device.lower() == "sim":
        sensor = vibechecker.VibeSensor.simulated()
        log.info("Using simulated sensor")
    elif args.device:
        sensors = vibechecker.VibeSensor.find()
        sensor = next((s for s in sensors if args.device in s.serial_number), None)
        if sensor is None:
            log.error(f"Device '{args.device}' not found. Available: "
                      f"{[s.serial_number for s in sensors]}")
            return 1
    else:
        sensors = vibechecker.VibeSensor.find()
        if not sensors:
            log.warning("No PicoScope found — falling back to simulated sensor. "
                        "Pass --device sim to suppress this warning.")
            sensor = vibechecker.VibeSensor.simulated()
        else:
            sensor = sensors[0]
            log.info(f"Found {sensor.model} s/n {sensor.serial_number}")

    # ── Load device config and build collector ────────────────────────────────
    serial = sensor.serial_number
    device_cfg = _cfg.load_device_config(serial)

    config = AcquisitionSettings.from_dict(
        device_cfg.get("acquisition", {})
    )
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

    collector.resize_frame_cache(
        max(config.cache_frames, session.pre_buffer_frames)
    )
    monitor.start(session)

    log.info(
        f"Monitor session started: {session_id}\n"
        f"  interval={args.interval}s  pre-buffer={args.pre_buffer}s  "
        f"burst={args.burst_duration}s\n"
        f"  output → {session.session_dir}"
    )
    print(f"\nvibechecker headless — session {session_id}")
    print(f"  interval  : {args.interval}s")
    print(f"  output    : {session.session_dir}")
    print(f"  channels  : {config.enabled_channels}")
    print(f"  Press Ctrl+C to stop\n")

    # ── Event loop ────────────────────────────────────────────────────────────
    last_status = time.monotonic()

    while not _SHUTDOWN:
        if not collector.new_frame_event.wait(timeout=1.0):
            continue
        collector.new_frame_event.clear()

        results = collector.process_samples()
        if results:
            monitor.on_results(results, collector.data["frame_cache"])

        # Print status line every 10 s
        now = time.monotonic()
        if now - last_status >= 10.0:
            snap = monitor.status_snapshot()
            h, rem = divmod(int(snap["elapsed_s"]), 3600)
            m, s   = divmod(rem, 60)
            print(
                f"  [{h:02d}:{m:02d}:{s:02d}]  "
                f"captures={snap['capture_count']}  "
                f"bursts={snap['burst_count']}  "
                f"next={snap['next_capture_s']:.0f}s  "
                f"size={snap['total_bytes'] / 1e6:.1f} MB",
                flush=True,
            )
            if snap["error"]:
                log.error(f"Writer error: {snap['error']}")
                _SHUTDOWN = True
            last_status = now

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

    log.info(
        f"Headless session finished. captures={snap['capture_count']} "
        f"bursts={snap['burst_count']} path={session.session_h5}"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="vibechecker-headless",
        description="vibechecker interval datalogger — no GUI required",
    )
    parser.add_argument("--interval",       type=float, default=3600,
                        metavar="SECS",
                        help="Capture interval in seconds (default: 3600)")
    parser.add_argument("--pre-buffer",     type=float, default=60,
                        metavar="SECS",
                        help="Pre-trigger buffer duration in seconds (default: 60)")
    parser.add_argument("--burst-duration", type=float, default=60,
                        metavar="SECS",
                        help="Burst capture duration in seconds (default: 60)")
    parser.add_argument("--output",         type=str,   default=None,
                        metavar="DIR",
                        help="Override output root directory")
    parser.add_argument("--device",         type=str,   default=None,
                        metavar="SERIAL",
                        help="PicoScope serial number, or 'sim' for simulation")
    parser.add_argument("--channels",       type=int,   nargs="+",
                        metavar="N",
                        help="Channel indices to enable (e.g. --channels 0 1)")
    parser.add_argument("--maxfreq",        type=float, default=None,
                        metavar="HZ",
                        help="Max analysis frequency override (Hz)")
    parser.add_argument("--binsize",        type=float, default=None,
                        metavar="HZ",
                        help="Frequency resolution override (Hz)")
    parser.add_argument("--no-compress",    action="store_true",
                        help="Disable gzip compression")
    parser.add_argument("--debug",          action="store_true",
                        help="Verbose logging to stderr")

    args = parser.parse_args()

    vibechecker.setup_logging(debug=args.debug)
    sys.excepthook = vibechecker.exception_handler
    vibechecker.get_logger().info("vibechecker headless started")

    sys.exit(run(args))


if __name__ == "__main__":
    main()
