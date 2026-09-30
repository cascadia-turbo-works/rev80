# rev80.spec  —  PyInstaller spec for the one-directory Windows bundle.
#
# Normally run by ./scripts/build.sh (CONTRIBUTING.md, section 10). By hand,
# from the repository root on Windows:
#   python -m PyInstaller build/rev80.spec --noconfirm
#
# Prerequisites (build.sh does all three):
#   pip install -e . --no-deps          (setuptools_scm writes _version.py)
#   ./scripts/fetch_font.sh             (copies the font into src/rev80/assets/fonts/)
#   python build/collect_pico_dlls.py   (copies the DLLs into drivers/; skipped by nodlls)

import re
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_all

# ── Paths ────────────────────────────────────────────────────────────────────

ROOT = Path(SPECPATH).parent
DRIVERS_DIR = ROOT / 'drivers'
LOGGING_YAML = ROOT / 'src' / 'rev80' / 'logging.yaml'
FONT_DIR = ROOT / 'src' / 'rev80' / 'assets' / 'fonts'
ICON_FILE = ROOT / 'assets' / 'icons' / 'rev80.ico'

# ── Version ──────────────────────────────────────────────────────────────────

_ver_text = (ROOT / 'src' / 'rev80' / '_version.py').read_text()
APP_VERSION = re.search(r'__version__ = "([^"]+)"', _ver_text).group(1)

# installer/rev80.iss includes version.iss (gitignored). Thus run this spec
# before iscc.
(ROOT / 'installer' / 'version.iss').write_text(f'#define AppVersion "{APP_VERSION}"\n')

print(f'Building version {APP_VERSION}')

# ── Hidden imports ───────────────────────────────────────────────────────────

# dearpygui embeds its own renderer; picosdk uses ctypes (no hidden imports).
hidden_imports = [
    'rev80._paths',
    'rev80._pico_loader',
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
    (str(LOGGING_YAML), 'rev80'),                                  # → sys._MEIPASS/rev80/logging.yaml
    (str(ROOT / 'assets'), 'assets'),                              # → sys._MEIPASS/assets/ (icons, etc.)
]

# The font goes to sys._MEIPASS/assets/fonts/, where _paths.resource_path()
# looks for it in a frozen app.
if FONT_DIR.is_dir():
    datas += [(str(FONT_DIR), 'assets/fonts')]                    # → sys._MEIPASS/assets/fonts/
else:
    print(
        'WARNING: src/rev80/assets/fonts/ not found. '
        'Run "./scripts/fetch_font.sh" first.'
    )

# Bundle drivers/ also when it holds no DLL (a nodlls build).
# _pico_loader registers sys._MEIPASS/drivers as a DLL directory.
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
    [str(ROOT / 'src' / 'rev80' / '__main__.py')],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

# ── Executable ───────────────────────────────────────────────────────────────

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='rev80',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                   # no console window
    icon=str(ICON_FILE),
)

# ── One-dir bundle ───────────────────────────────────────────────────────────
# Keep UPX off (here and in EXE). UPX compression of python3XX.dll makes the
# exe fail at start with "LoadLibrary failed".

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='rev80',
)
