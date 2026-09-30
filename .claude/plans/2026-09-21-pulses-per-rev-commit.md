# Plan — commit the pulses/rev work and the PROGRESS corrections

## Context

Three days of work sit uncommitted on `feature/tachometer` (fast-forwarded to
`main` at `97a7e54`, nothing unique on it before this). It is three unrelated
pieces of work that arrived in one working tree:

1. **Stale-entry fixes in `doc/PROGRESS.md`** — R29 described `samplerate` as
   power-of-two arithmetic, which `nextpow2`'s retirement made wrong, and R32's
   status still read "see working tree (not yet committed)" for work that
   shipped. Plus a new R48 recording the GitHub Actions CI/release automation,
   which had no requirement entry at all.
2. **Configurable `pulses_per_rev`, gated on whole revolutions** — the fixed
   `MIN_EDGES = 3` became `MIN_REVS = 2.0` + `min_edges_for(ppr)`, which is what
   makes a user-settable ppr safe. Verified offline (1120 tests), revert-checked,
   and closed out electrically on the 4424A (27 hardware tests). The GUI control
   was **tested by hand by the user** — that is what unblocked this commit.
3. **`doc/plans/headless-tach.md`** — the R44 survey. **Stays untracked** (user's
   call), so its PROGRESS link stays uncommitted with it.

The first two want to be separate commits: the reader of `git log` should be able
to see the measurement change on its own, without the CI bookkeeping mixed in.

The complication is that both touch `doc/PROGRESS.md`, in four places belonging
to two commits plus one that stays behind — and two of them (R43, R44) are
**adjacent lines**, so they land in one hunk even at `-U0` and cannot be
separated by hunk-level staging alone.

## Scope

Two commits, on `feature/tachometer`. **No push, no merge to `develop`/`main`,
no tag** — say what was committed and let the user decide those.

Left in the working tree afterwards, deliberately:

- `doc/plans/` — untracked.
- the **R44 line** of `doc/PROGRESS.md` — it links to that untracked plan file,
  so committing it would put a dangling reference in the repo.
- `scripts/tqcount.py` — untracked, pre-existing, not mine.

No test run. The suite and the hardware close-out already passed against this
exact tree, the user has hand-tested the GUI, and the only edits this plan makes
are the PROGRESS reconstruction below. `ruff` still runs, blocking, inside the
pre-commit hook.

## The two commits

### 1. `docs: correct two stale PROGRESS entries, and record the CI work as R48`

`doc/PROGRESS.md` — the R29, R32 and R48 lines only. Body covers: `nextpow2`
overstating the display rate by up to 2x; R32's filter being linear-phase
Kaiser, not zero-phase, and its real commits (`a7cc288` / `01b5832` / `568f712`);
and R48 noting that the `gh release create --draft` step is still unexercised
because it is tag-guarded.

### 2. `feat(tach): make pulses/rev configurable, gated on whole revolutions`

- `src/rev80/tach.py` — `MIN_REVS`, `min_edges_for()`, `slowest_rpm_for()`,
  `MIN_SAMPLES_PER_PULSE`; the gate in `estimate_rpm`; `from_dict` warning
  inverted; D-6 docstring section rewritten.
- `src/rev80/gui.py` — Pulses/rev control, floor via `slowest_rpm_for`,
  samples-per-pulse caution, pulse-vs-shaft period fix on the preview axis.
- `src/rev80/util.py` — `TACH_PPR`, `TACH_PPR_WARN` tags.
- `tests/test_tach.py`, `tests/test_tach_persistence.py`,
  `tests/test_picoscope_hw.py`.
- `CLAUDE.md`, `README.md`, `doc/CHANGELOG.md`, and the **R43 line only** of
  `doc/PROGRESS.md` — the project rule is that these move in the same change.

Body leads with why a fixed edge count was the wrong constraint (nine edges of a
6 ppr encoder is 1.5 turns and used to report a rate drawn from a fraction of a
revolution), the revert-check result (`rpm=1799.99…` where it wants `None`), the
two counter-intuitive consequences (a finer encoder does not read a slower
shaft; `MIN_SAMPLES_PER_PULSE`), and the AWG close-out.

## Staging `doc/PROGRESS.md` across the two commits

`git add -p` is interactive and unavailable, and `-U0` still yields one hunk for
R43+R44. So stage by reconstructing the file per commit:

1. Copy the current (final) `doc/PROGRESS.md` to the scratchpad as the target.
2. `git checkout HEAD -- doc/PROGRESS.md` to get back to the committed state.
3. Apply **only the R29, R32 and R48 changes**; stage and make commit 1.
4. Apply **only the R43 change**; stage with the rest of commit 2's files and
   commit.
5. Apply the **R44 change** last and leave it unstaged.

Each change is a single whole-line replacement (R29, R32, R43, R44) or a
single-line insertion (R48), so a `python3` exact-string replace per line is
enough, and it fails loudly if the anchor text has drifted. Take the replacement
text from the saved target copy, not from memory.

## The pre-commit hook

`core.hooksPath` is set to `.githooks` in this clone, so the hook runs. It:

- runs `ruff check src/ tests/` (blocking) — currently passing;
- re-renders `doc/*.pdf` for any of `README.md`, `CONTRIBUTING.md`,
  `doc/PROGRESS.md`, `doc/CHANGELOG.md` that is staged, and **`git add`s the
  PDF into the same commit**.

`pandoc` and `weasyprint` are both present, so this will happen rather than warn
and skip. `doc/PROGRESS.pdf` will be regenerated in both commits, each matching
that commit's Markdown — the hook working as intended, not churn to avoid. Do
not pass `--no-verify`.

Note the PDF will be regenerated a third time, unstaged, once the R44 line goes
back in at step 5. Leave that dirty PDF in the working tree alongside the R44
line it belongs to, or restore it from HEAD — it is not part of either commit.

## Attribution

Both commits: `--author="Claude AI <claude@anthropic.com>"` (per the global
CLAUDE.md, and matching `e419f5c` and the other recent Claude commits), and the
message ends with:

```
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

## Verification

1. `git log --stat -2` — each commit carries the files listed above and nothing
   else, and each picked up its regenerated PDF.
2. `git diff HEAD -- doc/PROGRESS.md` shows **exactly one changed line**, the
   R44 entry. If it shows more, or none, stop — the reconstruction went wrong
   and a fixup commit is the wrong repair.
3. `doc/PROGRESS.md` is byte-identical to the saved target copy.
4. `git status --short` shows only the R44 line's file, the unstaged
   `doc/PROGRESS.pdf` (if not restored), `?? doc/plans/` and
   `?? scripts/tqcount.py`.

Not re-verified: the GUI widget, which has no automated coverage. The user tested
it by hand, which is the evidence this commit rests on.
