try:
    from vibechecker._version import __version__  # noqa: F401
except ImportError:
    __version__ = "0.0.0+unknown"

from vibechecker.logger import exception_handler, get_logger, log_system_info, setup_logging  # noqa: F401
from vibechecker.util import *  # noqa: F401, F403

PICOSCOPE_DRIVER_MISSING: bool = True
try:
    from vibechecker.picoscope import FindPicoScope  # noqa: F401

    PICOSCOPE_DRIVER_MISSING = False
except Exception:

    def FindPicoScope() -> list:  # type: ignore[misc]
        return []


from vibechecker.config import config_dir, load_device_config, save_device_config  # noqa: F401
from vibechecker.sample import AcquisitionSettings, ChannelResult, VibeSample  # noqa: F401
from vibechecker.scope_sensor import ScopeSensor  # noqa: F401
from vibechecker.scope_sensor_registry import ScopeSensorRegistry  # noqa: F401
from vibechecker.sensor import VibeSensor  # noqa: F401
from vibechecker.simulation import GenerateTone, SimulatedSensor  # noqa: F401
from vibechecker.collector import DataCollector  # noqa: F401
try:
    from vibechecker.gui import GUI  # noqa: F401
except ModuleNotFoundError:
    pass  # dearpygui not installed — headless mode only
from vibechecker.monitor import MonitorController, MonitorSession  # noqa: F401
