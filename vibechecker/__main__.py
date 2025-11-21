import sys
import vibechecker


if __name__=="__main__":
    # Attach logging tools
    vibechecker.logger.setup_logging() # create log files.
    vibechecker.logger.log_system_info()
    sys.excepthook = vibechecker.logger.exception_handler

    # Start App
    context = []
    app = vibechecker.GUI()
    app.context = []
    app.run()
