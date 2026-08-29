# Branch notes — `chore/config-consistency-ci`

Draft changelog entry for the orchestrating session to fold into
`doc/CHANGELOG.md`. Delete this file afterwards.

Scope: repository configuration, cross-file consistency, and CI. DSP and
measurement math were deliberately left alone (concurrent branch).

Final state: `ruff check src/ tests/` clean; `pytest tests/ -q` →
**434 passed, 1 skipped** (up from 290 passed / 1 failed / 9 skipped on
`develop`). 135 tests added.

---

## [Unreleased] — chore/config-consistency-ci

### Added

- **`.github/workflows/ci.yml`** — first CI for the project. There was no
  `.github/` at all: 300+ tests and nothing ran them.
  - push + pull_request, `ubuntu-latest`, matrix over Python 3.10–3.13
    (the range the new `requires-python` floor admits)
  - checkout → setup-python → `pip install -e ".[dev]"` → `ruff check src/ tests/`
    → `pytest tests/ -q`; `fail-fast: false`, concurrency group cancels
    superseded runs
  - installs `libx11-6`: dearpygui's `_dearpygui.so` links against libX11 at
    load time (confirmed with `ldd`). No GL and no X server are needed because
    the suite never calls `create_viewport()`.
  - the native PicoSDK driver is deliberately **not** installed; the suite runs
    against `SimulatedSensor`
  - **Verified end to end locally**, not assumed: a clean Python 3.12 venv built
    exactly as CI does, with the PicoSDK driver stubbed out and
    `DISPLAY`/`WAYLAND_DISPLAY` unset, gives 300 passed / 10 skipped. The
    `picosdk` `git+https` pin resolved and built a wheel with no special
    handling, so `--no-deps` is not needed. `dearpygui==2.0.0` publishes
    manylinux wheels for cp310–cp313 (checked against the PyPI JSON API), so the
    whole matrix is covered.
- **`util.py`** — `amplitude_scale(mode)`, `nearest_interval_preset(seconds)`,
  `canonical_hook_type(value)`, `hook_type_label(value)`, `ANOMALY_HOOK_LABELS`,
  `DEFAULT_AMPLITUDE_MODE`, `DEFAULT_ANOMALY_HOOK_TYPE`, `DEFAULT_RMS_ALPHA`,
  `DEFAULT_SPEC_ALPHA`, and an explicit `__all__`
- **`util.py`** — `600: '10 min'` added to `MONITOR_INTERVAL_PRESETS`
- **`README.md`** — Contributing section now documents the one-time
  `git config core.hooksPath .githooks` install step
- **Tests** — 7 new files, 135 tests: `test_gui_save_config.py`,
  `test_icons.py`, `test_monitor_pretrigger_scaling.py`,
  `test_sensor_library_integrity.py`, `test_config_contract.py`,
  `test_anomaly_hook_build.py`, `test_util_small_defects.py`

### Fixed

- **`.githooks/pre-commit`** — still ran `ruff check vibechecker/` and wrote
  `vibechecker/_version.py` after the rebrand moved the package to
  `src/rev80/`. ruff exited non-zero against a nonexistent directory, so the
  hook blocked every commit for anyone who had installed it. Repointed at
  `src/ tests/` and `src/rev80/_version.py`.
  - `src/rev80/_version.py` regenerated: it read `rc0.4-10-g11a72f4` while
    `git describe` gives `rc0.5-44-g7bf4712`. **Shipped builds reported a
    version 34 commits behind, so a field bug report could not be tied to a
    build.**
  - Root cause of the silent rot: the hook is not installed by default
    (`core.hooksPath` is the stock `.git/hooks`), now documented in the README.

