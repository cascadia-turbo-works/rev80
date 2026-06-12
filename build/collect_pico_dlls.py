"""
collect_pico_dlls.py  —  Run on a Windows machine with PicoSDK installed.

Locates the 64-bit PicoScope 4000A DLLs and copies them to the
project's drivers/ directory so they can be bundled by PyInstaller.

Usage (from the project root on Windows):
    python build/collect_pico_dlls.py

Output:
    drivers/ps4000a.dll
    drivers/picoipp.dll   (runtime dependency of ps4000a.dll)

Requirements:
    - 64-bit Windows
    - PicoSDK installed (default path: C:\\Program Files\\Pico Technology\\SDK)
    - Python 3.8+ (64-bit)
"""

import platform
import shutil
import struct
import sys
from pathlib import Path

# ── Configuration ────────────────────────────────────────────────────────────

REQUIRED_DLLS = ['ps4000a.dll', 'picoipp.dll']

# PicoSDK default install locations (ordered by preference)
PICO_SDK_CANDIDATES = [
    r'C:\Program Files\Pico Technology\SDK\lib',
    r'C:\Program Files (x86)\Pico Technology\SDK\lib',
]

# Also probe registry for non-default install locations
_REG_KEYS = [
    (r'SOFTWARE\Pico Technology\SDK', 'InstallPath'),
    (r'SOFTWARE\WOW6432Node\Pico Technology\SDK', 'InstallPath'),
]

DRIVERS_DIR = Path(__file__).parent.parent / 'drivers'

# ── Helpers ──────────────────────────────────────────────────────────────────


def _check_platform() -> None:
    if platform.system() != 'Windows':
        sys.exit('collect_pico_dlls.py must be run on Windows.')
    if struct.calcsize('P') != 8:
        sys.exit('Must be run with 64-bit Python (PicoSDK DLLs are 64-bit only).')


def _probe_registry() -> tuple[list[str], bool]:
    """Return (sdk_lib_paths, registry_key_found).

    registry_key_found is True when the PicoSDK installer has written its
    registry entry, even if the lib path doesn't exist yet (pending reboot).
    """
    paths: list[str] = []
    found_in_registry = False
    try:
        import winreg
        for key_path, value_name in _REG_KEYS:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                    found_in_registry = True
                    install_path, _ = winreg.QueryValueEx(key, value_name)
                    candidate = str(Path(install_path) / 'lib')
                    if candidate not in paths:
                        paths.append(candidate)
            except FileNotFoundError:
                pass
    except ImportError:
        pass  # winreg not available (non-Windows)
    return paths, found_in_registry


def _find_dll(dll_name: str, search_dirs: list[str]) -> Path | None:
    for d in search_dirs:
        candidate = Path(d) / dll_name
        if candidate.is_file():
            return candidate
    return None


def _is_64bit_dll(dll_path: Path) -> bool:
    """Return True if the PE header indicates a 64-bit (AMD64) DLL."""
    try:
        with open(dll_path, 'rb') as f:
            dos_header = f.read(64)
            if dos_header[:2] != b'MZ':
                return False
            pe_offset = struct.unpack_from('<I', dos_header, 60)[0]
            f.seek(pe_offset)
            pe_sig = f.read(4)
            if pe_sig != b'PE\x00\x00':
                return False
            machine = struct.unpack_from('<H', f.read(20))[0]
            return machine == 0x8664  # IMAGE_FILE_MACHINE_AMD64
    except Exception:
        return False


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    _check_platform()

    # Build ordered search path: registry first, then well-known defaults
    reg_paths, sdk_in_registry = _probe_registry()
    search_dirs = reg_paths + PICO_SDK_CANDIDATES
    print(f'Searching for DLLs in: {search_dirs}')

    DRIVERS_DIR.mkdir(parents=True, exist_ok=True)

    missing: list[str] = []
    for dll_name in REQUIRED_DLLS:
        src = _find_dll(dll_name, search_dirs)
        if src is None:
            print(f'  NOT FOUND: {dll_name}')
            missing.append(dll_name)
            continue
        if not _is_64bit_dll(src):
            sys.exit(
                f'ERROR: {src} is not a 64-bit DLL. '
                'Install 64-bit PicoSDK and use 64-bit Python.'
            )
        dst = DRIVERS_DIR / dll_name
        shutil.copy2(src, dst)
        print(f'  Copied {dll_name}: {src} → {dst}')

    if missing:
        if sdk_in_registry:
            sys.exit(
                f'ERROR: PicoSDK is registered but its DLLs are not yet visible: {missing}\n'
                'The installer requires a reboot to complete driver registration.\n'
                'Please restart Windows and re-run the build.'
            )
        sys.exit(
            f'ERROR: Could not locate the following DLLs: {missing}\n'
            'Install PicoSDK from https://www.picotech.com/downloads,\n'
            'restart Windows, then re-run the build.'
        )

    print(f'\nAll DLLs collected to {DRIVERS_DIR}/')


if __name__ == '__main__':
    main()
