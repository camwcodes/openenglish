# student-progress

Open English LMS service that tracks students' lesson progress.
**Some students are minors** — read `TEAM-STANDARDS.md` before making any changes.

> **Assessment deliverables** live in [`deliverables/`](deliverables/):
> [`EVAL.md`](deliverables/EVAL.md) (answer key + results),
> [`DECISIONS.md`](deliverables/DECISIONS.md) (ADRs),
> [`AI-USAGE.md`](deliverables/AI-USAGE.md) (prompts + corrections),
> [`REVIEW-NOTES.md`](deliverables/REVIEW-NOTES.md) (recommendations beyond the scanner),
> [`RUN-LOG.md`](deliverables/RUN-LOG.md) (verbatim keyed gate runs over all 8 PRs).
> The gate itself is described below; working notes are in [`notes/`](notes/), the brief
> in [`assignment/`](assignment/).

## Running locally

Pick one of the two setups below, then use the common commands. Requires **Python 3.11+**
(CI uses 3.12).

### Option A — Nix + direnv (recommended, reproducible)

With [Nix](https://determinate.systems/nix) (flakes enabled) and
[direnv](https://direnv.net/) installed, the toolchain provisions itself:

```bash
direnv allow          # first time only; authorizes .envrc
```

On entering the directory, direnv loads a pinned Python 3.12 (via `flake.nix`/`flake.lock`),
creates `.venv`, and installs `requirements.txt` + `requirements-dev.txt`. Leaving the
directory unloads it.
See `notes/DEV-ENVIRONMENT.md` for how it works and troubleshooting.

> Optional: `use flake` with caching needs [nix-direnv](https://github.com/nix-community/nix-direnv)
> sourced in your direnv config. The `.envrc` here works without it.

### Option B — plain venv + pip (no Nix)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Common commands

With the dev environment active (Option A), use the [`just`](justfile) recipes:

```bash
just            # list all recipes
just serve      # run the API at http://127.0.0.1:8000 (interactive docs at /docs)
just test       # run the tests
just check      # lint + tests (the CI gates)
```

Not using Nix? `just` isn't provided by Option B — either install it, or run the underlying
commands directly (they're spelled out in the `justfile`), e.g. `uvicorn app.main:app --reload`
and `pytest`.

## AI Quality Gate (reviewing the open PRs)

The repo also contains the **AI Quality Gate** — review of each PR branch against
[`TEAM-STANDARDS.md`](TEAM-STANDARDS.md). It is deliberately split in two:

1. **Standard hygiene = standard tools**, one `just` recipe each, run one at a time in
   CI ([`checks.yml`](.github/workflows/checks.yml)) — nothing custom:
   - `just lint` — ruff
   - `just coverage` — pytest-cov + [diff-cover](https://github.com/Bachmann1234/diff_cover)
     on the current checkout (§2; fails under 100% diff coverage by default)
   - `just secrets <branch>` — [gitleaks](https://github.com/gitleaks/gitleaks) over the
     branch's commits (§5; hit = job fails = blocked)
   - `just todos` — ruff's `TD003` (TODO without issue link, §1; S3 → non-blocking)
   - `just check-all` — the combined run: lint, tests + diff coverage, PII check
2. **The gate proper** (the [`pii_checker/`](pii_checker/) package) — only what needs
   service policy or judgment:
   - `just pii-check [branch] [severity]` → [`deterministic.py`](pii_checker/deterministic.py) —
     PII/retention scan (PII→log flows, undeclared retention of PII copies, weakened
     guardrails), reading `PII_FIELDS`/`RETENTION_DAYS` from the branch under review.
     A plain tool: readable on a terminal, JSONL when piped, exits 1 when any finding
     is at or above the severity threshold (default `S2` = what blocks merge per §6;
     `S1` for only the worst, `none` to never fail).
   - `just ai [branch]` → [`ai_review.py`](pii_checker/ai_review.py) — the Claude
     reviewer for what needs judgment: logic correctness, test *effectiveness*,
     minimization/legal basis. Its instructions live in
     [`prompt.md`](pii_checker/prompt.md).
   - `just review <branch>` → both of the above piped into
     [`decide.py`](pii_checker/decide.py) (`python -m pii_checker`) — severity (§6:
     S1/S2 block, S3 comments) → block / comment / approve + a report.

"The PR is blocked" = any required CI job fails — branch protection composes the gate
job with the hygiene jobs. Design: [`notes/PLAN.md`](notes/PLAN.md). The per-PR answer key and how
the gate scored against it live in [`deliverables/EVAL.md`](deliverables/EVAL.md) — comparison with the
reviewer's key is a conversation, not a script.

### Run it (target: reproducible in under 15 minutes)

```bash
direnv allow                        # Option A users: provisions python, just, gitleaks + installs
                                    #   requirements.txt AND requirements-dev.txt into .venv
export ANTHROPIC_API_KEY=sk-...     # optional — without it the AI check skips itself
                                    #   (policy checks still run; the report says what's lost)

just review feature/streaks         # the gate on one PR branch -> reports/<branch>.{md,json}
                                    #   exit 0 = approve/comment, exit 1 = block
just pii-check feature/support-context    # the PII tool alone (defaults to HEAD, severity S2)
just pii-check feature/email-reminders S1 # only fail on the worst severity
just check-all                            # combined: lint + coverage + pii-check
just secrets feature/email-reminders      # hygiene tools, runnable standalone
```

Option B (no Nix): `pip install -r requirements.txt -r requirements-dev.txt`, put
`gitleaks` on PATH for `just secrets`, and run the underlying commands from the
`justfile` (e.g. `python3 -m pii_checker.deterministic feature/support-context`).

CI: [`checks.yml`](.github/workflows/checks.yml) runs the checks **one at a time** on
every pull request, each step the same `just` command you'd run locally;
[`quality-gate.yml`](.github/workflows/quality-gate.yml) runs the same `just review`
(report uploaded as artifact; a block fails the job). Set the `ANTHROPIC_API_KEY` repo
secret to enable the AI check there.

## Endpoints

- `GET /health`
- `GET /lessons`
- `GET /students/{id}/progress`
- `POST /students/{id}/progress` — body: `{"lesson_id": "...", "score": 0-100}`

Data is held in memory (see `app/store.py`). There is no database: the focus of this repository is the review process, not persistence.