- **`pyproject.toml`** — four defects, each breaking a clean install:
  - `requires-python` was `>=3.8`, two minor versions below the real floor. No
    module uses `from __future__ import annotations`, so every annotation is
    evaluated at import: PEP 604 `dict | None` in `sensor.py:46` needs 3.10;
    `dict[str, Any]` in `config.py:219` and `argparse.BooleanOptionalAction` in
    `__main__.py:17` need 3.9. pip installed happily on 3.8/3.9 and the app
    raised `TypeError` on first import. Raised to `>=3.10`. Swept for 3.11+/3.12+
    constructs (`tomllib`, `StrEnum`, `ExceptionGroup`, `except*`, `TaskGroup`,
    `typing.Self`, `typing.override`, `itertools.batched`, `datetime.UTC`, PEP
    695 generics) — none present, so 3.10 is correct, not merely safe.
  - `dearpygui` was an optional `[gui]` extra, but `gui.py:6` and `icons.py:3`
    import it at module scope and the `rev80` console script reaches both via
    `__main__:main`. `pip install -e .` — exactly what CLAUDE.md instructs —
    produced a `rev80` command that ImportErrors. Moved into required
    dependencies; `[gui]` kept as an empty alias.
  - `pandas` and `matplotlib` were declared runtime dependencies but imported
    nowhere under `src/`. `matplotlib` was already in the PyInstaller excludes,
    confirming it was never needed at runtime. Removed. (Both are still used by
    the standalone `examples/TMS_Digital_Audio.py` and
    `scripts/advanced_plots.py`, which sit outside the installed package.)
  - `numpy`, `scipy`, `h5py`, `pyyaml`, `plyer`, `pywin32` were entirely
    unconstrained, so a shipped installer's contents depended on what PyPI
    served that day. Added lower bounds (not pins) chosen as the oldest releases
    that support 3.10 and carry the APIs actually used.

- **`pyproject.toml` / CI reproducibility** — `[tool.ruff.lint]` set only
  `ignore`, never `select`, so ruff linted with whatever its *current default*
  happened to be — and that default moves between releases. On an identical
  tree: **ruff 0.15.10 → 0 errors, ruff 0.16.5 → 167 errors**, none from a code
  change. With `ruff` unbounded in `[dev]`, CI would have gone red on an
  untouched tree at the next ruff release. Fixed at both layers:
  `select = ["E4", "E7", "E9", "F"]` makes the rule set explicit, and
  `ruff>=0.15,<0.17` bounds the version. Both versions now report clean.

- **`gui.py`** — `_on_sb_save_config` called `h5py.File(...)` but `gui.py` never
  imported `h5py` at module scope; the three other users each did a
  function-local import and this one did not. The resulting `NameError` was
  caught by a broad `except Exception` and logged as
  `"failed to patch {session_h5}"`, so the session browser's **"Save Config"
  button was dead code** and the message pointed the user at disk permissions.
  Added the module-scope import, removed the three redundant local ones, and
  narrowed the `except` to `(OSError, KeyError)`.

- **`icons.py` / `gui.py`** — `test_gui_build` failed on any clone that had not
  run `scripts/build.sh`, with an opaque
  `SystemError: <built-in function pop_container_stack> returned a result with
  an exception set`. `assets/fonts/` is gitignored and populated by build.sh, so
  the font is absent on a fresh clone and on every CI runner; `icons.load()`
  passed the nonexistent path to `dpg.font()`, and the failure inside the
  context manager surfaced from `pop_container_stack` naming neither the font
  nor the path — taking down all of `_create_gui()`. Now checks for the file and
  falls back to the DPG default with a warning. *This was the pre-existing
  failure standing between the suite and green, and the blocker for CI.*

- **`picoscope.py`** — the PicoSDK *driver* (`libps4000a`) is a separate native
  install from the `picosdk` Python wrapper, and `picosdk/ps4000a.py`
  instantiates `Ps4000alib()` at import time, raising `CannotFindPicoSDKError`
  when the driver is absent. `picoscope.py` imported it unguarded, so
  `import rev80.picoscope` was fatal without the driver. Reproduced by stubbing
  `find_library`: the **whole suite aborts** with 3 collection errors, not
  3 modules' worth of skips — note `test_antialias.py` is pure DSP and was
  collateral damage. Also contradicted CLAUDE.md's claim of "offline development
  and CI without hardware". Now degrades to `PICOSDK_AVAILABLE = False`, mirroring
  the guard `__init__.py:9-17` already uses for this exact import;
  `FindPicoScope()` returns `[]` with a warning. Verified identical results with
  the driver present and absent.

- **`monitor/controller.py:258`** — read the sensor sensitivity under
  `sensitivity_mv_per_eu`, a key that exists nowhere in the codebase;
  `session.sensor_snapshot` holds `ScopeSensor.to_dict()` output, which emits
  `sensitivity`. The `1.0` default therefore **always** won: the mV→EU division
  never happened and every burst's pre-trigger trend points came out a factor of
  `sensitivity` too large (~10x for a 10.2 mV/g sensor) against the post-trigger
  points on the same continuous plot. `engineering_units` on the adjacent line
  used the correct key, so the unit *label* converted while the magnitude did
  not — worse than an obvious break. Now rehydrates through
  `ScopeSensor.from_dict()` once per call so the field name can only be wrong in
  one place; misleading comment at `:246` corrected.

