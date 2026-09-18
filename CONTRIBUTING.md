# Contributing to Rev80

Dev environment setup, project layout, and build/packaging instructions. For
usage, installation, configuration, and the vibration/DSP technical
reference, see **[README.md](README.md)**.

## Table of Contents

- [Development environment](#development-environment)
- [Moving the checkout](#moving-the-checkout)
- [Rendering docs to PDF](#rendering-docs-to-pdf)
- [Project layout](#project-layout)
- [Testing](#testing)
- [Replacing the app icon](#replacing-the-app-icon)
- [Building the Windows Installer](#building-the-windows-installer)

---

## Development environment

Linux / macOS recommended.

```bash
git clone <repo-url>/rev80.git
cd rev80

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install in editable mode with dev tools
pip install -e ".[dev]"

# Enable the repo's git hooks (once per clone) — keeps doc/*.pdf in sync
# with README.md, CONTRIBUTING.md, doc/PROGRESS.md, doc/CHANGELOG.md on commit
git config core.hooksPath .githooks

# Run the test suite (no hardware required — uses SimulatedSensor)
pytest tests/

# Launch the app against the source tree
python -m rev80
```

---

## Moving the checkout

Three things outside the repo are bound to its **absolute path** and break silently when the
checkout moves. This has happened on every relocation so far, so run all of it in one pass:

```bash
cd <new-path>

# 1. Re-point the editable install. Without this, `import rev80` and both console
#    scripts fail with ModuleNotFoundError while `pytest` keeps passing — tests
#    resolve via pyproject's `pythonpath = ["src"]`, which never consults the install.
pyenv local <env>                  # or: source .venv/bin/activate
python -c "import sys; print(sys.prefix)"   # confirm the intended env FIRST
pip install -e ".[dev]"

# 2. Re-enable git hooks. Use the relative path — an absolute `core.hooksPath`
#    silently disables every hook (including the blocking `ruff` gate) after a move.
git config core.hooksPath .githooks

# 3. Verify
rev80 --list-sensors               # must not raise ModuleNotFoundError
git config --get core.hooksPath    # must print: .githooks
```

`.python-version` and `.vscode/` are gitignored so each checkout owns its own dev environment;
they are not carried by `git clone`. Prefer `mv` over a fresh clone when relocating, or recreate
them by hand. Uninstall any stale distribution left over from the `vibechecker` era with
`pip uninstall vibechecker` — it is a separate dist and `pip install -e .` will not remove it.

Nothing *inside* the repo hardcodes an absolute path, and the user-level state
(`~/.config/rev80/`, `~/Documents/Rev80/data/`, the desktop entry) is path-independent.

---

## Rendering docs to PDF

`doc/README.pdf`, `doc/CONTRIBUTING.pdf`, `doc/PROGRESS.pdf`, and `doc/CHANGELOG.pdf` are
committed alongside their Markdown sources. The same `pre-commit` hook that runs `ruff`
(`.githooks/pre-commit`, enabled by the `git config core.hooksPath .githooks` step above)
also re-renders and stages the PDF for any of those four files that are part of a commit,
via `scripts/render_md.sh`:

```bash
# Render one file manually, e.g. after editing without committing
./scripts/render_md.sh README.md          # → doc/README.pdf
./scripts/render_md.sh doc/CHANGELOG.md   # → doc/CHANGELOG.pdf
```

Requires `pandoc` and `weasyprint` on PATH. If either is missing, the hook prints a warning
and skips rendering rather than blocking the commit — install them to keep the PDFs current:

```bash
# Debian/Ubuntu
sudo apt-get install pandoc
pip install weasyprint
```

---

## Project layout

```
src/rev80/                Python package
  _paths.py               Runtime-safe path resolution (dev vs frozen)
  _pico_loader.py         Windows DLL search path setup for frozen builds
  logging.yaml            Logging configuration (bundled with package)
  monitor/                Monitor Mode package
    __init__.py
    session.py            MonitorSession dataclass
    gate.py                IntervalGate scheduler
    anomaly.py             AnomalyHook protocol; Rms/Spectral/FixedThreshold hooks; Composite
    writer.py               MonitorWriterThread (daemon, writes session.h5)
    controller.py           MonitorController (is_recording; hook supplied at start)
  assets/                 Package data — bundled into wheels and frozen builds alike
    fonts/                CommitMono Nerd Font (gitignored; fetched by scripts/fetch_font.sh)
    icons/hicolor/        App icon PNG set (16..256px), for `rev80 --install-desktop-entry`
                           on Linux — see "Replacing the app icon" below
  desktop.py              Linux .desktop launcher entry + icon install/uninstall
assets/                   App icon source (edited directly by scripts/make_icons.sh)
  rev80.svg               Source artwork
  rev80.ico               Multi-resolution icon used by installer and exe
drivers/                  PicoScope DLLs (Windows build only, not committed)
installer/                Inno Setup script
tests/                    pytest suite
  test_monitor_controller.py
  test_monitor_gate.py
  test_monitor_index.py
  test_monitor_session_load.py   full write→load→browse integration tests
build/
  rev80.spec              PyInstaller build spec
  collect_pico_dlls.py    Collects PicoScope DLLs into drivers/
scripts/
  build.sh                Full build pipeline (run from Git Bash)
  make_icons.sh           Regenerates rev80.ico + the hicolor PNG set via Inkscape + ImageMagick
  fetch_font.sh           Downloads the CommitMono Nerd Font into src/rev80/assets/fonts/
  render_md.sh            Renders a Markdown file to PDF (pandoc + weasyprint) — see doc/
.githooks/
  pre-commit              ruff check (blocking; scope matches CI), and re-renders doc/*.pdf
                           for any of README.md, CONTRIBUTING.md, doc/PROGRESS.md,
                           doc/CHANGELOG.md staged in the commit
doc/
  README.pdf, CONTRIBUTING.pdf, PROGRESS.pdf, CHANGELOG.pdf   Rendered by the pre-commit hook
  PROGRESS.md              Delivery history — client requirements mapped to commits
  CHANGELOG.md             Keep-a-Changelog-format change log
```

---

## Testing

Tests use `VibeSensor.simulated()` and synthetic data — no hardware required. The full suite runs in ~50 s. Tests that write `.h5` scratch files use a project-relative `./DEVDATA/` directory (hardcoded in the test files, independent of the app's own `~/Documents/Rev80/data/` save location) — safe to delete between runs.

```bash
# Run all tests (no hardware)
pytest tests/

# Skip hardware-dependent tests explicitly
pytest tests/ -k "not hardware and not siggen"

# Single file
pytest tests/test_monitor_session_load.py

# Single test
pytest tests/test_vibechecker.py::test_save
```

| Test file | Coverage |
|---|---|
| `test_sample.py` | `AcquisitionSettings`, `VibeSample`, `ChannelResult` |
| `test_vibechecker.py` | `DataCollector` stream lifecycle, save/load, trend |
| `test_acquisition_settings.py` | Derived properties, setter validation |
| `test_scope_sensor.py` | Sensor calibration pipeline, mV→EU scaling |
| `test_picoscope.py` | `FindPicoScope` enumeration logic (mocked driver) |
| `test_config.py` | YAML persistence, defaults, atomic writes |
| `test_monitor_gate.py` | `IntervalGate` snap-to-grid, burst entry/exit |
| `test_monitor_anomaly.py` | `RmsThresholdHook` (warmup, streak, t=0 tracking), `SpectralThresholdHook` (EWMA, band masking), `FixedThresholdHook` (unit conversion, mV skip, modality mismatch), `CompositeAnomalyHook` |
| `test_monitor_controller.py` | `MonitorController` lifecycle, hook wiring, cooldown gating, HDF5 structure |
| `test_monitor_session_load.py` | Full write→load→browse integration: interval frames, burst frames, trend reconstruction, NaN regression guard |

Hardware-specific tests skip automatically when no PicoScope is detected.

---

## Replacing the app icon

Edit `assets/icons/rev80.svg`, then regenerate both the Windows `.ico` and the Linux
`hicolor` PNG set from it — no changes to `build/rev80.spec`, `installer/rev80.iss`,
or `desktop.py` are needed either way:

```bash
# From the repo root — requires inkscape and imagemagick
./scripts/make_icons.sh
```

This updates `src/rev80/assets/icons/hicolor/*/apps/rev80.png` (Linux desktop entry) in
place — commit it. It currently writes `rev80.ico` to the repo root rather than
`assets/icons/rev80.ico`; move it there manually before committing so `build/rev80.spec`
picks up the update.

---

## Building the Windows Installer

Produces a self-contained one-directory executable and a standalone installer (`.exe`) via PyInstaller and Inno Setup. **The build must run on a 64-bit Windows machine.**

### Prerequisites

| Tool | Where to get it | Notes |
| --- | --- | --- |
| Python 3.10+ (64-bit) | [python.org](https://www.python.org/downloads/) | Must be 64-bit; add to PATH |
| Git for Windows | [git-scm.com](https://git-scm.com/download/win) | Provides Git Bash for `scripts/build.sh` |
| PicoSDK 11.1.418 | [picotech.com/downloads](https://www.picotech.com/downloads) | **Reboot after install** |
| Inno Setup 6 | [jrsoftware.org/isinfo.php](https://jrsoftware.org/isinfo.php) | Per-user install to `%LOCALAPPDATA%` is fine |

Install project dependencies (from Git Bash or cmd.exe):

```bash
pip install -e ".[dev]"
```

### Running the build

```bash
# Run from the repo root
# Full pipeline: collect DLLs → PyInstaller → Inno Setup
./scripts/build.sh

# Individual steps
./scripts/build.sh dlls         # collect PicoScope DLLs into drivers/ only
./scripts/build.sh pyinstaller  # PyInstaller only (skips DLL collection)
./scripts/build.sh installer    # Inno Setup only (requires dist/ to exist)
./scripts/build.sh wheel        # Python wheel + sdist (runs anywhere, no Windows tooling)

# Flags, any position
./scripts/build.sh all clean    # force a full PyInstaller cache wipe
./scripts/build.sh all nodlls   # skip DLL collection -> driver-less bundle
```

`nodlls` is what CI uses; see [Automated releases](#automated-releases). `wheel`
is the only target that runs off Windows.

> **`python -m build` does not work from the repo root.** This repo has its own
> `build/` directory, which shadows the `build` PyPI package as an implicit
> namespace package: `import build` succeeds and `python -m build` fails with
> *No module named build.__main__*. `./scripts/build.sh wheel` runs it from a
> scratch directory to sidestep this — use that rather than calling the
> frontend directly.

### Output

| Path | Description |
| --- | --- |
| `dist/rev80/rev80.exe` | Standalone executable (no install needed) |
| `installer/Output/Rev80Setup-<version>.exe` | Installer with Start Menu shortcut and uninstaller |
| `dist/rev80-<version>-py3-none-any.whl` | Python wheel (`./scripts/build.sh wheel`) |
| `dist/rev80-<version>.tar.gz` | Source distribution |

### Known constraints

- **64-bit only** — PicoSDK DLLs are 64-bit; 32-bit Python will not work.
- **DearPyGui pinned to 2.0.0** — versions above 2.0.0 have a known viewport crash on Windows.
- **USB kernel driver** — `ps4000a.dll` is the user-mode library; the USB kernel driver is installed separately by PicoSDK. Reboot required before first hardware connection.
- **Code signing** — the installer and executable are unsigned; Windows SmartScreen will warn on first run. Sign with `osslsigncode` and a certificate if you need this.
- **Local builds still need real Windows hardware** — PyInstaller cross-compilation isn't reliable and PicoSDK's DLLs are Windows-only, so a full local build means: boot into Windows, pull, run `scripts/build.sh`. Tagged releases are automated instead — see below.

---

## Automated releases

Pushing a `vX.Y.Z` tag runs [`.github/workflows/release.yml`](.github/workflows/release.yml),
which builds the installer and the wheel and attaches both to a **draft** GitHub
Release. Review it, then publish by hand — the exe is unsigned, so a release is
worth a look before it goes out.

```bash
git tag v0.2.0
git push origin v0.2.0
# -> test gate -> wheel (ubuntu) + installer (windows) -> draft release
```

Four things about it are worth knowing before you rely on it:

- **CI installers are driver-less — by choice, not by constraint.** The release
  build passes `nodlls`, so no DLLs are bundled; the user installs PicoSDK
  themselves and the installer warns when it is missing. A local
  `./scripts/build.sh` is unchanged and still bundles `ps4000a.dll` +
  `picoipp.dll`. Dropping `nodlls` to ship a driver-bundled installer is a
  one-word change, gated only on the Pico redistribution licence.
- **PicoSDK *is* installed on the Windows runner**, which is a separate
  requirement from bundling. `picosdk`'s own `setup.py` probes for the native
  DLLs at **install** time and refuses to build without them, so without the SDK
  `pip install` fails before any of our code runs:

  ```
  TypeError: argument of type 'NoneType' is not iterable
  ERROR: Failed to build 'picosdk' when getting requirements to build wheel
  ```

  `find_library()` returns `None`, `ctypes.WinDLL(None)` raises `TypeError` —
  which its `except OSError` does not catch — and its `if not atleast1dll:
  exit(1)` would have failed anyway. On Linux the same line is
  `cdll.LoadLibrary(None)`, which is legal and returns a handle to the main
  program, so the probe passes; **that is why the ubuntu jobs install picosdk
  happily and a Windows job cannot.** Pre-installing the wrapper does not help
  either: the dependency is a direct git URL, so pip re-clones and re-runs
  `setup.py` for metadata regardless.

  The workflow silent-installs the SDK (`/quiet /norestart`, cached by version)
  and puts its `lib` directory on `PATH`. **No reboot is needed** — the restart
  PicoSDK asks for registers the USB *kernel driver*, which matters for talking
  to a scope, not for `LoadLibrary`-ing a user-mode DLL, and no scope is
  attached to a runner. Measured 2026-09-17: `find_library('ps4000a')` resolved
  and `WinDLL` loaded it in the same job, with the 7z extraction fallback
  unused.
- **A tag trigger ignores branches.** GitHub Actions has no notion of "tagged on
  main" — any `v*` tag, on any branch, builds a release. Deliberate, but it means
  a stray tag produces a draft.
- **The version comes from `git describe`.** Every job checks out with
  `fetch-depth: 0`; without tags `setuptools_scm` falls back to `0.0.0+unknown`
  and the release would ship `Rev80Setup-0.0.0+unknown.exe` with nothing failing.
  Both build jobs assert against that string, because it is the failure here that
  is otherwise silent.
- **The wheel is a release asset, not a PyPI package.** `picosdk` is a direct
  git URL dependency and PyPI rejects those. Publishing to PyPI would mean
  restructuring that dependency first.

Legacy `rc0.x` tags predate this and do not match `v*`; they will not trigger anything.

### Rehearsing it

Use a throwaway tag rather than a real version the first time, and check that the
installer job's log reports a real version rather than the fallback:

```bash
git tag v0.0.1rcx && git push origin v0.0.1rcx
# ...then delete the draft release and:
git push origin :v0.0.1rcx && git tag -d v0.0.1rcx
```
