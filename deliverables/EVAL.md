# EVAL — answer key for the 8 open PRs, and how the gate scored against it

This file **is** the ground truth — what we believe each PR gets wrong, written down
before comparing with the reviewer's hidden key (that comparison is a conversation at
the session, not a script). To reproduce the gate's side, run the tools and hold the
output against the tables below:

```bash
just review <branch>     # the gate: pii-check + AI review -> decision + report
just pii-check <branch>  # the deterministic PII/retention tool alone (exit 1 = findings)
just secrets <branch>    # gitleaks         (standalone hygiene, own CI job)
just coverage            # diff-cover       (run on the branch's checkout)
just todos               # ruff TD003       (non-blocking)
```

## Scope: who owns which standard

Standard hygiene is off-the-shelf tooling run as its own sequential CI steps
(`checks.yml`, one job, one step per tool — same `just` command as locally), not
part of the gate: **gitleaks** (§5 secrets), **pytest-cov + diff-cover** (§2 missing
tests), **ruff TD003** (§1 TODOs). The gate owns what needs service policy or judgment:
**pii-checker** (§3 PII→log, §4 retention, guardrail edits) and **ai_review** (§2 logic
correctness and test *effectiveness*, §3/§4 minimization and legal-basis judgment).
"The PR is blocked" = any required CI job fails (branch protection), not one process's
verdict.

## Answer key

Severities are TEAM-STANDARDS.md §6's own scale: **S1/S2 block merge, S3 is a comment.**
*(ambig.)* = genuinely debatable call, argued both ways below rather than asserted.

| PR | Expected outcome | Expected findings (owner) |
|----|------------------|---------------------------|
| `feature/lessons-pagination` | ✅ approve | none — validated params, effective tests |
| `feature/score-validation` | ✅ approve | none — correct validation, effective tests |
| `fix/mobile-sync-visibility` | ⛔ block | S1 `app/main.py` logs `full_name`+`email` directly, pii-minor (pii-checker — it reports one finding per log call, naming the first field hit, `.full_name`) |
| `feature/support-context` | ⛔ block | S1 `app/main.py` helper builds PII dict → logged, indirect (pii-checker); *(ambig.)* S1 minors' data to support tooling w/o minimization (AI) |
| `feature/email-reminders` | ⛔ block | S1 committed SendGrid key (gitleaks); *(ambig.)* S1 logs recipient email (pii-checker, 0.8); *(ambig.)* S2 untested scaffolding (diff-cover); S3 ticketless TODO (ruff TD003) |
| `feature/streaks` | ⛔ block | *(ambig.)* S2 off-by-one — activity *today* never counts (AI); S2 decorative tests — assert `isinstance`/`>=0`, can't fail on breakage (AI) |
| `feature/analytics-archive` | ⛔ block | S1 indefinite PII copy incl. minors (`full_name`, `birthdate`, `is_minor`), no RETENTION_DAYS category (pii-checker) |
| `fix/progress-percentage` | ⛔ block | S2 `round→int` truncation + no-lessons 0→100 (AI); *(ambig.)* S2 new test asserts the wrong value, locking the bug in (AI) |

## How the gate actually scored (hand-tallied; deterministic runs 2026-10-11, keyed AI runs 2026-10-15)

**Deterministic layer (pii-checker, no API key):** 4 of 4 expected deterministic
findings found — `mobile-sync` direct log, `support-context` indirect helper log,
`analytics-archive` retention, `email-reminders` email log (the ambiguous one) — with
**zero false positives** on the two clean PRs. Standalone tools verified by hand:
gitleaks finds the SendGrid key; diff-cover reports 0% on `app/notifications.py`;
ruff TD003 fires on the ticketless TODO.

**Per-PR decisions without the AI:** 6 of 8 correct. The two misses are `streaks` and
`progress-percentage` — the **false-green zone**: tests exist and the changed lines are
executed, so no deterministic tool (ours or standard) can fire. Those two ride entirely
on `ai_review.py`; without an API key they degrade to *undetected*, and `pii_checker/decide.py`'s
report says so explicitly rather than implying full coverage.

