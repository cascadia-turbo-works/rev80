import argparse
import sys

import rev80


def _init_config() -> int:
    from rev80.config import acquisition_config_path, ensure_config_dir
    cfg_dir = acquisition_config_path().parent
    before  = set(cfg_dir.rglob('*.yaml')) if cfg_dir.exists() else set()

    ensure_config_dir()

    print(f"Config directory: {cfg_dir}\n")
    for path in sorted(cfg_dir.rglob('*.yaml')):
        tag = " [created]" if path not in before else ""
        print(f"  {path.relative_to(cfg_dir)}{tag}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    from rev80.headless import build_option_parser

    parser = argparse.ArgumentParser(
        prog="rev80",
        description="Rev80 — industrial vibration analysis for PicoScope",
    )
    parser.add_argument("--version", action="store_true",
                         help="Print version and exit")

    # Info commands — no GUI, no hardware required. Same behavior as `rev80-headless`.
    info = parser.add_argument_group("info commands")
    info.add_argument("--init-config",  action="store_true",
                       help="Seed ~/.config/rev80/ with default config files and exit")
    info.add_argument("--list-devices", action="store_true",
                       help="List connected PicoScope devices and exit")
    info.add_argument("--list-sensors", action="store_true",
                       help="List IEPE sensors in the library and exit")
    info.add_argument("--edit-config",  action="store_true",
                       help="Open acquisition.yaml in $EDITOR and exit")

    # Linux desktop integration — no-ops (with a warning) on other platforms
    desktop = parser.add_argument_group("linux desktop integration")
    desktop.add_argument("--install-desktop-entry", action="store_true",
                          help="Install a ~/.local/share/applications/rev80.desktop "
                               "launcher entry + icon and exit")
    desktop.add_argument("--uninstall-desktop-entry", action="store_true",
                          help="Remove the desktop launcher entry + icon and exit")

    # GUI launch options
    gui = parser.add_argument_group("gui options")
    gui.add_argument("--from-file",  metavar="PATH", default=None,
                      help="Load an h5 measurement or monitor session on startup")
    gui.add_argument("--autodetect", action=argparse.BooleanOptionalAction, default=None,
                      help="Auto-connect to a PicoScope on launch (default: true, "
                           "false when --from-file is given)")
    gui.add_argument("--debug", action="store_true",
                      help="Verbose logging to stderr")

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        "headless",
        parents=[build_option_parser()],
        description="Rev80 interval datalogger — no GUI required",
        help="Run the interval datalogger with no GUI (same options as rev80-headless)",
    )

    return parser


def main():
    parser = _build_parser()
    args = parser.parse_args()

    if args.version:
        print(rev80.__version__)
        sys.exit(0)

    if args.command == "headless":
        from rev80.headless import run_headless
        sys.exit(run_headless(args))

    if args.init_config:
        sys.exit(_init_config())
    if args.list_devices:
        from rev80.headless import _list_devices
        sys.exit(_list_devices())
    if args.list_sensors:
        from rev80.headless import _list_sensors
        sys.exit(_list_sensors())
    if args.edit_config:
        from rev80.headless import _edit_config
        sys.exit(_edit_config())
    if args.install_desktop_entry:
        from rev80.desktop import install as install_desktop_entry
        sys.exit(install_desktop_entry())
    if args.uninstall_desktop_entry:
        from rev80.desktop import uninstall as uninstall_desktop_entry
        sys.exit(uninstall_desktop_entry())

    # Default autodetect=False when opening a file; True otherwise
    if args.autodetect is None:
        args.autodetect = args.from_file is None

    rev80.setup_logging(debug=args.debug)
    rev80.log_system_info()
    # Installs sys.excepthook AND threading.excepthook AND faulthandler.
    # The thread hook is the one that was missing: everything interesting
    # in this app runs off the main thread, and those deaths went to
    # stderr, which is nowhere when launched from a desktop entry.
    rev80.install_excepthooks()
    rev80.get_logger().info('Rev80 Launched')
    app = rev80.GUI()
    app.initialize()
    app.run(initial_file=args.from_file, autodetect=args.autodetect)
    app.cleanup()


if __name__ == "__main__":
    main()
