import sys
import vibechecker

if __name__ == "__main__":
    if "--headless" in sys.argv:
        sys.argv.remove("--headless")
        from vibechecker.headless import main
        main()
    else:
        consoledebug = "--debug" in sys.argv
        vibechecker.setup_logging(debug=consoledebug)
        vibechecker.log_system_info()
        sys.excepthook = vibechecker.exception_handler
        vibechecker.get_logger().info('Vibechecker Launched')
        app = vibechecker.GUI()
        app.initialize()
        app.run()
        app.cleanup()
