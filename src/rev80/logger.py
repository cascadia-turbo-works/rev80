# Event Logging

import os
import sys
import platform
import yaml
import logging.config

from rev80._paths import resource_path, log_dir


def setup_logging(debug: bool = False) -> None:
    """Load logging configuration and direct file handlers to the correct log dir."""
    config_file = resource_path("rev80/logging.yaml")
    if not config_file.exists():
        raise FileNotFoundError(f"Logging config not found: {config_file}")
    with open(config_file, "r") as f:
        config = yaml.safe_load(f)

    # rename main logger to match package name
    if isinstance(__package__, str):
        config['loggers'][__package__] = config['loggers']['main']
        del config['loggers']['main']

    # Redirect file handlers to the runtime-safe log directory
    _log_dir = log_dir()
    for handler in config.get("handlers", {}).values():
        fname = handler.get("filename")
        if fname:
            # Replace bare relative filename (e.g. "log/main.log") with absolute path
            handler["filename"] = str(_log_dir / os.path.basename(fname))

    if debug:
        config['handlers']['console']['level'] = logging.DEBUG

    # setup config
    logging.config.dictConfig(config)

def get_logger(name:str=''):
    """Return a sublogger under the __package__ namespace."""
    
    tag = [] 
    if isinstance(__package__, str):
        tag.append(__package__)
    else:
        tag.append('main')

    if name:
        tag.append(name)

    logname = '.'.join(tag)
    
    return logging.getLogger(logname)

baselog = get_logger()
def exception_handler(exc_type, exc, tb):
    '''Capture any unhandled exceptions to log'''
    baselog.error("Unhandled GUI exception:", exc_info=(exc_type, exc, tb))

def log_system_info():
    '''
    Log platform specific info to log.
    '''

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
