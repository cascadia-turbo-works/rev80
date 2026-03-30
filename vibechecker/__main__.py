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
    app = vibechecker.GUI()
    app.initialize()
    app.run()
    app.cleanup()
