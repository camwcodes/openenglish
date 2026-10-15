# Codebase Walkthrough — `student-progress`

A reading guide to the seed service **before** you dig into the code. This describes the
**system under review** (the LMS service + its test/CI setup), not the AI Quality Gate we
are building. The service is deliberately small and deliberately imperfect: it is the
substrate the 8 PRs modify and that our reviewer must judge.

> Orientation only — the severity rules and per-PR traps live in `AGENTS.md` and
> `TEAM-STANDARDS.md`. This file is about *how the code is built*.

---

## 1. File structure as a whole

```
OpenEnglish/
├── app/                      # the service (the thing under review)
│   ├── __init__.py           # marks app as a package (empty)
│   ├── main.py               # FastAPI app: routes + request handling
│   ├── models.py             # domain types (dataclasses) + PII classification
│   ├── store.py              # in-memory seed data (students, lessons, progress)
│   └── privacy.py            # redaction helper + retention policy constants
├── tests/
│   └── test_progress.py      # service tests (FastAPI TestClient)
├── conftest.py               # pytest bootstrap (makes `app` importable)
├── pyproject.toml            # project metadata + pytest config
├── requirements.txt          # pinned runtime + dev deps
├── .github/workflows/ci.yml  # CI: ruff lint + pytest on PRs and main
├── open_prs.sh               # evaluator's script to publish the 8 branches as PRs
├── README.md                 # how to run the service locally
├── TEAM-STANDARDS.md         # the review rubric (code/testing/PII/retention/secrets)
└── PULL_REQUESTS.md          # the 8 PRs: branch, title, author's description
```

Plus the assessment artifacts we added (`AGENTS.md`, `EVAL.md`/`DECISIONS.md`/`AI-USAGE.md`
scaffolds, the challenge PDF + its markdown) and the two provided zips.

**Two layers in one repo.** Everything under `app/`, `tests/`, and the 8 git branches is
*fixed input* — the material being reviewed. Everything we author for the gate is separate.
Don't edit the service to "fix" the PRs; the flaws are the exam questions.

### The 8 PRs are git branches, not files

There is no GitHub remote. Each PR is a branch off `main`; you inspect one with
`git diff main..<branch>`. `open_prs.sh` is the *evaluator's* helper to push them as real
GitHub PRs later — it is not part of running the service or the gate.

---

## 2. Architecture in one paragraph

A single-process **FastAPI** app with **all state in module-level Python collections** —
no database, no ORM, no persistence layer (the README is explicit: the focus is the review
process, not persistence). A request hits a route in `app/main.py`, which reads/writes the
in-memory structures in `app/store.py`, builds plain `dict`/dataclass responses, and
(for writes) emits a log line scrubbed through `app/privacy.py`. `app/models.py` defines
the shapes; `app/store.py` holds the data; `app/privacy.py` encodes the compliance rules
as code. That's the entire runtime.

```
HTTP request
   │
   ▼
app/main.py  ──reads/writes──►  app/store.py  (STUDENTS / LESSONS / PROGRESS)
   │                                   │
   │ uses shapes from                  │ holds instances of
   ▼                                   ▼
app/privacy.py  (redact, RETENTION) ◄─ app/models.py  (Student / Lesson / ProgressRecord)
   │
   ▼
logger  (should only ever see redacted payloads)
```

---

## 3. File-by-file

### `app/models.py` — domain types + the PII contract
Three `@dataclass` types: `Student`, `Lesson`, `ProgressRecord`. Plain data holders, no
behavior. The important part is the **module docstring and inline comments**: they classify
`full_name`, `email`, `birthdate` as PII, and as **`pii-minor`** when `is_minor` is true —
mirroring `TEAM-STANDARDS.md §3`. `Student` is the only type carrying personal data; it also
carries the `is_minor` flag that escalates every privacy rule. (Comments/docstrings are in
Spanish; the standards and candidate docs are English.)

### `app/store.py` — the in-memory "database"
Three module-level globals populated at import:
- `STUDENTS`: `dict[str, Student]` — 4 students. **Two are minors** (`s-001` b.2013,
  `s-002` b.2011), two are adults (`s-003`, `s-004`). This mix is what makes the privacy
  rules bite in practice.
- `LESSONS`: `list[Lesson]` — 5 lessons, levels A1–B1.
- `PROGRESS`: `list[ProgressRecord]` — 6 seed records.

Because these are **module-level mutable globals**, any write (`POST`) mutates shared
process state. Note the test-isolation implication (see §5): state leaks across requests
and across tests within a run.

### `app/privacy.py` — compliance encoded as code
Small but load-bearing. Two pieces:
- `PII_FIELDS = {"full_name", "email", "birthdate"}` and `redact(payload)` → returns a copy
  with those keys replaced by `"[REDACTED]"`. **Shallow and opt-in**: it only redacts
  top-level keys the caller chose to pass, and only if the caller remembers to call it.
  Nothing forces log statements through it.
- `RETENTION_DAYS = {"progress": 365, "progress_minor": 90}` — the retention buckets any
  new persisted/copied dataset is supposed to declare. The 90-day minor bucket is the
  policy the archive-style PRs must respect.

This file is the "right way" the standards point to; the review traps are mostly about code
that **bypasses** it.

### `app/main.py` — the web layer (the center of gravity)
Creates the `FastAPI` app and a module logger configured at `INFO` with a plain formatter.
Routes:
- `GET /health` → `{"status": "ok"}`. Trivial liveness.
- `GET /lessons` → serializes `store.LESSONS` via `lesson.__dict__`. No pagination in
  baseline (one PR adds it).
