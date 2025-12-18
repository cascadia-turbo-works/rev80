# Event Logging

import os
import sys
import platform
import yaml
import logging.config

def setup_logging(config_path="logging.yaml"):

    # load logging config
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Logging config not found: {config_path}")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # rename main logger to match package name
    if isinstance(__package__, str):
        config['loggers'][__package__] = config['loggers']['main']
        del config['loggers']['main']

    # Ensure the log directory exists
    for handler in config.get("handlers", {}).values():
        fname = handler.get("filename")
        if fname:
            os.makedirs(os.path.dirname(fname), exist_ok=True)

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
