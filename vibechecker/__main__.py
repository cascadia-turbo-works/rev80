import sys
import vibechecker

DEBUG_FLAG = "--debug"

if __name__=="__main__":
    consoledebug = DEBUG_FLAG in sys.argv

    # Attach logging tools
    vibechecker.setup_logging(debug=consoledebug) # create log files.
    vibechecker.log_system_info()
    sys.excepthook = vibechecker.exception_handler

    vibechecker.get_logger().info('Vibechecker Launched')

    # Start App
    try:
        print("Creating GUI...", flush=True)
        app = vibechecker.GUI()
        print("Initializing...", flush=True)
        app.initialize()
        print("Running...", flush=True)
        app.run()
        app.cleanup()
    except Exception:
        import traceback
        traceback.print_exc()
        vibechecker.get_logger().exception("Fatal startup error")
        input("Press Enter to exit...")
