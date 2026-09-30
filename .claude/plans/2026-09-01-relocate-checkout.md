# Relocating the rev80 checkout: what breaks, and making it move-proof

## Context

The repo is about to move on disk. It has moved twice already —
`/home/hgg/CODE/reveng/vibegui` → `/home/hgg/Documents/reveng/code/vibegui` →
`/home/hgg/Documents/reveng/vibration/rev80` — and **neither previous move was cleaned up**.
Three pieces of machinery are broken *right now* because they still point at the dead
`.../reveng/code/vibegui` path, and one points at a path from two moves ago
(`/home/hgg/PurpleDocs/...`). None of them fail loudly, which is why they went unnoticed.

So this isn't "what will the move break" — it's "the move already broke these; fix them in a
way that survives the next move too."

### Broken now (verified this session)

| What | Current value | Effect |
|---|---|---|
| `core.hooksPath` (`.git/config`) | `/home/hgg/Documents/reveng/code/vibegui/.git/hooks` — **does not exist** | Git silently runs **no hooks**. The blocking `ruff check src/ tests/` gate and the `doc/*.pdf` re-render in `.githooks/pre-commit` have not run since the last move. |
| `gitflow.path.hooks` | `/home/hgg/PurpleDocs/reveng/code/vibegui/.git/hooks` | Dead; stale from the move before last. |
| Editable install `.pth` | `.../vibecheck/lib/python3.13/site-packages/__editable__.rev80-0.1.0.pth` → `/home/hgg/Documents/reveng/code/vibegui/src` | `import rev80` fails. Verified: `rev80 --help` → `ModuleNotFoundError: No module named 'rev80'`. So the `rev80` / `rev80-headless` console scripts **and the desktop launcher** are all dead. |
| Stale `vibechecker` dist | `__editable__.vibechecker-0.1.0.pth` + `__editable___vibechecker_0_1_0_finder.py`, mapping `vibechecker` → the dead vibegui dir | A separate distribution from the pre-rename era. `pip install -e .` will **not** remove it. |
| `.vscode/launch.json` | `"module": "vibechecker"` | Stale from the package rename — **already deleted** in the working tree; superseded by the `.gitignore` change below. |

### In-flight manual cleanup (uncommitted, this session)

`.vscode/*` and two stale `doc/*.pdf` are staged as deleted, and `.gitignore` gained
`.ruff_cache/`, `.python-version`, `.vscode` so each checkout owns its own dev environment.

**One gap:** `.python-version` is **still tracked**, and a `.gitignore` entry has no effect on a
tracked file — `git check-ignore -v` matches `.ruff_cache` and `.vscode` but *not* `.python-version`.
It needs `git rm --cached .python-version` to actually become per-instance.

That change reorders the move: once `.python-version` is untracked, **pyenv no longer auto-selects
`vibecheck` in the moved checkout**, so a bare `pip install -e .` there would install into the global
`3.13.2` instead. Select the env first (step 3).

### Not affected by a move (verified — do not touch)

- **Tests.** `pyproject.toml` sets `pythonpath = ["src"]`, resolved from rootdir. 737 tests collect
  cleanly right now *despite* the broken editable install. Tests never exercise the installed package.
- **Repo contents.** `grep -rI "/home/hgg" .` over the whole tree returns nothing — no absolute paths
  are committed anywhere in `src/`, `tests/`, `scripts/`, `build/`, or `installer/`.
