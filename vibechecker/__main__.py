import sys
import vibechecker

if __name__=="__main__":
    # Attach logging tools
    vibechecker.setup_logging() # create log files.
    vibechecker.log_system_info()
    sys.excepthook = vibechecker.exception_handler

    # Start App
    app = vibechecker.GUI()
    app.run()
