import os
import sys
import platform
import yaml
import logging.config

def setup_logging(config_path="logging.yaml"):
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Logging config not found: {config_path}")

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # Ensure the log directory exists
    for handler in config.get("handlers", {}).values():
        fname = handler.get("filename")
        if fname:
            os.makedirs(os.path.dirname(fname), exist_ok=True)

    logging.config.dictConfig(config)

def get_logger(name: str = None):
    """Return a sublogger under the 'vibe' namespace."""
    base = "vibe"
    logname = base
    if name:
        logname += '.' + name

    return logging.getLogger(logname)

baselog = get_logger()
def exception_handler(exc_type, exc, tb):
    '''Capture any unhandled exceptions to log'''
    baselog.error("Unhandled GUI exception:", exc_info=(exc_type, exc, tb))

def log_system_info():
    '''
    Log platform specific info to log.
    '''

    baselog.info('Vibechecker Launched')

    sysinfo = f'''.
    ======== SYSTEM INFORMATION =======
    || OS:               {platform.system()} {platform.release()}
    || Machine:          {platform.machine()}
    || Processor:        {platform.processor()}
    || Python version:   {platform.python_version()}
    || Executable path:  {sys.executable}
    ===================================
    '''

    baselog.debug(sysinfo)
