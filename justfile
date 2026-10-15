# Common commands for student-progress. Run `just` (or `just --list`) to see them.
# The toolchain (python, pytest, ruff, uvicorn, just itself) comes from the Nix
# devShell via direnv — see notes/DEV-ENVIRONMENT.md.

# Show available recipes
default:
    @just --list

# Run the test suite
test:
    pytest -q

# Run specific tests, e.g. `just test-one tests/test_progress.py::test_progress_percentage`
test-one target:
    pytest -q {{target}}

# Lint with ruff
lint:
    ruff check .

# Lint + tests, the same gates CI runs
check: lint test

# Run the API locally (http://127.0.0.1:8000, interactive docs at /docs)
serve:
    uvicorn app.main:app --reload

# ---- AI Quality Gate (pii_checker/ + decide.py; see notes/PLAN.md, deliverables/EVAL.md) ----
# Only what needs policy/judgment lives here. Standard hygiene (coverage,
# secrets, TODOs) is standalone tooling below — separate CI jobs, not gate checks.

# PII/retention scan; exits 1 at/above `severity` (S1 worst; default S2 = blocks merge per §6; "none" = never fail)
pii-check branch="HEAD" severity="S2":
    python3 -m pii_checker.deterministic {{branch}} --fail-on {{severity}}

# AI review alone (prompt: pii_checker/prompt.md; skips gracefully without ANTHROPIC_API_KEY)
ai branch="HEAD":
    python3 -m pii_checker.ai_review {{branch}}

# The gate (same recipe as CI): pii-check + AI -> decide -> reports/<branch>.{md,json}; exit 1 = block
review branch:
    #!/usr/bin/env bash
    set -uo pipefail
    mkdir -p reports
    slug="$(echo '{{branch}}' | tr / -)"
    det="reports/$slug.det.jsonl"
    python3 -m pii_checker.deterministic {{branch}} --fail-on none > "$det"
    { cat "$det"; python3 -m pii_checker.ai_review {{branch}} --hints "$det"; } \
      | python3 -m pii_checker --branch {{branch}}

# ---- Standalone hygiene tools (CI runs them one at a time: checks.yml) ----

# Run the tests, then fail if under `fail_under`% of this checkout's changed lines are covered
coverage base="main" fail_under="100":
    pytest -q --cov=app --cov-report=xml
    diff-cover coverage.xml --compare-branch {{base}} --fail-under {{fail_under}}

# Secret scan over a branch's commits (gitleaks; any hit exits 1)
secrets branch="HEAD" base="main":
    gitleaks git --no-banner --log-opts="{{base}}..{{branch}}"

# TODOs without an issue link (ruff TD003, selected ad hoc — service lint config untouched)
todos:
    ruff check . --select TD003

# All local checks, one at a time (lint, tests+diff-coverage, PII scan)
check-all: lint coverage pii-check

# Hit the local server's /health (requires `just serve` running elsewhere)
api-health:
    @curl -fsS http://127.0.0.1:8000/health | jq .

# Hit the local server's /lessons (requires `just serve` running elsewhere)
api-lessons:
    @curl -fsS http://127.0.0.1:8000/lessons | jq .

# Hit /students/{id}/progress, e.g. `just api-progress s-001` (default: s-003)
api-progress id="s-003":
    @curl -fsS http://127.0.0.1:8000/students/{{id}}/progress | jq .

# jq builds the body so the string is escaped and score is a real JSON number.
# Record progress (POST), e.g. `just api-record s-004 l-01 80` (default score: 100)
api-record id lesson score="100":
    @jq -nc --arg l "{{lesson}}" --argjson s {{score}} '{lesson_id: $l, score: $s}' \
      | curl -fsS -X POST http://127.0.0.1:8000/students/{{id}}/progress \
        -H 'Content-Type: application/json' --data @- | jq .
