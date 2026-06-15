# vibechecker.spec  —  PyInstaller build spec
#
# Build (from project root on Windows):
#   pyinstaller vibechecker.spec
#
# Prerequisites:
#   pip install pyinstaller
#   python build/collect_pico_dlls.py   (copies DLLs to drivers/)

import re
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_all

# ── Paths ────────────────────────────────────────────────────────────────────

ROOT = Path(SPECPATH)
DRIVERS_DIR = ROOT / 'drivers'
LOGGING_YAML = ROOT / 'vibechecker' / 'logging.yaml'
ICON_FILE = ROOT / 'assets' / 'icons' / 'vibechecker.ico'

# ── Version ──────────────────────────────────────────────────────────────────

_ver_text = (ROOT / 'vibechecker' / '_version.py').read_text()
APP_VERSION = re.search(r'__version__ = "([^"]+)"', _ver_text).group(1)

# Write installer/version.iss so iscc picks it up without extra arguments
(ROOT / 'installer' / 'version.iss').write_text(f'#define AppVersion "{APP_VERSION}"\n')

print(f'Building version {APP_VERSION}')

# ── Hidden imports ───────────────────────────────────────────────────────────

# dearpygui embeds its own renderer; picosdk uses ctypes (no hidden imports).
hidden_imports = [
    'vibechecker._paths',
    'vibechecker._pico_loader',
    'scipy.signal',
    'scipy.signal.windows',
    'scipy.fft',
    'h5py',
    'h5py._hl',
    'h5py.defs',
    'h5py.utils',
    'h5py._conv',
    'h5py._proxy',
    'numpy',
    'dearpygui.dearpygui',
    'yaml',
    # plyer platform detection is dynamic; bundle all backends explicitly
    *collect_submodules('plyer'),
    # win32com is loaded dynamically by plyer's Windows filechooser backend
    'win32com',
    'win32com.shell',
    'win32com.shell.shell',
    'pywintypes',
]

# ── Bundled data files ───────────────────────────────────────────────────────

datas = [
    (str(LOGGING_YAML), '.'),                                      # → sys._MEIPASS/logging.yaml
    (str(ROOT / 'assets'), 'assets'),                              # → sys._MEIPASS/assets/
]

# Bundle PicoScope DLLs under drivers/ sub-directory
if DRIVERS_DIR.is_dir():
    datas += [(str(DRIVERS_DIR), 'drivers')]
else:
    print(
        'WARNING: drivers/ directory not found. '
        'Run "python build/collect_pico_dlls.py" on a Windows machine with PicoSDK installed.'
    )

# Collect dearpygui font/theme data if present
datas += collect_data_files('dearpygui')

# ── Binaries ─────────────────────────────────────────────────────────────────

binaries = []

# ── Excludes (trim unused scipy subpackages to reduce size) ──────────────────

excludes = [
    'tkinter',
    'matplotlib',
    'IPython',
    'ipykernel',
    'notebook',
    'sounddevice',   # not used in the PicoScope-only build; remove if audio support needed
]

# ── Analysis ─────────────────────────────────────────────────────────────────

a = Analysis(
    [str(ROOT / 'vibechecker' / '__main__.py')],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# ── Executable ───────────────────────────────────────────────────────────────

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='vibechecker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                   # no console window
    icon=str(ICON_FILE),
)

# ── One-dir bundle ───────────────────────────────────────────────────────────
# UPX disabled: compressing python3XX.dll causes "LoadLibrary failed" on
# launch; PyInstaller already compresses .pyc into PYZ so UPX saves little.

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='vibechecker',
)