- `_get_student(student_id)` → shared helper; raises `HTTPException(404)` if missing. The
  one place lookups are centralized.
- `GET /students/{id}/progress` → filters `PROGRESS` for the student, counts `completed`,
  computes `percentage = round(100 * completed / total) if total else 0`. The `if total`
  guard and the rounding are exactly what one PR changes.
- `POST /students/{id}/progress` → takes an **untyped `payload: dict`**, reads
  `payload["lesson_id"]` (unguarded — `KeyError` → 500 on missing key) and
  `int(payload.get("score", 0))`, appends a new `ProgressRecord`, then logs via
  `redact(...)`. **No validation** of lesson existence or score range in baseline — the
  seam two PRs target. The write path is also where PII-to-logs traps get inserted.

Design note: handlers return plain `dict`s and dataclass `__dict__`s rather than Pydantic
response models, and the POST body is an untyped `dict` rather than a Pydantic model — so
there is **no automatic input validation**. That looseness is intentional seed material.

### `tests/test_progress.py` — the baseline test suite
Uses `fastapi.testclient.TestClient` (a `TestClient` built once at module import). Covers:
health, lesson count, the 60% percentage case for `s-003`, 404 for unknown student, and a
`POST` round-trip for `s-004`. These are *effective* tests (they'd fail if behavior broke) —
a useful contrast to the **trivial** tests some PRs ship, which `TEAM-STANDARDS §2` says
"do not count as coverage." The client hits the shared in-memory store, so the `POST` test
mutates global state for the rest of the run.

### `conftest.py` + `pyproject.toml` — the test/runtime wiring
`pyproject.toml` sets `[tool.pytest.ini_options] pythonpath = ["."]` and
`testpaths = ["tests"]`, so `import app...` resolves from the repo root and `pytest` with no
args finds the suite. `conftest.py` is effectively empty (a comment) but its presence pins
the pytest rootdir to the repo root. Python `requires-python = ">=3.11"`.

### `.github/workflows/ci.yml` — the existing CI
On `pull_request` and pushes to `main`: checkout → setup Python **3.12** → `pip install -r
requirements.txt` → `ruff check .` → `pytest -q`. This is the *service's* gate (lint +
tests). Our **AI Quality Gate is a separate pipeline** we add; this file shows the house
CI style to match. (Minor wrinkle worth noting: runtime floor is 3.11 but CI pins 3.12.)

### `requirements.txt`
Pinned: `fastapi`, `uvicorn` (serve), `httpx` (TestClient transport), `pytest`, `ruff`.
Lean — no DB driver, no settings/secrets library (relevant: the secret-handling rule has no
framework backing it, so a hardcoded key is easy to slip in).

### `open_prs.sh`
Bash (portable to macOS bash 3.2). Reads a heredoc table of `branch|title|body`, pushes each
branch and opens a `gh pr create`. For the evaluator to materialize the 8 PRs on GitHub —
not needed for local review.

---

## 4. How it works together — request lifecycles

**Read progress** (`GET /students/s-003/progress`): route → `_get_student` (404 if absent)
→ list-comprehension filter over `store.PROGRESS` → count completed → `percentage` math →
plain `dict` response. Pure read; no logging, no PII leaves.

**Record progress** (`POST /students/s-004/progress`): route → `_get_student` → read
`lesson_id`/`score` from the raw dict → construct `ProgressRecord` → **append to the global
`store.PROGRESS`** → `logger.info(..., redact({...}))` → `{"ok": True}`. This single handler
touches every theme the review cares about: input validation (absent), correct data
(score/lesson trust), mutation of shared state, and PII-safe logging. Most PR traps live on
or near this path.

---

## 5. Main coding structures & design themes

- **Everything is module-global mutable state.** `STUDENTS/LESSONS/PROGRESS` are imported
  and mutated in place. Simple, but: no test isolation between cases, order-dependence
  risk, and not thread-safe (fine here — single-process exercise). Keep this in mind when
  reasoning about whether a PR's test actually proves anything.
- **Dataclasses as dumb records; dicts on the wire.** No Pydantic models for I/O, so no
  framework-enforced validation. Responses are hand-built dicts / `__dict__` dumps.
- **Compliance is convention, not enforcement.** `redact()` and `RETENTION_DAYS` exist, but
  nothing *requires* their use — a dev can log `student.full_name` directly or copy data
  with no retention tag and the code still runs and passes lint. The standards fill the gap
  that the code deliberately leaves open. This gap is precisely what the AI reviewer must
  police.
- **Explicit-error style, inconsistently applied.** `_get_student` raises a clean 404, but
  `POST` dereferences `payload["lesson_id"]` without guarding — a seam for the
  input-validation PRs.
- **Small, flat, dependency-light.** Five source files, no layers/services/repos. Easy to
  hold the whole thing in your head, which is the point: the difficulty is in *judging
  changes*, not understanding the base.

---

## 6. Suggested reading order

1. `TEAM-STANDARDS.md` — the rubric everything is judged against.
2. `app/models.py` → `app/store.py` — the shapes and the data (note who's a minor).
3. `app/privacy.py` — the compliance primitives.
4. `app/main.py` — where it all comes together (read the `POST` handler closely).
5. `tests/test_progress.py` — what "effective tests" look like here.
6. `PULL_REQUESTS.md`, then `git diff main..<branch>` for each of the 8 — the actual work.
