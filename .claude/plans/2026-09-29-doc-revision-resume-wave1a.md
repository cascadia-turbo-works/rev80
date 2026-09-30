# Resume wave 1a of the documentation revision

## Context

The 10 wave-1a agents stopped. Nine agents reached the session limit (HTTP 429). W1-AG stopped because the permission check gave no verdict. No agent made a commit. All worktrees are at `8bd106c` on `doc/revision`.

Worktrees that have partial work (not committed):

| Package | Worktree | Changes |
|---|---|---|
| W1-C2 | `agent-a8a3f7deebc9cfe22` | `collector.py`, `_dsp.py` (+67/−194). No staging file |
| W1-C4 | `agent-aa7843b9cffa0a5c8` | `peaks.py` (+29/−174). No staging file |
| W1-T1 | `agent-afc43b91cb128f3ba` | `test_measurement_validity.py` (+48/−131) |
| FIX-S | `agent-af5e94ff89dd0cab1` | `controller.py`, `gui.py`, new `tests/test_manual_burst_alignment.py` |

The other six worktrees have no changes: W1-AUD, W1-C1, W1-C3, W1-RM, W1-CT and W1-AG.

Owner decision: run a maximum of **3 agents at the same time**.

## Method

Resume each agent with `SendMessage` to its agent ID. The agent keeps its transcript and its worktree. Each resume message says:
- "You stopped at the session limit. Continue your package in the same worktree. Do not start again."
- First run `git status` and `git diff --stat`, and then continue from that state.
- For C2 and C4: the evidence that you removed is not yet in a staging file. Before you continue, get the removed text from `git diff` (or `git show 8bd106c:<file>`). Write it to `doc/_staging/evidence-Cn.md`.

Before each merge, reject the package if `git diff --stat` shows a file that the package does not own (plan 12.5 and 14.1). Merge with `git merge --no-ff` into `doc/revision`. After each merge, run `ruff check src/ tests/`. Remove the worktree after the merge.

W1-AG: resume it. If the permission check fails again, I apply the edits myself. The agent's report gives them in full.

## Batches (3 at a time)

| Batch | Packages | Reason |
|---|---|---|
| 1 | FIX-S, W1-AUD, W1-C2 | FIX-S and AUD gate wave 1b. C2 has partial work |
| 2 | W1-C4, W1-T1, W1-C1 | C4 and T1 have partial work |
| 3 | W1-C3, W1-RM, W1-CT | |
| 4 | W1-AG | Small. It can run in the gap when a batch-3 agent finishes |

Start the next package when a slot is free. Do not wait for a full batch to finish.

Wave 1b (W1-C5, W1-C6, W1-T2, W1-PR) starts when FIX-S and W1-AUD are merged. These packages also use the 3-agent limit, so they share slots with batches 3 and 4. Priority order in the queue after batch 1: C4, T1, C1, C5, C6, C3, RM, CT, PR, T2, AG.

For new agents (wave 1b), use the same brief form as wave 1a. Add this step: "After worktree creation, if HEAD is not the current `doc/revision` tip, run `git merge --ff-only doc/revision`." (In wave 1a, the worktrees started at `f4e78fb`, and the agents had to fast-forward.)

## Questions for the owner

Send each question that an agent reports to the owner, one at a time, with a summary. W1-AG already reports one question: can the "standing assumption" examples in the writer prompt keep their fixed-bug history? They are agent context, not reference documents (plan risk R-12).

## Verification

- For each package: the checks in its brief (plan 12.6), and pytest with `--ignore=tests/test_picoscope_hw.py`. I run ruff again after each merge.
- FIX-S: the revert-check results in its report. After the merge, I run `python -m pytest tests/test_manual_burst_alignment.py` and the new GUI gate test on `doc/revision`.
- After all of wave 1: `git log --oneline 8bd106c..doc/revision` shows one commit for each package (two for FIX-S). Then wave 2 starts (plan 12.4).
