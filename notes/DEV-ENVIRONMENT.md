# Dev Environment — Nix + direnv + venv

How the local development environment is provisioned and why it's built this way.
The goal: `cd` into the repo and have the exact Python toolchain ready, with zero
manual steps, reproducibly, and **without drifting from CI**.

## TL;DR

```bash
cd ~/Desktop/OpenEnglish     # direnv auto-loads the env (first time: run `direnv allow`)
which python3                # -> .../OpenEnglish/.venv/bin/python3  (Python 3.12.15)
just test                    # run the suite — just works
```

`cd` out and the environment unloads itself.

## The model: Nix gives the interpreter, pip gives the packages

This is a **hybrid** setup, split on purpose:

- **Nix** provides *only* the Python **interpreter** (3.12, matching CI), pinned via
  `flake.lock`. This is the one piece that's otherwise fiddly to get identical across
  machines.
- **pip + `requirements.txt`** provide the Python **packages**, inside a project-local
  `.venv`. These stay byte-identical to what CI installs (`pip install -r requirements.txt`),
  so there is **no gate/CI parity risk**.
- **direnv** glues it together: on `cd`, it loads the Nix toolchain, creates/activates the
  venv, installs deps when they change, and exports the finished environment into your shell.

```
cd into repo
   │
   ▼
direnv reads .envrc  (in BASH)
   │   1. eval "$(nix print-dev-env)"   → Nix Python 3.12 on PATH (from flake.nix/flake.lock)
   │   2. create .venv (if missing) using that Python; activate it
   │   3. pip install -r requirements.txt  (only when requirements.txt changed)
   ▼
direnv exports the resulting env into your zsh
   │
   ▼
python3 / pytest / ruff resolve to .venv  (Python 3.12.15)
```

## Files involved

| File | Role | Committed? |
|------|------|-----------|
| `flake.nix` | Declares a Nix devShell whose only package is `python312`. Multi-system (darwin/linux). | staged, not yet committed |
| `flake.lock` | Pins `nixpkgs` to an exact revision (2026-10-08) → reproducible interpreter. | not yet committed |
| `.envrc` | The direnv script: load flake env → create/activate `.venv` → pip-install on change. | not ignored (commit when ready) |
| `.gitignore` | Ignores `.venv/` and `.direnv/` (build artifacts, never committed). | existing |
| `requirements.txt` | The actual Python dependency pins (shared with CI). | existing |

> `flake.nix`/`flake.lock` are currently **staged but not committed** by request. Nix reads
> them from the working tree regardless — that's the source of the harmless
> `warning: Git tree ... has uncommitted changes` on each load. It disappears once committed.

## How `.envrc` works, line by line

```bash
watch_file flake.nix flake.lock requirements.txt   # reload env automatically if any change
eval "$(nix print-dev-env)"                         # Nix Python 3.12 onto PATH

if [ ! -d .venv ]; then                             # first run only
  python3 -m venv .venv                             # venv built FROM the Nix 3.12 interpreter
fi
source .venv/bin/activate                           # venv python/pip take precedence

if [ requirements.txt -nt .venv/.deps-installed ]; then   # deps stale?
  python3 -m pip install --quiet --upgrade pip
  python3 -m pip install --quiet -r requirements.txt
  touch .venv/.deps-installed                        # marker: deps match current requirements
fi
```

The `.venv/.deps-installed` marker means pip only runs when `requirements.txt` is newer than
the last install — so routine `cd`s are instant, but editing `requirements.txt` triggers a
reinstall on the next load.

## Key choices (and the alternatives rejected)

**1. Flake + `flake.lock`, not an unpinned `shell.nix`.**
A locked flake pins the exact nixpkgs revision, so the interpreter is identical on any
machine — the strongest "reproducible in <15 min for a new dev" story. Cost: flakes must be
enabled (they are, via Determinate Nix) and files must be git-tracked for Nix to read them.

**2. Hybrid venv/pip, not pure `python3.withPackages`.**
A pure-Nix Python environment would be fully reproducible but would pull dependency versions
from nixpkgs, which **drift from `requirements.txt` and from CI** (CI runs
`pip install -r requirements.txt`). Keeping packages in a pip venv guarantees the local env
matches CI exactly. We accept that packages come from PyPI (they're pinned) rather than Nix.

**3. direnv loads the env — we do *not* `eval "$(nix print-dev-env)"` by hand in zsh.**
`nix print-dev-env` emits a **bash** script. Run directly in an interactive **zsh** it fails
to apply: you get `zsh: read-only variable: LINENO` and `PATH` silently doesn't update
(`which python3` stays `/usr/bin/python3`). direnv runs `.envrc` in **bash**, computes the
environment, and exports only the diff into zsh — so it applies cleanly with no warning.
This incompatibility is *the* reason the setup goes through direnv.

**4. Python 3.12, not 3.11.**
The project floor is 3.11 (`pyproject.toml`), but CI pins 3.12 (`.github/workflows/ci.yml`).
Dev matches CI → 3.12.

**5. nix-direnv is optional and deferred.**
`use flake` (with caching) comes from nix-direnv, which requires sourcing its `direnvrc`
globally — a system/home-config change the user manages declaratively in their own Nix
config. To avoid touching anything outside the repo, `.envrc` uses the plain
`eval "$(nix print-dev-env)"` form, which works with stock direnv. When nix-direnv is added
to the Nix config, swap the two `watch_file`+`eval` lines for a single `use flake` to gain
caching — no other change needed.

## First-time vs. daily use

- **First time:** `direnv allow` once (authorizes `.envrc`). The initial load downloads the
  Nix Python from the binary cache and builds `.venv` + installs deps (tens of seconds).
- **Daily:** just `cd` in. Env loads from cache instantly; pip only re-runs if
  `requirements.txt` changed. `cd` out → env unloads.
- **Per-PR work:** `git checkout <branch>` then let direnv reload; if that branch changes
  `requirements.txt`, deps refresh automatically.

## Relationship to CI

`.github/workflows/ci.yml` does `pip install -r requirements.txt` on Python 3.12, then
`ruff check .` + `pytest -q`. The local env reproduces that same interpreter + same packages,
so "passes locally" and "passes CI" stay in sync. (CI itself does not use Nix/direnv — those
are a local developer-experience layer only.)

## Troubleshooting

- **`warning: Git tree ... has uncommitted changes`** — expected until `flake.nix`/`flake.lock`
  are committed. Harmless.
- **`zsh: read-only variable: LINENO`** — only appears if you run `eval "$(nix print-dev-env)"`
  *by hand* in zsh. Don't; let direnv load the env.
- **`which python3` shows `/usr/bin/python3`** — direnv isn't active in that shell. Run
  `direnv allow` / `direnv reload`, and confirm the direnv hook is in your shell rc.
- **Wrong Python in `.venv`** (e.g. rebuilt it with system python) — `rm -rf .venv` and
  `direnv reload`; it rebuilds from the Nix 3.12 interpreter.
- **Deps not refreshing after editing `requirements.txt`** — `rm .venv/.deps-installed` and
  reload, or `pip install -r requirements.txt` inside the active env.
