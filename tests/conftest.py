"""Skip the GUI tests where dearpygui is not installed.

pyproject.toml installs dearpygui on x86-64 only, so on an ARM board such as
a Raspberry Pi the modules that import it at module scope cannot be collected.
They are left out of collection, and the report header names them.
"""
import importlib.util
import re
from pathlib import Path

HAS_DEARPYGUI = importlib.util.find_spec("dearpygui") is not None

_GUI_IMPORT = re.compile(
    r"^(import dearpygui|from rev80\.gui |import rev80\.gui|from rev80 import gui)",
    re.MULTILINE,
)

collect_ignore = [] if HAS_DEARPYGUI else sorted(
    path.name for path in Path(__file__).parent.glob("test_*.py")
    if _GUI_IMPORT.search(path.read_text(encoding="utf-8"))
)


def pytest_report_header(config):
    if collect_ignore:
        return [f"dearpygui not installed: {len(collect_ignore)} GUI test "
                f"modules not collected: {', '.join(collect_ignore)}"]
    return None
