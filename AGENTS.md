# AGENTS.md

Guidance for Claude Code (and other agents) working in this repository.

## What this repo is

This is a **take-home assessment for Open English's Platform Engineer role**. The task
is to build an **AI Quality Gate**: a CI pipeline where an LLM reviews each open pull
request against `TEAM-STANDARDS.md` (with particular rigor on minors' privacy), produces
structured findings (severity, file/line, rule violated, suggested fix), and **decides**
whether to block, comment, or approve.

The repository currently contains only the **seed**: a small LMS service
(`student-progress`) plus 8 prepared pull requests (the "golden set"). The quality gate
itself has **not been built yet** — that is the work. The full brief is in
`assignment/Platform_Engineer_Challenge_-_Open_English.pdf`.

Two distinct things live in one git repo, do not conflate them:
- **The system under review** — the `app/` service and the 8 PR branches. Treat as fixed
  input. Do not "fix" the PRs; the bugs in them are the test cases.
- **The gate we are building** — new code/CI/prompts/eval harness. This is what we author.

## Required deliverables (the grade is these, equally weighted)

| File | Contents |
|------|----------|
| Working pipeline | The gate running over the 8 PRs (CI or well-documented local run) |
| `deliverables/EVAL.md` | Ground truth per PR, precision/recall vs. that ground truth, ≥1 false-positive + ≥1 false-negative analyzed, trust policy |
| `README.md` | Reproducible in < 15 min by a new dev (currently describes only the seed service — must be extended) |
| `deliverables/DECISIONS.md` | 3–6 mini-ADRs: trade-offs and what was cut and why |
| `deliverables/AI-USAGE.md` | Tools used, 3–5 key prompts, ≥1 case where AI output was discarded/corrected and why |

Timebox is a real 4–5h. Prioritizing well beats covering everything; park cut scope in
`deliverables/DECISIONS.md`. The reviewer reveals *their* ground truth at the session and also runs the
gate on an **unseen PR**, so the gate must generalize, not overfit these 8.

## The golden set: 8 PRs live as git branches

Each PR is a branch off `main`. There is no GitHub remote; review a PR by diffing locally:

```bash
git diff main..feature/score-validation          # the diff the gate must review
git diff main..<branch> -- '*.py'                  # code-only
git branch | grep -v main                          # list the 8 PR branches
```

Branches (see `PULL_REQUESTS.md` for titles/author descriptions):
`feature/lessons-pagination`, `feature/score-validation`, `fix/mobile-sync-visibility`,
`feature/support-context`, `feature/email-reminders`, `feature/streaks`,
`feature/analytics-archive`, `fix/progress-percentage`.

`open_prs.sh` is the **evaluator's** script to publish these as real GitHub PRs — it is not
needed to run the gate locally. The gate should consume `git diff` output directly.

The classification of what each PR gets wrong is **our deliverable** (`deliverables/EVAL.md` ground
truth), compared against the reviewer's hidden answer key during the session. Do not treat
any pre-written verdict as authoritative — derive it from the diff against the standards.

## TEAM-STANDARDS.md is the rubric — internalize the severity model

The gate's decisions must map to the severities defined in `TEAM-STANDARDS.md §6`:

- **S1 — blocks merge:** PII exposure (aggravated for `pii-minor`), committed secrets,
  retention/minimization violations involving minors' data.
- **S2 — blocks merge:** logic bugs producing incorrect data; core logic without
  *effective* tests.
- **S3 — comment only:** style, naming, refactors.

Key nuances the reviewer is testing for, worth encoding in prompts/checks:
- `full_name`, `email`, `birthdate` are PII; when `is_minor` is true they are `pii-minor`.
  PII must never reach logs **directly or indirectly** (helpers, `extra=`, serialization) —
  use `app.privacy.redact()`.
- Minors' data must not leave the service (analytics, support tooling, third parties)
  without minimization + documented legal basis.
- Minors' data retention ≤ 90 days unless a legal basis is documented in the PR; every
  persisted/copied dataset declares a category in `app.privacy.RETENTION_DAYS`.
- A test that cannot fail when the behavior breaks (trivial assertion, no business-case
  coverage) does **not** count as coverage — a passing test suite is not proof of S2-safety.

Combine the LLM with **deterministic checks** where cheaper/more reliable (e.g. secret
scanning, "does a logic change ship a test that would actually catch a regression",
grepping for PII field names reaching a logger). Not everything needs the LLM.

## The service under review (`app/`)

In-memory FastAPI LMS, no database (persistence is out of scope). Python 3.11+.

- `app/main.py` — FastAPI routes: `/health`, `/lessons`, `GET/POST /students/{id}/progress`.
- `app/models.py` — `Student` (carries the PII fields + `is_minor`), `Lesson`, `ProgressRecord`.
- `app/store.py` — seed data in module-level dicts/lists; **some students are minors**
  (`is_minor=True`), which is what makes the privacy rules bite.
- `app/privacy.py` — `redact()` and `RETENTION_DAYS`; the standards point reviewers here.

Note: source comments/docstrings are in Spanish; the standards and candidate-facing docs
are in English.

## Dev environment (Nix + direnv + venv)

The toolchain is provisioned automatically — **do not hand-roll a venv**. On `cd` into the
repo, direnv loads a Nix devShell (Python 3.12, pinned via `flake.lock`), creates/activates
`.venv`, and pip-installs `requirements.txt` when it changes. Hybrid on purpose: Nix gives
the interpreter, pip gives the packages (so they stay identical to CI). First time only:
`direnv allow`. Full rationale and troubleshooting in `notes/DEV-ENVIRONMENT.md`.

- If direnv isn't active in a shell (`which python3` → `/usr/bin/python3`), run
  `direnv reload`, or `direnv exec . <cmd>` to run a one-off inside the env.
- Do **not** run `eval "$(nix print-dev-env)"` by hand in zsh — it emits bash and fails to
  apply (`read-only variable: LINENO`, PATH unchanged). Let direnv do it.
- `flake.nix`/`flake.lock` are staged but not committed yet → Nix prints a harmless
  `uncommitted changes` warning on load.

## Commands

Common tasks are `just` recipes (run `just` to list them; defined in `justfile`):

```bash
just test                           # run the suite (pytest -q), from repo root
just test-one tests/test_progress.py::test_progress_percentage   # a single test
just lint                           # ruff check . (CI gate: ruff + pytest, see .github/workflows/ci.yml)
just check                          # lint + tests together
just serve                          # run the service via uvicorn (rarely needed for this task)
```

direnv provides python3/pytest/ruff/just from the Nix shell + `.venv` after `cd` +
`direnv allow`. In a shell without the direnv hook, prefix with `direnv exec . <cmd>`
(e.g. `direnv exec . just test`).

`conftest.py` + `pyproject.toml` set `pythonpath = ["."]` so `app` imports from the repo
root. When checking out a PR branch to run its tests, run pytest on that branch's tree.

## Working constraints

- The user manages their **system declaratively with Nix**. Keep changes inside the repo;
  do not edit `~/.config`, shell rc files, or home-manager config, and do not run imperative
  installers (`nix profile install`, `brew install`, …) without asking. Need a system-level
  tool (e.g. nix-direnv for `use flake`)? Prefer a project-local alternative, or tell the
  user what to add to their own Nix config.
- Commit only when asked; staging is fine when a tool requires it (Nix flakes read tracked
  files).

## Repo documentation map

- `notes/PLAN.md` — **the original build plan for the gate** (checks → findings → decide/eval).
  Superseded in structure by deliverables/DECISIONS.md ADRs 2/6/7 (final layout: `pii_checker/` +
  `decide.py`, hygiene tools standalone, no eval harness); kept as the design record.
- `notes/DEV-ENVIRONMENT.md` — Nix/direnv/venv setup, choices, troubleshooting.
- `notes/CODEBASE.md` — walkthrough of the `student-progress` service (architecture, file-by-file).
- `notes/COMMITS.md` — commit-by-commit walkthrough (main history + the 8 PR commits).
- `TEAM-STANDARDS.md` — the review rubric. `PULL_REQUESTS.md` — the 8 PRs.
- `assignment/Platform_Engineer_Challenge_-_Open_English.{pdf,md}` — the challenge brief.
- `deliverables/EVAL.md` / `deliverables/DECISIONS.md` / `deliverables/AI-USAGE.md` — graded deliverables (running logs; `deliverables/AI-USAGE.md`
  also holds the prompt log + interaction log). `deliverables/REVIEW-NOTES.md` — out-of-scanner
  recommendations.

## Status (as of 2026-10-11, late)

**Built, then simplified three times on user pushback** (deliverables/DECISIONS.md ADR 2, 6, 7, 8
supersede notes/PLAN.md's check catalog). Final shape — the `pii_checker/` package is "our
separate tooling":

- **Gate** (policy/judgment only): `pii_checker/deterministic.py` (one tool, three rules:
  PII→log taint incl. one-hop helpers, undeclared retention of PII copies, weakened
  `app/privacy.py` guardrails; branch arg defaults to HEAD, TTY-readable / JSONL piped,
  `--fail-on S1|S2|S3|none` severity threshold, default S2) + `pii_checker/ai_review.py`
  (Claude, structured output; the review prompt lives in `pii_checker/prompt.md`, edit
  it there) → `pii_checker/decide.py`, invoked as `python -m pii_checker` via
  `__main__.py` (§6 severities → block/comment/approve, readable report, `--ai-s2`
  switch). Shared: `pii_checker/_diff.py` (unidiff + `load_policy`),
  `pii_checker/_findings.py`. Run: `just review <branch>`; CI `quality-gate.yml`.
  ADR 8 records why the deterministic rules can't be ruff/bandit/semgrep rules.
- **Standalone hygiene** (standard tools, NOT gate checks): `just lint`, `just coverage`
  (pytest-cov + diff-cover, `--fail-under 100` default), `just secrets` (gitleaks),
  `just todos` (ruff `--select TD003`); `just check-all` = lint + coverage + pii-check.
  CI `checks.yml` runs the checks one at a time, each step the same just command
  (TODOs non-blocking).
- **No eval harness** (user decision): `deliverables/EVAL.md` is the answer key + hand-tallied
  results; comparison with the reviewer's key happens live at the session.

Verified (fresh-eyes audit + user runs, 2026-10-11, no API key): direnv env end-to-end
(requirements-dev incl. unidiff; flake provides gitleaks); lint clean; pii-checker finds
exactly the 4 expected deterministic hits across the 8 branches, 0 FPs on clean
branches, exit codes and `--fail-on` thresholds correct; `just review` blocks/approves
correctly without a key and writes reports; `just secrets` finds the planted SendGrid
key; ruff TD003 and diff-cover fire on an email-reminders checkout; decisions 6/8
without AI (misses = the two false-green logic PRs, AI-owned). **Keyed runs completed
2026-10-15** over all 8 branches (verbatim transcript: deliverables/RUN-LOG.md): both
false-green logic PRs blocked on AI S2 with worked examples; clean PRs not false-blocked
(one real S3 comment on score-validation, pre-recorded in REVIEW-NOTES §3); decision
accuracy with AI 8/8 at block level; `--ai-s2 block` confirmed (EVAL.md trust policy,
ADR 5 resolution). Known code polish items from the audit (fail-open `review` recipe
without `set -e`; multiline-log-call and redact-short-circuit detection edges; report's
"AI contributed nothing" banner also fires when a keyed run returns zero findings) are
in the audit report, not yet applied.

Deviations from notes/PLAN.md, all recorded: temp-0 impossible on current API → structural
determinism (ADR 4); taint *does* catch `support-context` (deliverables/EVAL.md); mutation parked;
hygiene/diff-parsing/eval restructured per ADRs 2, 6, 7.

See the memory files for standing preferences (in-project/Nix-declarative, composable/simple,
user runs verification).

## Conventions for the gate we build

- Keep gate code isolated from the service (it lives in the top-level `pii_checker/`
  package) so it never pollutes the diffs being reviewed.
- Findings are structured (JSONL when piped; readable on a TTY) so tools compose.
  `deliverables/EVAL.md` holds the answer key and hand-tallied results — no scoring harness (user
  decision, ADR 7: at n=8 the comparison with the reviewer's key is a conversation,
  not a script).
- Default to the latest Claude models for the reviewer LLM; the API key comes from an env
  var, never committed (this repo's PR #5 trap is literally a committed key).
