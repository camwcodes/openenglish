# Review notes — recommendations beyond the scanner

What a reviewer should push for that the gate deliberately does **not** implement
(the gate detects violations; these remove the conditions that make them possible).

## 1. Build redaction into the logging layer (preferred fix)

Root cause of the log-PII traps (`fix/mobile-sync-visibility`, `feature/support-context`):
`app.privacy.redact()` is **opt-in** — every call site must remember it, so forgetting it
is the default failure mode. Move redaction into the one place every record passes
through:

```python
class RedactPII(logging.Filter):
    def filter(self, record):
        record.args = tuple(
            redact(a) if isinstance(a, dict) else a for a in (record.args or ())
        )
        return True
```

(sketch — a structlog processor is the nicer version). Same for any future notifier.
Add base-library tests proving the logger redacts PII, so the guarantee itself is covered.

## 2. Switch `redact()` from blocklist to allowlist

`redact()` masks keys found in `PII_FIELDS` → **fails open**: a new PII field on
`Student` leaks everywhere until someone updates the set. An allowlist projection
`pick(obj, ["student_id", "lesson_id", ...])` **fails closed** and is DRY.

Note: the one real call site today, `redact({"student_id": ..., "lesson_id": ...})`
(app/main.py), is a **no-op** — the dict contains no PII keys. The actual protection is
the manual field selection; the code only *looks* defended.

## 3. Smaller observations

- `int(payload.get("score", 0))` raises `ValueError` → 500 on non-numeric input; the
  validation PRs never fixed input *type* validation. Pydantic models for request bodies
  would subsume most of `feature/score-validation`. *(The keyed AI run of 2026-10-15
  independently surfaced exactly this on `feature/score-validation` as an S3 comment —
  see EVAL.md's FP analysis and RUN-LOG.md.)*
- `app/streaks.py` would be trivially safe with a `start = today` parameter and a
  property-based test (`streak(dates + [today]) == streak(dates) + 1` when today is new).
- Retention is declared (`RETENTION_DAYS`) but nothing *enforces* it — there is no purge
  job. The standard is only as real as the mechanism behind it.