- **`README.md:920` / `CLAUDE.md:127`** — documented the same wrong
  `sensitivity_mv_per_eu` key. Following the README raised `KeyError` in
  `from_dict`, and the very next README paragraph correctly said the code
  divides by `sensitivity` — the two lines contradicted each other. Both fixed.

- **Sensor library could be silently and permanently destroyed.**
  `ScopeSensorRegistry._load_user` swallowed any parse failure with
  `except Exception: return []`, and `_save_user` writes whatever `_load_user`
  returned straight back over the file. `add()` and `delete()` both follow that
  load-then-save path, so **one unreadable entry erased every calibrated sensor
  definition, with nothing logged.** Two independent triggers reached it: the
  wrong documented key above, and `config._atomic_yaml_write` using `yaml.dump`
  with the **unsafe default Dumper** while every reader uses `yaml.safe_load` —
  loading a colleague's `.h5` auto-registers its sensors with no prompt and no
  type coercion, so a non-scalar attribute serialised as a
  `!!python/object/apply:` tag that `safe_load` then refused. Fixed at all three
  layers:
  1. `config.py:159` → `yaml.safe_dump`; unrepresentable values now fail loudly
     at write time and the existing file survives. Also closes a latent
     escalation: a writer emitting object tags means any future switch to
     `yaml.load` becomes arbitrary code execution from a shared measurement
     file. *No RCE today.*
  2. `scope_sensor.py` → `from_dict` coerces every field and rejects containers
     and arbitrary objects, so junk cannot reach the writer.
  3. `scope_sensor_registry.py` → a bad *entry* is logged with file, index and
     content and skipped; a bad *file* raises, so a read failure can never
     become an overwrite. Read-only callers go through `all()`, which degrades
     to `[]` and logs, so a corrupt file cannot crash GUI construction.

- **`config.py` / `gui.py` / `headless.py`** — two monitor defaults the GUI could
  not represent and therefore silently rewrote:
  - `hook_type`: `config.py:83` seeds `'rms'` (lowercase); the GUI combo items
    are capitalised and both `_on_anom_config_change` and `_build_anomaly_hook`
    compared raw strings, while `headless.py:159` did `.lower()`. On a fresh
    install `'rms'` matched neither `('RMS','Both')` nor `('Spectral','Both')`:
    opening Config→Monitor once **hid both hook groups, built zero anomaly
    hooks, and silently disabled anomaly detection** behind an Enable switch
    that was on. Now canonical lowercase everywhere, capitalisation demoted to a
    display label.
  - `interval_s`: `config.py:74` seeds `600`, which was not a preset member, so
    the widget showed "1 h" and saving wrote `3600.0` back — **silently changing
    a 10-minute logging interval to hourly, discarding 5 of every 6
    measurements.** Fixed at both ends: `600` is now a preset, and the fallback
    picks the *nearest* preset rather than a hardcoded 3600.

- **`headless.py` / `gui.py`** — `_build_anomaly_hook` bound `period` only inside
  the `if hook_type in ("rms","both")` branch but read it in the spectral
  branch, so a **Spectral-only config raised `UnboundLocalError`**. In headless
  this fires *after* `collector.start_stream()`, killing the process with the
  PicoScope still streaming and never closed — the worst outcome for an
  unattended run. The two copies fail differently, which is why it survived:
  `gui.py` reads `period` unconditionally and always raises, while
  `headless.py`'s `if "spec_ewma_time" in anom_cfg and period > 0`
  short-circuits, so it only raises when that key is present — which is exactly
  what the GUI writes. Hoisted in both.

- **Reconciled the four ways the two `_build_anomaly_hook` copies had drifted:**
  hook-type casing (above); `warmup` default 30 (GUI) vs 10 (headless) → 10,
  matching `config.py`'s seed, since at 30 the GUI needed a 3x longer baseline
  warm-up during which nothing could fire; `spec_n` default 3 (GUI) vs 10
  (headless) → 10, since at 3 the GUI fired on a third of the evidence headless
  required; and the EWMA-alpha fallbacks, previously hardcoded separately in
  each copy, now `util.DEFAULT_RMS_ALPHA` / `DEFAULT_SPEC_ALPHA`.