**With the AI (keyed runs of 2026-10-15, all 8 branches — verbatim transcript in
[RUN-LOG.md](RUN-LOG.md)):** the AI caught both planted logic bugs, each with the worked
example the prompt demands — `streaks` S2 `logic/incorrect` (0.92; traces activity on the
20th–22nd with today=22nd → code returns 2, intended 3) plus S2 `testing/ineffective`
(0.95; shows each assertion passes regardless of the bug), and `progress-percentage` S2
`logic/incorrect` (0.88; 2 of 3 lessons → 66 not 67; empty catalog with 3 completed
records → 100, intended 0) plus S2 `testing/ineffective` (0.85; the new test asserts the
buggy 100, so fixing the code would *fail* it). `lessons-pagination` stayed clean
(APPROVE, no findings). `score-validation` drew one S3 `quality/style` (0.60):
`int(payload.get("score", 0))` turns non-numeric input into a 500 — comment-only, and
substantively real (the same defect was recorded in REVIEW-NOTES.md §3 *before* this
run). On the four deterministically-blocked PRs the AI added the judgment its prompt
asks for: pii-minor aggravation findings naming the specific minors (1.00/0.95/0.85),
an independent re-find of the committed SendGrid key (`secrets/committed`, 0.98 —
defense in depth beside gitleaks), the archive copy judged as minors' data leaving the
service without minimization or legal basis (`pii/leaves-service`, 0.95), and the
untested archive wiring (`testing/missing`, 0.85). The ambiguous `support-context`
leaves-service call came back framed as `pii/minor-exposure` on the helper instead —
same substance, different slug.

## Precision & recall (hand-tallied against the answer key above)

Scored per layer, because "the gate" is a composition (see Scope): finding-level counts
use the answer key's expected findings per owner; decision-level uses the per-PR outcome.

| Layer | Expected findings (owned) | Found | FP | Precision | Recall |
|-------|--------------------------|-------|----|-----------|--------|
| pii-checker (deterministic) | 4 | 4 | 0 | 4/4 = **1.00** | 4/4 = **1.00** |
| Standalone hygiene (gitleaks, diff-cover, TD003) | 3 | 3 | 0 | 3/3 = **1.00** | 3/3 = **1.00** |
| ai_review (logic, test effectiveness, minimization) | 5 | 5 | 1\* | 10/11 = **0.91** vs key\* | 5/5 = **1.00** |

\* The AI emitted 11 findings total: the 5 the answer key expected of it, 5
aggravation/corroboration findings on already-blocked PRs (the pii-minor aggravations
its prompt explicitly requests, the committed key, the untested archive wiring — all
true, counted as correct), and 1 finding not in the key: the `score-validation` S3,
counted as the false positive for honesty even though it is substantively real
(pre-recorded in REVIEW-NOTES.md §3) and comment-only.

**Decision level (block vs. approve), without the AI:** 6 of 8 PRs decided correctly
(**accuracy 0.75**). All 4 blocks were correct (**block precision 1.00**); of the 6 PRs
that should block, 4 were blocked (**block recall 0.67**). The two misses are the
false-green zone (`streaks`, `fix/progress-percentage`) — AI-owned by design; without a
key they degrade to *undetected* and the report says so.

**Decision level, with the AI (runs of 2026-10-15):** block/no-block correct on **8/8**
PRs — **block precision 1.00** (6 blocks, all warranted), **block recall 6/6 = 1.00**
(the two false-green PRs now block on AI S2). One divergence inside the non-blocking
tier: `score-validation` decided *comment* instead of *approve*, on the S3 above — no
false block, and the finding is real. No uncorroborated AI-only S2 appeared on either
clean PR, so the `--ai-s2 block` default stands (trust policy below).

## Trust policy (validate, don't tune)

Fixed a priori from §6 (see `pii_checker/decide.py`): block any S1; block S2 that is deterministic
or corroborated; S3 comments. n=8 is far too small to fit thresholds, so the one knob
we leave to evidence is **uncorroborated AI-only S2** (`--ai-s2 block|comment`,
default `block`): if the AI catches the two planted logic bugs without false-blocking
the clean PRs, `block` stands; if it over-reaches on clean PRs, flip to `comment`.

