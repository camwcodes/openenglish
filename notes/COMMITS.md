# Commit-by-commit walkthrough

What every commit in the seed repository changed. The history has two parts:

- **`main` history** — 6 commits that build the `student-progress` service and its docs.
- **PR commits** — 8 branches, each a single commit off `main` (these are "the 8 PRs").

This document is **descriptive** (what changed), not a verdict on each PR — classifying the
PRs against `TEAM-STANDARDS.md` is the `EVAL.md` ground-truth exercise. All commits are
authored by `OE Platform <platform@openenglish.com>` on 2026-07-22/23.

---

# Part A — `main` branch history

## `6a6e592` — student-progress: servicio base del LMS

The initial commit: the entire baseline service, tests, CI, and the first cut of the team
standards — 11 files, 240 insertions. Everything later commits and PRs build on lands here.

**Breakdown:**
- `app/main.py` — FastAPI app with `/health`, `/lessons`, and `GET`/`POST
  /students/{id}/progress`; the `_get_student` 404 helper; percentage math; redacted log on
  write.
- `app/models.py` — `Student` / `Lesson` / `ProgressRecord` dataclasses + the PII
  classification comments.
- `app/store.py` — in-memory `STUDENTS` (4, two minors) / `LESSONS` (5) / `PROGRESS` (6).
- `app/privacy.py` — `redact()` and `RETENTION_DAYS`.
- `app/__init__.py` — empty package marker.
- `tests/test_progress.py` — 5 baseline tests (health, lessons, 60% case, 404, POST).
- `TEAM-STANDARDS.md` (Spanish, 31 lines), `README.md` (Spanish), `requirements.txt`
  (fastapi/uvicorn/httpx/pytest/ruff), `.github/workflows/ci.yml` (ruff + pytest),
  `.gitignore`.

## `08adbea` — Docs: PRs abiertos y script para publicarlos

Adds the two files that frame the exercise: the list of the 8 PRs and the evaluator's script
to publish them as GitHub PRs. No service code touched.

**Breakdown:**
- `PULL_REQUESTS.md` (new) — Spanish table of the 8 branches with titles and author blurbs.
- `open_prs.sh` (new) — Bash using `declare -A` associative arrays (`TITLES`/`BODIES`) to
  `git push` each branch and `gh pr create`. (This Bash-4 form is what a later commit
  rewrites for macOS.)

## `d698911` — Fix: pytest pythonpath + requisito Python 3.11+

Makes the test suite runnable from the repo root and pins the Python floor. This is the
commit that introduced the `pythonpath`/`conftest` wiring the dev environment relies on.

**Breakdown:**
- `pyproject.toml` (new) — project metadata, `requires-python = ">=3.11"`, and
  `[tool.pytest.ini_options]` with `pythonpath = ["."]` + `testpaths = ["tests"]`.
- `conftest.py` (new) — one-line comment file; its presence pins the pytest rootdir.
- `README.md` — adds the Python 3.11+ note and the `python3 -m venv .venv` line.

## `e03b086` — Team standards in English

Translates `TEAM-STANDARDS.md` from Spanish to English. Content-equivalent, but this is the
canonical rubric the gate reviews against, so the wording matters.

**Breakdown:**
- `TEAM-STANDARDS.md` — full Spanish→English rewrite of all six sections (code quality,
  testing, PII/logging, retention, secrets, review severities S1/S2/S3). The substantive
  rules are preserved: PII fields = `full_name`/`email`/`birthdate`, `pii-minor` when
  `is_minor`, 90-day minor retention, `redact()`, severity tiers.

## `94bfe37` — Candidate-facing docs in English

Translates the remaining candidate-facing docs to English so the repo reads consistently.
Documentation only.

**Breakdown:**
- `PULL_REQUESTS.md` — Spanish→English (table header + all 8 author descriptions).
- `README.md` — Spanish→English (title blurb, "Running locally", endpoints note).
- `open_prs.sh` — Spanish→English comments and the `BODIES` strings; logic unchanged.

## `fbd4e09` — open_prs.sh compatible with bash 3.2 (macOS default)

Rewrites the PR-publishing script to run on macOS's stock Bash 3.2, which lacks the
associative arrays the earlier version used. Behavior is identical; only portability changes.

**Breakdown:**
- `open_prs.sh` — replaces the `declare -A TITLES/BODIES` maps and `for branch in "${!...}"`
  loop with a `while IFS='|' read -r branch title body` loop over a `<<'PRS'` heredoc of
  `branch|title|body` lines. Adds a "works on macOS's default bash 3.2" comment.

---

# Part B — the 8 PR commits (one branch each)

## `386b2e1` — `feature/lessons-pagination` — Add pagination to lessons list

Adds `limit`/`offset` query parameters to `GET /lessons` with bounds validation, plus a test
file covering the slice, the default behavior, and invalid params.

**Breakdown:**
- `app/main.py` — `list_lessons(limit: int = 50, offset: int = 0)`; raises `HTTPException
  422` when `limit < 1 or limit > 100 or offset < 0`; returns
  `store.LESSONS[offset : offset + limit]`.
- `tests/test_lessons_pagination.py` (new, 3 tests) — `test_pagination_slice`
  (`limit=2, offset=1` → `["l-02","l-03"]`), `test_pagination_defaults_return_all` (→ 5),
  `test_pagination_invalid_params` (`limit=0` and `offset=-1` → 422).

## `60a6090` — `feature/score-validation` — Validate lesson and score on progress recording

Adds input validation to `POST /students/{id}/progress`: the `lesson_id` must exist and the
`score` must be 0–100, with tests for the rejection and acceptance paths.

