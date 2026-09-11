from rev80.logger import (  # noqa: F401
    exception_handler,
    get_logger,
    install_excepthooks,
    log_system_info,
    resolve_version,
    setup_logging,
)

try:
    from rev80._version import __version__ as _stamped_version
except ImportError:
    _stamped_version = "0.0.0+unknown"

# In a source checkout the working tree is the truth: _version.py is stamped by
# a pre-commit hook that is not installed automatically, and has been observed
# 100 commits stale — which makes a field log impossible to tie to a build
# (audit H-03). In an installed or frozen build there is no git, and the stamp
# is authoritative.
__version__: str = resolve_version(_stamped_version)
from rev80.util import *  # noqa: F401, F403

PICOSCOPE_DRIVER_MISSING: bool = True
try:
    from rev80.picoscope import FindPicoScope  # noqa: F401

    PICOSCOPE_DRIVER_MISSING = False
except Exception:

    def FindPicoScope() -> list:  # type: ignore[misc]
        return []


from rev80.config import config_dir, load_device_config, save_device_config  # noqa: F401
from rev80.sample import AcquisitionSettings, ChannelResult, VibeSample  # noqa: F401
from rev80.scope_sensor import ScopeSensor  # noqa: F401
from rev80.scope_sensor_registry import ScopeSensorRegistry  # noqa: F401
from rev80.sensor import VibeSensor  # noqa: F401
from rev80.simulation import GenerateTone, SimulatedSensor  # noqa: F401
from rev80.collector import DataCollector  # noqa: F401
try:
    from rev80.gui import GUI  # noqa: F401
except ModuleNotFoundError:
    pass  # dearpygui not installed — headless mode only
from rev80.monitor import MonitorController, MonitorSession  # noqa: F401