**Measured (keyed runs, 2026-10-15 — RUN-LOG.md):** both planted logic bugs caught as
AI-only S2 at 0.85–0.95, each with a worked example; **zero S2 findings on the clean
PRs** → **`block` stands.** The one clean-PR finding was an S3 (comment-only, and a
real defect — see FP analysis), which this switch does not govern: S3 never blocks
regardless of the setting.

## False positive / false negative analysis (deliverable: ≥1 each)

**False negative — `fix/progress-percentage`, logic bug (no-key runs).** The PR ships
`test_progress_percentage_no_lessons` asserting `percentage == 100` for an empty
catalog — the *bug is enshrined as the expected value*. Even the coverage job goes
green: the changed line is executed by a passing test; no tool can know 100 is the
wrong number. The only signals are semantic (`round()`→`int()` changes 3/7 lessons from
43 to 42; no-lessons flips 0→100). This is why the AI check is load-bearing and why its
prompt demands a worked example instead of a generic "review this diff".

**False positive (most likely candidate) — `email-reminders` email log, confidence 0.8.**
The pii-checker flags `logger.info("reminder queued to=%s ...", email)` by variable
*name*: `email` matches a `PII_FIELDS` entry but is just a parameter name. Here it
genuinely is the student's email (we lean "real", marked ambiguous), but the same
heuristic would flag `email_count` — so the rule emits at 0.8 instead of 1.0 and is the
checker's one FP-prone rule. The attribute- and helper-based rules carry no such risk.

**False positive, measured (AI keyed run) — `score-validation` S3, confidence 0.60.**
The pre-registered criterion above says any AI finding on a clean PR counts as a false
positive, and exactly one materialized: S3 `quality/style` — `int(payload.get("score",
0))` turns non-numeric input into a 500 instead of a 422. Against the answer key it is
an FP; substantively it is true — REVIEW-NOTES.md §3 recorded the same defect before
the keyed run — and at comment severity it cost nothing at the decision level. Honest
reading: the AI's one over-reach landed on a real issue at a defensible severity, which
is the FP profile you want.

**Prediction disproven (kept for honesty).** notes/PLAN.md expected the taint pass to *miss*
`support-context`'s cross-module helper flow. The one-hop "PII-carrying function" pass
catches it (`build_support_context()` reads `full_name`/`email`/`birthdate`; its call
site is logged), so the expected FN did not materialize.

## Ambiguous calls (argued both ways)

1. **`streaks` off-by-one** — counting starts at `today-1`, so activity today never
   counts, against the docstring's "terminando hoy". We call it a real S2; if the
   reviewer's key reads start-at-yesterday as intended, our flag is a FP and the
   expected outcome becomes `comment` (decorative tests still stand).
2. **`email-reminders` email log** — a second S1 beside the committed key, or subsumed
   by that incident? We flag it; defensible either way.
3. **`email-reminders` untested scaffolding** — 0% diff coverage on the new module vs
   the author's "scaffolding only, nothing is sent yet". S2 by the letter of §2, noise
   by intent.
4. **TODO severity** — `TODO: mover a config` points at the committed secret itself;
   arguably evidence for the S1 rather than a standalone S3.

## What 8 PRs can and cannot tell us

They can: show the deterministic layer has ~zero FP cost, confirm the severity→decision
mapping, and expose the false-green zone that motivates the AI check. One accepted
deterministic blind spot to name out loud: declaring *any* new `RETENTION_DAYS` category
switches the retention rule off for that diff (adequacy — the 90-day minor cap, the
legal basis — is deliberately the AI's call), so a keyless run of a PR that declares a
generous category *and* copies minors' data surfaces only the S3 guardrail-touched
comment. They cannot:
justify a numeric confidence threshold or promise the AI's FP rate on the unseen PR —
which is why the only tunable is the AI-only-S2 switch, and why every check reads
`PII_FIELDS`/`RETENTION_DAYS` from the branch under review instead of memorizing this
repo's values (generalize, don't overfit).