**Breakdown:**
- `app/main.py` — in `record_progress`: rejects unknown `lesson_id`
  (`422 "unknown lesson"`) by checking membership in `{lesson.id for lesson in store.LESSONS}`;
  computes `score = int(payload.get("score", 0))` and rejects `score < 0 or score > 100`
  (`422`); constructs the record with the validated `score`.
- `tests/test_score_validation.py` (new, 3 tests) — unknown lesson → 422, out-of-range
  scores (`101`, `-5`) → 422, valid score (`100`) → `{"ok": True}`.

## `fa726eb` — `fix/mobile-sync-visibility` — Add sync visibility to debug missing progress reports

Adds a log line on progress writes to help support trace "progress not showing" reports from
the mobile app. No tests.

**Breakdown:**
- `app/main.py` — in `record_progress`, before the existing redacted log, adds a
  `logger.info("sync: progress recorded for %s (%s) lesson=%s score=%s", student.full_name,
  student.email, record.lesson_id, record.score)` — i.e. logs `full_name` and `email`
  directly (not via `redact()`).
- No test file added.

## `dfabcae` — `feature/support-context` — Support tooling: log compact context on progress lookups

Adds a support helper that assembles a compact per-student context and logs it on every
progress lookup, so support doesn't have to pull from three systems. No tests.

**Breakdown:**
- `app/support.py` (new) — `build_support_context(student, records)` returns a dict with
  `student` (`"full_name <email>"`), `birthdate`, `country`, and `records` (count).
- `app/main.py` — imports it and, in `get_progress`, adds
  `logger.info("progress lookup %s", build_support_context(student, records))` on every
  `GET /students/{id}/progress`.
- No test file added.

## `e1732cb` — `feature/email-reminders` — Scaffolding for inactivity email reminders

Adds a not-yet-wired module for emailing inactive students. Currently only logs; nothing is
sent. No tests.

**Breakdown:**
- `app/notifications.py` (new) — module logger; module-level constants
  `SENDGRID_API_KEY = "SG.kx9m…"` (a hardcoded SendGrid-shaped key) and
  `FROM_ADDRESS = "reminders@openenglish.com"`; a `# TODO: mover a config antes del launch`
  comment; `send_inactivity_reminder(email, days_inactive)` that only does
  `logger.info("reminder queued to=%s days_inactive=%s", email, days_inactive)`.
- No wiring into `app/main.py`; no test file added.

## `b5133c2` — `feature/streaks` — Lesson streak calculation for gamification

Adds a pure function to compute a consecutive-day activity streak, with a test file of three
assertions.

**Breakdown:**
- `app/streaks.py` (new) — `current_streak(activity_dates: list[date], today: date | None =
  None) -> int`: defaults `today` to `date.today()`, builds a `set` of the dates, then walks
  **backward starting from `today - 1 day`** (`day = today - timedelta(days=1)`), counting
  while `day in days`. (Note: the loop begins at yesterday, so activity *on* `today` is not
  counted toward the streak.)
- `tests/test_streaks.py` (new, 3 tests) — `test_streak_returns_int` (result is an `int`),
  `test_streak_never_negative` (`current_streak([]) >= 0`), `test_streak_handles_duplicates`
  (duplicate dates → `>= 0`). (All three assert type/non-negativity rather than a specific
  streak value.)

## `d5ecfb1` — `feature/analytics-archive` — Archive progress events for cohort analytics

Adds an in-memory archive that copies each progress event together with student attributes
so analytics can slice cohorts without joins, and wires it into the write path. No tests.

**Breakdown:**
- `app/archive.py` (new) — module-level `ARCHIVE: list[dict]`; `archive_progress(student,
  record)` appends a dict with `student_id`, `full_name`, `birthdate`, `country`,
  `is_minor`, `lesson_id`, `score`. The module docstring states the data is "conserved
  indefinitely" for year-over-year comparison. No entry in `RETENTION_DAYS`.
- `app/main.py` — imports `archive_progress` and calls it in `record_progress` after
  appending to `store.PROGRESS`.
- No test file added.

## `a620c38` — `fix/progress-percentage` — Fix percentage rounding inconsistencies

Changes how the completion percentage is computed in `GET /students/{id}/progress` and adds a
test for the no-lessons case.

**Breakdown:**
- `app/main.py` — changes `percentage = round(100 * completed / total) if total else 0` to
  `percentage = int(100 * completed / total) if total else 100`. Two behavior changes:
  `round()` → `int()` (truncation instead of rounding), and the no-lessons fallback `0` →
  `100`.
- `tests/test_progress.py` — adds `test_progress_percentage_no_lessons`, which
  `monkeypatch`es `store.LESSONS` to `[]` and asserts the returned `percentage == 100`.

---

## At a glance

| Commit | Branch / scope | Files | Tests added |
|--------|----------------|-------|-------------|
| `6a6e592` | main — base service | 11 | 5 (baseline) |
| `08adbea` | main — PR docs + script | 2 | — |
| `d698911` | main — pytest/python pin | 3 | — |
| `e03b086` | main — standards → EN | 1 | — |
| `94bfe37` | main — docs → EN | 3 | — |
| `fbd4e09` | main — bash 3.2 script | 1 | — |
| `386b2e1` | lessons-pagination | 2 | 3 |
| `60a6090` | score-validation | 2 | 3 |
| `fa726eb` | mobile-sync-visibility | 1 | 0 |
| `dfabcae` | support-context | 2 | 0 |
| `e1732cb` | email-reminders | 1 | 0 |
| `b5133c2` | streaks | 2 | 3 |
| `d5ecfb1` | analytics-archive | 2 | 0 |
| `a620c38` | progress-percentage | 2 | 1 |
