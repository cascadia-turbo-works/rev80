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

def main():
    args, _ = _parse_args()

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
