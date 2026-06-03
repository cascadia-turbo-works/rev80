import argparse
import sys
import vibechecker

def _parse_args():
    p = argparse.ArgumentParser(
        prog="vibechecker",
        description="vibechecker — vibration analysis GUI",
        add_help=False,   # keep --help working via DPG passthrough
    )
    p.add_argument("--headless",   action="store_true")
    p.add_argument("--from-file",  metavar="PATH", default=None,
                   help="Load an h5 measurement or monitor session on startup")
    p.add_argument("--debug",      action="store_true")
    args, remaining = p.parse_known_args()
    return args, remaining

if __name__ == "__main__":
    args, _ = _parse_args()

    if args.headless:
        # Strip --headless; remaining argv is for headless parser
        sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a != "--headless"]
        from vibechecker.headless import main
        main()
    else:
        vibechecker.setup_logging(debug=args.debug)
        vibechecker.log_system_info()
        sys.excepthook = vibechecker.exception_handler
        vibechecker.get_logger().info('Vibechecker Launched')
        app = vibechecker.GUI()
        app.initialize()
        app.run(initial_file=args.from_file)
        app.cleanup()
