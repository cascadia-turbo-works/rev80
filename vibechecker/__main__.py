import argparse
import sys
import vibechecker

def _parse_args():
    p = argparse.ArgumentParser(
        prog="vibechecker",
        description="vibechecker — vibration analysis GUI",
        add_help=False,   # keep --help working via DPG passthrough
    )
    p.add_argument("--headless",      action="store_true")
    p.add_argument("--init-config",   action="store_true",
                   help="Seed ~/.config/vibechecker/ with default config files and exit")
    p.add_argument("--from-file",     metavar="PATH", default=None,
                   help="Load an h5 measurement or monitor session on startup")
    p.add_argument("--autodetect",    action=argparse.BooleanOptionalAction,
                   default=None,
                   help="Auto-connect to a PicoScope on launch (default: true, "
                        "false when --from-file is given)")
    p.add_argument("--debug",         action="store_true")
    args, remaining = p.parse_known_args()

    # Default autodetect=False when opening a file; True otherwise
    if args.autodetect is None:
        args.autodetect = args.from_file is None

    return args, remaining

def _init_config() -> int:
    from vibechecker.config import acquisition_config_path, ensure_config_dir
    cfg_dir = acquisition_config_path().parent
    before  = set(cfg_dir.rglob('*.yaml')) if cfg_dir.exists() else set()

    ensure_config_dir()

    print(f"Config directory: {cfg_dir}\n")
    for path in sorted(cfg_dir.rglob('*.yaml')):
        tag = " [created]" if path not in before else ""
        print(f"  {path.relative_to(cfg_dir)}{tag}")
    return 0


def main():
    args, _ = _parse_args()

    if args.init_config:
        sys.exit(_init_config())

    if args.headless:
        sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a != "--headless"]
        from vibechecker.headless import main as headless_main
        headless_main()
    else:
        vibechecker.setup_logging(debug=args.debug)
        vibechecker.log_system_info()
        sys.excepthook = vibechecker.exception_handler
        vibechecker.get_logger().info('Vibechecker Launched')
        app = vibechecker.GUI()
        app.initialize()
        app.run(initial_file=args.from_file, autodetect=args.autodetect)
        app.cleanup()

if __name__ == "__main__":
    main()
