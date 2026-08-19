try:
    from rev80._version import __version__  # noqa: F401
except ImportError:
    __version__ = "0.0.0+unknown"

from rev80.logger import exception_handler, get_logger, log_system_info, setup_logging  # noqa: F401
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
