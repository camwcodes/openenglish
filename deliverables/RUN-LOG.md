# RUN-LOG — keyed gate runs over all 8 PRs (verbatim)

Exact commands and unedited output of the full gate (`pii-check` + AI review →
`decide`) with `ANTHROPIC_API_KEY` set. Run 2026-10-15 from repo root on `main`;
model `claude-opus-4-8` (the `GATE_AI_MODEL` default), trust policy `--ai-s2 block`
(the default). Reports also landed in `reports/<slug>.{md,json}` (gitignored).
Durations are from the shell prompt. Results are tallied against the answer key in
[EVAL.md](EVAL.md).

A reading note: on a clean PR the report's ⚠️ "AI review contributed nothing" banner
still appears — `decide.py` infers AI participation from findings, and a keyed run
that returns zero findings is indistinguishable from a skipped one. The banner text
("clean PR, no API key, or API failure") covers the case; known polish item.

---

## `just review feature/streaks` (~17s, exit 1)

```
# Quality gate — `feature/streaks`

**Decision: ⛔ BLOCK**

- **S2 — blocks merge** · `app/streaks.py:10` · logic/incorrect (AI, confidence 0.92)
  current_streak never checks today itself; it starts counting at today-1, so the day the user is actually active today is ignored and the streak is off (and a streak ending today is miscounted when today has no activity). [worked example: Input: activity_dates=[2026-07-20, 2026-07-21, 2026-07-22], today=2026-07-22. days={20,21,22}. Code: day=21 -> in days, streak=1, day=20 -> in days, streak=2, day=19 -> not in days -> return 2. Intended: consecutive days with activity ending today = 20,21,22 = 3. Actual 2 != expected 3.]
  **Fix:** Start the walk at `day = today` (and require activity today to have a non-zero streak), e.g. `day = today; while day in days: streak += 1; day -= timedelta(days=1)`.

- **S2 — blocks merge** · `tests/test_streaks.py:6` · testing/ineffective (AI, confidence 0.95)
  All three tests assert only type (isinstance int) or non-negativity (>=0); none assert a concrete streak value, so they pass regardless of the off-by-one bug and cannot detect a regression (§2). [worked example: test_streak_returns_int checks isinstance(...,int) -> true for any return. test_streak_never_negative checks []>=0 -> 0>=0 true. test_streak_handles_duplicates checks result>=0 -> 2>=0 true. With the bug returning 2 instead of 3, every assertion still passes, so none fail when behavior breaks.]
  **Fix:** Add an assertion on an exact value, e.g. assert current_streak([date(2026,7,20),date(2026,7,21),date(2026,7,22)], today=date(2026,7,22)) == 3, which currently fails and exposes the bug.


error: recipe `review` failed with exit code 1
```

## `just review fix/progress-percentage` (~27s, exit 1)

```
# Quality gate — `fix/progress-percentage`

**Decision: ⛔ BLOCK**

- **S2 — blocks merge** · `app/main.py:39` · logic/incorrect (AI, confidence 0.88)
  The percentage computation was changed in two ways that produce incorrect data. (1) round() was replaced by int(), which truncates instead of rounding. (2) The no-lessons fallback was changed from 0 to 100, so a student with no lessons (or whose completed count exceeds total) is reported as 100% complete. [worked example: Truncation: completed=2, total=3 -> 100*2/3 = 66.666...; intended round() = 67, but int() returns 66 (off by one, understated). Empty case: monkeypatch LESSONS=[] for s-003 whose PROGRESS has 3 completed records -> completed=3, total=0 -> new code takes the 'else 100' branch and returns 100, i.e. a student is '100% complete' of zero lessons; intended/original value is 0.]
  **Fix:** Keep rounding and use 0 for the empty case: percentage = round(100 * completed / total) if total else 0

- **S2 — blocks merge** · `tests/test_progress.py:30` · testing/ineffective (AI, confidence 0.85)
  test_progress_percentage_no_lessons asserts the buggy fallback value (100) rather than correct behavior, so it locks in the regression instead of detecting it. It cannot catch the real problem (completed>0 with total=0 reported as fully complete). [worked example: Trace: monkeypatch LESSONS=[] -> total=0; s-003 has 3 completed PROGRESS records -> completed=3; new code returns percentage=100 via 'else 100'. The test asserts ==100, so it passes on the buggy value. If the code were fixed to the intended 0, this test would fail — meaning it asserts the wrong expected value and provides no protection against the regression.]
  **Fix:** Assert the intended empty-dataset percentage (0) and add a case that exercises rounding (e.g. 2 of 3 -> 67) so truncation regressions are caught.


error: recipe `review` failed with exit code 1
```

