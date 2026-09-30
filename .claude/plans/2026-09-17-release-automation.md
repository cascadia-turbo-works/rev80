# Release automation: tag → Windows installer + wheel

## Context

Rev80 is built by hand today: boot into Windows, pull, run `scripts/build.sh`.
`CONTRIBUTING.md:253` says so explicitly — *"No CI/dedicated build server … There's
no GitHub Actions workflow for it."* With the move to a GitHub remote
(`https://github.com/cascadia-turbo-works/rev80`) that manual step can go away.

The goal: **pushing a `vX.Y.Z` tag produces a draft GitHub Release carrying the
Windows installer and the Python wheel**, ready to review and publish.

Decisions taken (from the clarifying round):

| Question | Answer |
|---|---|
| PicoSDK DLLs in CI | Ship driver-less; users install PicoSDK separately |
| Release output | Draft GitHub Release, published manually |
| Tag must be on `main`? | No — build any `v*` tag |
| Wheel destination | Release asset only, not PyPI |

Two things make this easy, and one makes it interesting:

- A working CI workflow already exists (`.github/workflows/ci.yml`) and encodes the
  hard-won runner knowledge (`fetch-depth: 0`, `libx11-6`, driver-less `picosdk`).
  It has simply never run, because the only remote is self-hosted `catherby`.
- `scripts/build.sh` already has step selectors and `find_iscc()` already probes
  `C:\Program Files (x86)\Inno Setup 6\iscc.exe` — exactly where Chocolatey puts it.
- The interesting part: **GitHub's hosted Windows runners have no PicoSDK**, and
  `build/collect_pico_dlls.py` calls `sys.exit()` when it can't find the DLLs. That
  step has to become skippable.

---

## What you need to know before trying it

These are the GitHub Actions facts that actually bite on this repo:

1. **A tag trigger fires wherever the tag points.** `on: push: tags: ['v*']` has no
   concept of "on main". You chose to accept that — any `v*` tag builds.
2. **`fetch-depth: 0` is mandatory.** `setuptools_scm` derives the version from
   `git describe`. The default shallow checkout has no tags, so the version silently
   becomes `0.0.0+unknown` and you ship `Rev80Setup-0.0.0+unknown.exe`. The existing
   `ci.yml` already documents this.
3. **The build must leave the tree clean.** `_version.py`, `installer/version.iss`,
   `drivers/*.dll` and the fetched font are all gitignored, so `setuptools_scm` still
   reports a bare `0.1.0` rather than appending a `+d<date>` dirty suffix. Do not
   commit any of them.
4. **Inno Setup is not preinstalled** on `windows-latest`; Chocolatey provides it.
5. **The existing `ci.yml` uses a bare `push:`, which already includes tags** — so
   without a change, tagging runs both workflows. Worth narrowing.
6. **The exe and installer are unsigned.** Automation doesn't change that; users will
   still see a SmartScreen warning. Out of scope here, but it's why a *draft* release
   is the right default.

---

## Changes

### 1. `scripts/build.sh` — make it CI-drivable

Keep it the single source of truth for how a build happens; teach it two things so CI
and your Windows box run the *same* script.

- **Add a `nodlls` flag**, parsed exactly like the existing `clean` flag (the `for arg
  in "$@"` loop at lines 27–29). When set, skip step 3 (`collect_pico_dlls.py`). This
  is the one change CI strictly needs — everything else in the script already works on
  a runner, including `cygpath` and `taskkill` (Git Bash ships on `windows-latest`,
  and `taskkill` is already `|| true`-guarded).
- **Add a `wheel` step target** running `python -m build`, so `dist/*.whl` and
  `dist/*.tar.gz` are producible locally too, not only in CI. Note it coexists with
  PyInstaller's `dist/rev80/` — step 4's `rm -rf dist/rev80` is already narrow enough.
- Update the header comment block: document `nodlls`, and state that a driver-less
  build is what CI produces.

Leave `find_iscc()`, the font fetch and the version refresh alone — they already work.

### 2. `.github/workflows/release.yml` — new

Trigger and permissions:

```yaml
on:
  push:
    tags: ['v*']
permissions:
  contents: write        # required for `gh release create`
```

Four jobs. Use the `gh` CLI for the release rather than a third-party action — it is
preinstalled and keeps the supply chain to actions GitHub itself publishes.

- **`test`** — gate. `ubuntu-latest`, single Python (3.12), mirroring `ci.yml`'s steps:
  `fetch-depth: 0`, `libx11-6`, `pip install -e ".[dev]"`, `ruff check src/ tests/`,
  `pytest tests/ -q`. Cheap insurance that a tag can't cut a release from a red tree.