- `.python-version` (`vibecheck`) travels with the repo, so pyenv keeps resolving the same env.
- `~/.config/rev80/`, `~/Documents/Rev80/data/`, `~/.local/share/applications/rev80.desktop`
  (its `Exec=` points at the env's `bin/rev80`, not the repo), the icon, git remotes,
  setuptools_scm (git-based), and the ruff/pytest caches (no absolute paths inside).
- `.claude/settings.local.json` and `.claude/agents/vibration-engineer.md` — in-repo, they travel.
- `~/.claude/settings.json`, shell rc files, and `~/.claude/plans/` contain no references to this path.

### Claude Code impact — the path is the identity key

Claude Code keys per-project state on the **absolute cwd**, so a move silently starts a new project:

- `~/.claude/projects/<path-slug>/` holds session transcripts **and the memory directory**.
  The old slug `-home-hgg-Documents-reveng-code-vibegui` still holds **21 sessions**; the current
  `-home-hgg-Documents-reveng-vibration-rev80` has only 2. `--resume` / `--continue` will not see
  history from before a move. The memory dir at the current slug is empty today, so nothing is at
  risk this time — but anything written there before the move must be carried over.
- `~/.claude.json` → `projects` is keyed by absolute path and stores `hasTrustDialogAccepted`,
  `allowedTools`, MCP servers, and usage history. There are already **three** entries for this
  project, one per historical path. After the move: trust dialog again, fresh entry.
- The in-repo `.claude/` directory is the part that *does* follow the checkout — permissions in
  `.claude/settings.local.json` and the `vibration-engineer` agent keep working.

Net: nothing in Claude's behaviour degrades, but session history and the `~/.claude.json` entry are
left behind unless explicitly carried.

---

## Answering the question raised mid-plan

`pip uninstall . && pip install -e .` is the right instinct and fixes the largest single breakage,
but as written it is wrong in two ways:

1. `pip uninstall` takes **distribution names**, not a directory — `.` is not a valid target.
2. Even if it were, it would only address `rev80`. The stale **`vibechecker`** dist is a separate
   distribution whose finder `.pth` maps to the dead path; a `rev80` reinstall leaves it in place.

Correct form: `pip uninstall -y rev80 vibechecker` then `pip install -e .` from the new location.

---

## Plan

### 1. Move the checkout

Plain `mv`. Nothing inside the repo needs editing.

Use `mv`, not a fresh `git clone` — `.claude/settings.local.json`, `.python-version` (once untracked),
`log/`, and `DEVDATA/` are all untracked-but-wanted and only survive a move, not a clone.

### 2. Carry the Claude state to the new path key

**Do this with no Claude Code session running against either path.** `~/.claude.json` is rewritten in
full on session exit, so a live session will clobber a hand-edited file.

The new project slug is the new absolute path with every `/` replaced by `-`, including the leading
one (e.g. `/home/hgg/Documents/rev80` → `-home-hgg-Documents-rev80`).

```bash
OLD=/home/hgg/Documents/reveng/vibration/rev80
NEW=<new-absolute-path>
OLDSLUG=-home-hgg-Documents-reveng-vibration-rev80
NEWSLUG=$(printf '%s' "$NEW" | tr '/' '-')

# a) transcripts + memory dir
mv ~/.claude/projects/"$OLDSLUG" ~/.claude/projects/"$NEWSLUG"

# b) ~/.claude.json projects entry (trust dialog, allowedTools, MCP servers, history)
cp ~/.claude.json ~/.claude.json.bak            # this file is easy to corrupt; keep the backup
python3 - "$OLD" "$NEW" <<'EOF'
import json, sys
old, new = sys.argv[1], sys.argv[2]
p = "/home/hgg/.claude.json"
d = json.load(open(p))
projects = d.get("projects", {})
if old in projects:
    projects[new] = projects.pop(old)
    json.dump(d, open(p, "w"), indent=2)
    print("moved", old, "->", new)
else:
    print("no entry for", old, "- nothing to carry")
EOF
```

Carrying (b) preserves `hasTrustDialogAccepted: true`, so there's no trust prompt at the new path.
The current entry's `memory/` dir is empty, so (a) is purely about `--resume` history — but do it in
the same pass so the empty dir doesn't get recreated and diverge.

Optionally also fold in the **21 stranded sessions** at `-home-hgg-Documents-reveng-code-vibegui`
(and the two dead `~/.claude.json` keys, `/home/hgg/CODE/reveng/vibegui` and
`/home/hgg/Documents/reveng/code/vibegui`) — move the transcript `.jsonl` files into the new slug dir
and delete the dead keys. This is cleanup, not required for the move to work.

### 3. Re-point the environment (from the new location)

```bash
cd <new-path>
pyenv local vibecheck                   # REQUIRED once .python-version is untracked
python -c "import sys; print(sys.prefix)"   # confirm .../envs/vibecheck before installing
pip uninstall rev80 vibechecker         # drops both stale editable .pth/finder files
pip install -e ".[dev,gui]"             # rewrites the .pth to the new src/
```

Both dists really are present in the `vibecheck` env and both must go — `rev80-0.1.0.dist-info`
and `vibechecker-0.1.0.dist-info`, each with its own editable `.pth` pointing at the dead path.
(`gui` is an empty alias since dearpygui moved into the required dependencies — `pyproject.toml:43`
— so it is harmless but adds nothing; `dev` is the extra that matters.)

This also re-stamps `src/rev80/_version.py` via setuptools_scm and fixes the desktop launcher
(`Exec=` already points at the env's `bin/rev80`, which the reinstall makes importable again).

### 4. Make git hooks path-independent — the fix that prevents a repeat

```bash
git config core.hooksPath .githooks     # relative; survives any future move
git config --unset gitflow.path.hooks   # dead path from two moves ago
```

`.githooks/pre-commit` is in-repo and already correct; only the pointer was absolute.
This matches what `CONTRIBUTING.md:35` already documents — the config had simply drifted.

### 5. Finish the per-instance dev-environment change

```bash
git rm --cached .python-version         # makes the new .gitignore entry actually take effect
```

Then commit the in-flight cleanup together: `.gitignore`, the `.vscode/` deletions, the two stale
`doc/*.pdf` deletions, and this untracking.

Add a short "Moving the checkout" note to `CONTRIBUTING.md` covering steps 3–4 and the
`pyenv local` requirement — this is the third relocation, and each one has cost the same debugging.

## Verification

```bash
cd <new-path>
rev80 --list-sensors                    # must not raise ModuleNotFoundError (fails today)
python -m rev80 --help                  # same, via module entry
pytest tests/ -q                        # 737 tests, unchanged before and after
ruff check src/ tests/                  # what the hook gates on

git config core.hooksPath               # expect: .githooks  (relative)
touch README.md && git add README.md && git commit -m "test"   # hook must fire ruff; then reset
git config --get gitflow.path.hooks     # expect: no output
```

Then confirm the desktop entry launches (`Exec=.../envs/vibecheck/bin/rev80`).

Claude state carried correctly:

```bash
python3 -c "import json;d=json.load(open('/home/hgg/.claude.json'));\
print([k for k in d['projects'] if 'rev80' in k or 'vibegui' in k])"
ls ~/.claude/projects/ | grep -i rev80        # new slug present, old slug gone
```

Then start Claude from the new path: **no trust dialog** (proves the `~/.claude.json` entry carried)
and `--resume` lists the prior sessions (proves the transcript dir carried).