## `just review feature/lessons-pagination` (~6s, exit 0)

```
# Quality gate — `feature/lessons-pagination`

**Decision: ✅ APPROVE**

No findings.

⚠️ The AI review contributed nothing this run (clean PR, no API key, or API failure — see run logs). Without it, subtle logic bugs and ineffective-test findings are NOT covered.
```

## `just review feature/score-validation` (~18s, exit 0)

```
# Quality gate — `feature/score-validation`

**Decision: 💬 COMMENT**

- **S3 — comment only** · `app/main.py:51` · quality/style (AI, confidence 0.60)
  score is coerced with int(payload.get("score", 0)) before validation; a non-numeric value raises an unhandled ValueError producing a 500 instead of a 422. External input should be validated explicitly (§1). [worked example: POST /students/s-004/progress with {"lesson_id":"l-01","score":"abc"}: lesson check passes, then int("abc") raises ValueError which is not caught, so FastAPI returns 500. Expected: a 422 validation error consistent with the other score checks.]
  **Fix:** Wrap the int() conversion in a try/except and raise HTTPException(422) on failure, or validate the type before coercion.
```

## `just review fix/mobile-sync-visibility` (~15s, exit 1)

```
# Quality gate — `fix/mobile-sync-visibility`

**Decision: ⛔ BLOCK**

- **S1 — blocks merge** · `app/main.py:57` · pii/log-exposure (deterministic)
  PII written to logs (PII field `.full_name` is passed to the logger). Seed data includes minors, so this is aggravated pii-minor exposure (§3).
  **Fix:** Log only non-PII identifiers, or pass the payload through app.privacy.redact().

- **S1 — blocks merge** · `app/main.py:57` · pii/minor-exposure (AI, confidence 1.00)
  Aggravation of the PII log exposure: the leaked students include minors. Seed data s-001 (birthdate 2013-04-02, is_minor=True) and s-002 (2011-11-19, is_minor=True) have full_name and email logged, making this pii-minor exposure which carries stricter handling under §3/§6. [worked example: record_progress('s-002', {'lesson_id':'l-01'}): student=Student('s-002','Mateo Fernández','mateo.f@example.com','2011-11-19','MX', is_minor=True). Log line produces 'sync: progress recorded for Mateo Fernández (mateo.f@example.com) ...' — a minor's full_name+email in the logs.]
  **Fix:** Never log minors' PII; emit only redacted non-PII identifiers.


error: recipe `review` failed with exit code 1
```

## `just review feature/support-context` (~16s, exit 1)

```
# Quality gate — `feature/support-context`

**Decision: ⛔ BLOCK**

- **S1 — blocks merge** · `app/main.py:37` · pii/log-exposure (deterministic)
  PII written to logs (helper `build_support_context()` builds PII fields and its result is logged). Seed data includes minors, so this is aggravated pii-minor exposure (§3).
  **Fix:** Log only non-PII identifiers, or pass the payload through app.privacy.redact().

- **S1 — blocks merge** · `app/support.py:6` · pii/minor-exposure (AI, confidence 0.95)
  Aggravation of the log-exposure finding: build_support_context emits pii-minor data. Seed students s-001 (Valentina Rojas, birthdate 2013) and s-002 (Mateo Fernández, 2011) have is_minor=True, so full_name/email/birthdate are pii-minor. Logging these fields is aggravated exposure of minors' personal data under §3/§6. [worked example: For s-001 is_minor=True; build_support_context puts 'Valentina Rojas <valen.rojas@example.com>' and birthdate '2013-04-02' into the returned dict. The caller logs this dict, so pii-minor (name+email+birthdate of a 12-year-old) lands in application logs — the aggravated case in §6.]
  **Fix:** Remove full_name, email and birthdate from the support context entirely; expose only non-PII identifiers (student.id, country, records count) so minors' data never reaches logs.


error: recipe `review` failed with exit code 1
```