- **`_pico_loader.py:24`** — computed `Path(__file__).parent.parent / 'drivers'`
  → `src/drivers`, which does not exist; `_paths.py:25` already gets this right
  with three `.parent`s. `ensure_pico_dlls_loadable()` silently returned `False`
  in development, bundled DLLs were never registered, and picosdk fell back to
  walking `%PATH%`. Frozen builds use the `sys._MEIPASS` branch and were
  unaffected. Now delegates to `_paths.resource_path('drivers')` — the
  duplication was the bug — and logs a warning on Windows when it returns False.

- **`collector.py:1187,1224`** — deprecated `datetime.utcnow()` replaced with
  `datetime.now(timezone.utc).replace(tzinfo=None)`, deliberately **naive** to
  match `utcnow()`'s exact semantics. See follow-ups.

- **`AMPLITUDE_SCALE.get()` fallback inconsistency** — called with two different
  defaults across five sites: `np.sqrt(2)` in the live path
  (`collector.py:231`, `:550`) and `1.0` in the reload path
  (`collector.py:992`, `:1147`, `monitor/controller.py:267`). An unrecognised
  mode reconstructed a loaded trend **1.414x off** relative to the live trend on
  the same plot. All five now call `util.amplitude_scale()`; the fallback is
  `'0-P'` because every call site already normalises with `or '0-P'` before the
  lookup. Unknown modes are logged. A test asserts no `AMPLITUDE_SCALE.get()`
  survives anywhere in `src/`.

- **`util.py`** — no `__all__`, so `rev80/__init__.py`'s
  `from rev80.util import *` re-exported `np` and every imported name into the
  top-level namespace. Added an explicit `__all__`. `data_dir` is listed
  deliberately: it is imported into `util` from `rev80._paths` and reached as
  `rev80.data_dir()` by six call sites in `gui.py`/`headless.py`, so omitting it
  would have broken them at runtime rather than at import.

- **18 ruff errors** cleared (unused imports/variables, one `E401`). The five
  unsafe `F841`s were handled by hand: `test_vibechecker.py:186`'s `old_sr` was
  kept and *asserted on* — `test_load_offline_adjusts_maxfreq` captured the
  pre-load samplerate but never compared against it, so the "adjusts" behaviour
  it is named for went unverified. No `noqa` added anywhere.

### Reverted

- **`.python-version`** — briefly changed to `3.13` on the premise that the
  literal `vibecheck` was a stale string. That premise was wrong: `vibecheck` is
  a real pyenv-virtualenv holding every project dependency, and naming a
  virtualenv there is correct pyenv-virtualenv usage. The change resolved to a
  bare interpreter with no packages and produced 15 collection errors. Reverted;
  the `pyproject.toml` changes from the same commit stand.

---

## Recommended follow-ups (not done on this branch)

1. **Lockfile with hashes.** Lower bounds narrow the window but do not make
   installer contents reproducible. A `uv.lock`/`pip-compile` output with hashes
   is the real fix.
2. **Extract a shared `monitor/factory.py`.** `_build_anomaly_hook` exists twice,
   copy-pasted, and had drifted four ways plus carried an identical
   `UnboundLocalError`. Deliberately not done here — it would collide with
   concurrent work and bloat this branch. The two copies are now reconciled and
   both are covered by parametrized tests, so the refactor is safe to do next.
3. **UTC/local timestamp inconsistency.** headless writes UTC while the GUI
   writes naive local time. The `utcnow()` fix above deliberately preserves
   existing meaning rather than picking a side. Resolving this properly needs a
   decision about already-stored files.
4. **Widen the ruff rule set.** `select` is pinned to ruff's historical defaults
   (`E4`, `E7`, `E9`, `F`) to make CI reproducible without a large cleanup.
   Adopting more rules (e.g. `I` for import sorting, `B`, `UP`) is now a
   deliberate, separately reviewable change — ruff 0.16.5 reports 167 findings
   under its current defaults.
5. **`test_gui_build` only builds the GUI.** It never renders a frame or
   exercises a callback. The session-browser Save Config bug lived behind a
   button no test pressed.