- **`wheel`** — `needs: test`, `ubuntu-latest`. `fetch-depth: 0` → `setup-python` →
  `./scripts/fetch_font.sh` (so the wheel actually carries the font declared in
  `[tool.setuptools.package-data]`) → `pip install build` → `python -m build` →
  `actions/upload-artifact` on `dist/*`.
- **`installer`** — `needs: test`, `windows-latest`, `defaults: run: shell: bash`.
  `fetch-depth: 0` → `setup-python` (pin **3.12**, x64) → `choco install innosetup
  --no-progress -y` → `pip install -e ".[dev]"` (brings PyInstaller) →
  `./scripts/build.sh all nodlls` → upload `installer/Output/Rev80Setup-*.exe`.
- **`release`** — `needs: [wheel, installer]`, `ubuntu-latest`.
  `actions/download-artifact` → `gh release create "$GITHUB_REF_NAME" --draft
  --generate-notes --title "$GITHUB_REF_NAME" <files>`.

Note the Python pinned in the `installer` job **is the interpreter shipped to users**
inside the frozen bundle. 3.12 is the conservative pick for PyInstaller; changing it is
a deliberate decision, so say so in a comment.

### 3. `.github/workflows/ci.yml` — one-line narrowing

Change the bare `push:` to `push: branches: ['**']` so tag pushes run only the release
workflow (which carries its own test gate). Prevents a duplicate 4-job matrix on every
tag.

### 4. Docs — same change, per the repo's own rule

- `CONTRIBUTING.md:253` — replace "No CI/dedicated build server … There's no GitHub
  Actions workflow for it" with the tag → draft-release flow, and state plainly that
  **CI installers are driver-less**: users install PicoSDK themselves. Your local
  `./scripts/build.sh` still bundles the DLLs.
- `CLAUDE.md:47` — **stale and wrong today**, independent of this work: it says the
  pre-commit hook *"stamps `src/rev80/_version.py` from `git describe`"*. It does not;
  `.githooks/pre-commit` has an explicit comment retiring that, and `setuptools_scm`
  generates the file at install/build time. Fix while here, since the release
  workflow's correctness depends on the real mechanism.
- `doc/CHANGELOG.md` — note the added release automation.

---

## Files

| File | Change |
|---|---|
| `.github/workflows/release.yml` | new — the four jobs above |
| `.github/workflows/ci.yml` | narrow `push:` to branches only |
| `scripts/build.sh` | `nodlls` flag; `wheel` target; header comment |
| `CONTRIBUTING.md` | replace the "no CI" section |
| `CLAUDE.md` | fix the stale version-stamping claim (line ~47) |
| `doc/CHANGELOG.md` | changelog entry |

Not touched: `build/rev80.spec` and `build/collect_pico_dlls.py` already degrade
correctly. The spec bundles `drivers/` whether or not it holds DLLs, and
`_pico_loader.ensure_pico_dlls_loadable()` logs a warning and returns `False` rather
than raising.

---

## Verification

**Before pushing anything**, locally (Linux, proves the `nodlls` path and the wheel):

```bash
./scripts/build.sh wheel          # dist/rev80-*.whl exists, version is not 0.0.0+unknown
git status --porcelain            # must be empty — a dirty tree corrupts the version
```

**Remote setup** (one-time, and the point of no return for the first CI run):

```bash
git remote add github git@github.com:cascadia-turbo-works/rev80.git
git push github main develop
git push github --tags            # NOTE: this pushes v0.1.0 and will trigger a release run
```

Push branches first and confirm `ci.yml` goes green before pushing tags, so the first
release run isn't debugging two things at once.

**End-to-end test of the release path** — use a throwaway tag, not a real version:

```bash
git tag v0.0.1-citest
git push github v0.0.1-citest
```

Then check:
1. `release.yml` runs; `test` passes and gates the two build jobs.
2. The `installer` job's log shows `Building version 0.0.1...` — **not** `0.0.0+unknown`.
   That single line is the main thing that can silently go wrong.
3. A draft release appears with `Rev80Setup-0.0.1*.exe` and `rev80-0.0.1*.whl` attached.
4. Download the installer, run it on a Windows machine, confirm it installs and Rev80
   launches. It will warn that PicoSDK is missing if the machine has no SDK — that is
   the expected driver-less behaviour, not a failure.

Clean up: delete the draft release and the tag (`git push github :v0.0.1-citest`).

**Full confidence** requires the usual close-out: with the 4424A attached, run
`pytest tests/test_picoscope_hw.py` against a CI-built installer to confirm a
driver-less bundle still drives real hardware when PicoSDK is present on the machine.