## `just review feature/email-reminders` (~13s, exit 1)

```
# Quality gate — `feature/email-reminders`

**Decision: ⛔ BLOCK**

- **S1 — blocks merge** · `app/notifications.py:7` · secrets/committed (AI, confidence 0.98)
  A SendGrid API key is hardcoded and committed to the repository (SENDGRID_API_KEY = "SG...."). Per §5 this is a security incident regardless of environment; secrets must come from environment variables only.
  **Fix:** Remove the literal key, load it from os.environ at runtime (e.g. SENDGRID_API_KEY = os.environ["SENDGRID_API_KEY"]), and rotate/revoke the exposed key immediately since it is now in git history.

- **S1 — blocks merge** · `app/notifications.py:11` · pii/minor-exposure (AI, confidence 0.85)
  send_inactivity_reminder takes an email and logs it; the student seed data (app/store.py) contains minors s-001 (Valentina, birthdate 2013) and s-002 (Mateo, 2011) with is_minor=True. Inactivity reminders would target exactly these inactive students, so the logged emails are pii-minor, aggravating the log-exposure finding to the strictest handling tier.
  **Fix:** Never log minors' emails; redact or omit PII and, before wiring up, ensure a documented legal basis and data minimization for any email sent/stored for minors.

- **S1 — blocks merge** · `app/notifications.py:13` · pii/log-exposure (deterministic)
  PII written to logs (variable `email` (a PII field name) is passed to the logger). Seed data includes minors, so this is aggravated pii-minor exposure (§3).
  **Fix:** Log only non-PII identifiers, or pass the payload through app.privacy.redact().


error: recipe `review` failed with exit code 1
```

## `just review feature/analytics-archive` (exit 1)

```
# Quality gate — `feature/analytics-archive`

**Decision: ⛔ BLOCK**

- **S1 — blocks merge** · `app/archive.py:12` · retention/missing-category (deterministic)
  New persisted copy of personal data (birthdate, full_name) with no category declared in app.privacy.RETENTION_DAYS. Seed data includes minors (max 90 days without a documented legal basis) (§4).
  **Fix:** Declare a RETENTION_DAYS category (≤90 days for minors unless a legal basis is documented in the PR) and store only the fields actually needed.

- **S1 — blocks merge** · `app/archive.py:12` · pii/leaves-service (AI, confidence 0.95)
  Minors' personal data (full_name, birthdate) is copied into an analytics archive explicitly built so the analytics team can 'cortar cohortes', i.e. data leaving this service, with no data minimization and no documented legal basis. This is pii-minor and blocks merge. [worked example: Trace: archive_progress(Student('s-001','Valentina Rojas','2013-04-02',is_minor=True), record) produces an ARCHIVE entry containing the minor's full_name and raw birthdate intended for the analytics team. Expected per §3: minors' data must not leave the service without minimization + documented legal basis; actual copies raw identifying fields with neither.]
  **Fix:** Minimize before copying: omit full_name/birthdate (use age bucket or hashed id), and document the legal basis in the PR before exposing any minor data to analytics.

- **S2 — blocks merge** · `app/archive.py:11` · testing/missing (AI, confidence 0.85)
  New core logic (archive_progress) and its wiring into record_progress ship with no tests. There is no assertion that archiving minimizes fields or respects retention, so a regression could not be caught. [worked example: The diff adds app/archive.py and a call in main.py but no test file. A test calling archive_progress(student, record) and asserting the stored dict excludes full_name/birthdate for minors would fail today — no such test exists, so broken minimization would go undetected.]
  **Fix:** Add tests covering archive_progress contents and (once minimized) that no raw PII of minors is stored.


error: recipe `review` failed with exit code 1
```
