# AI Quality Gate — Build Plan

> **Revised at build time (2026-10-11):** narrowed repeatedly on user pushback —
> secrets/coverage/TODO are **standalone tools with their own CI jobs**, not gate checks;
> diff parsing is bought (`unidiff`); the three deterministic checks merged into one
> tool in a renamed package (`pii_checker/deterministic.py`, prompt extracted to
> `pii_checker/prompt.md`); and the `eval/` harness was dropped — `deliverables/EVAL.md` holds the
> answer key and hand-tallied results. See deliverables/DECISIONS.md ADR 2, 6, 7, 8; this file is
> kept as the original design record.

We build a set of **checks** (reusable analyzers that emit *findings*) and a thin **policy**
layer that turns findings into a **decision** (block / comment / approve) and an **eval** that
scores it. The assignment's "AI Quality Gate" is the *composition* of these — the word "gate"
lives only in docs, not in the code layout.

Mechanism vs policy:
- **Checks (mechanism)** — independent dev tools, each runnable alone, each prints findings as
  JSON lines. Useful with or without the gate (manual, CI, pre-commit).
- **Policy (the gate)** — `decide.py` (trust policy) + `eval/` (metrics). Small, assignment-specific.

Single source of truth for sensitive data: **`app/privacy.py`** (`PII_FIELDS`,
`RETENTION_DAYS`), read from the branch under review — never hardcoded in checks or prompts.

This mirrors a well-worn pattern (linters → findings → a diff-aware reporter/policy; cf.
SARIF, reviewdog). Our findings format is a minimal, SARIF-lite JSON line.

---

## How it works (flow on one PR)

1. **Diff** — `git diff main...<branch>` → changed files, added lines, hunk line numbers.
2. **Context** — post-change content of changed files + `app/privacy.py` from the branch
   (to read `PII_FIELDS` / `RETENTION_DAYS`).
3. **Run checks** — each check reads the branch/diff and prints findings (JSON lines).
   Deterministic checks set `confidence=1.0`; the AI check adds judgment findings.
4. **Decide** — `decide.py` reads all findings on stdin, dedupes, maps to severity, applies
   the trust policy → report (markdown + JSON) + exit code.
5. **Eval** — `eval/score.py` runs the above over all 8 branches and compares to ground truth.

The checks are static analyzers over diffs; the one dynamic check is coverage (it runs the
PR's tests). Nothing else runs the service.

---

## Checks catalog

Each is a standalone command in `checks/`, emitting the findings contract. Deterministic
unless marked AI.

| Check | Kind | Tool (build/buy) | Catches | Std |
|-------|------|------------------|---------|-----|
| `secrets` | det | **buy — gitleaks** | `email-reminders` (SendGrid key) | §5 |
| `coverage` | det | **buy — pytest-cov + diff-cover** | logic change with no test covering it (the 4 no-test PRs) | §2 |
| `pii_taint.py` | det | **build — AST**, reads `PII_FIELDS` | `mobile-sync-visibility`, `support-context`, `analytics-archive` | §3 |
| `todo.py` | det | build — regex | `email-reminders` (TODO) | §1 |
| `retention.py` | det | build — AST | new student/PII collection w/ no `RETENTION_DAYS` entry → seeds `analytics-archive` | §4 |
| `safety_config` | det | build — diff check | PR edits `PII_FIELDS`/`RETENTION_DAYS` (weakening guardrails) | §3/§4 |
| `mutation` *(optional)* | det | buy — mutmut | `streaks` (tests present but decorative) | §2 |
| `ai_review.py` | **AI** | Claude API, structured output | logic correctness (`progress-percentage`), test meaningfulness, minimization/legal basis, minor aggravation | §2/§4/§6 |

Test-quality division of labor: **coverage** = missing tests; **mutation** = weak tests
(`streaks`); **AI** = wrong tests (`progress-percentage` asserts the wrong value).

**False-green caveat (the core risk).** On the two subtle logic cases (`streaks`,
`progress-percentage`) the deterministic layer is not silent — it goes *green*: a test exists
and `diff-cover` sees the changed line executed, so coverage reports "fine." Detection there
falls **entirely on the AI check**, on exactly the "subtle" cases the brief planted and will
replicate on the unseen PR. So the AI check is load-bearing, not a nice-to-have — harden it
(below) and keep `mutation` as its deterministic backup rather than cutting it first.

The AI check is given the standards text, the branch's `PII_FIELDS`/`RETENTION_DAYS` values,
the diff, file context, and the deterministic findings as hints. It reasons — it does **not**
hunt field names or key regexes (that's the deterministic checks' job).

### Hardening the AI check (because it's load-bearing)

- **Temperature 0.** A gate emits block/approve; the same diff must yield the same verdict
  every run. Default-temp sampling can flip `streaks`/`progress-percentage` between runs —
  non-reproducible blocks are both a DX failure and a credibility failure in the live demo.
- **Force worked-example reasoning for logic/test findings.** The prompt makes the model
  *trace a concrete input* ("evaluate `current_streak` on dates ending today; state the
  returned value" / "state what value the test asserts and whether it would change if the
  bug were absent"). This is what surfaces off-by-one and wrong-assertion tests — not a
  general "review this diff" instruction.
- **Two trust tiers in one check.** (a) PII/minimization/retention judgments are usually
  *corroborated* by a deterministic finding → high trust. (b) Logic/test-quality judgments
  on `streaks`/`progress-percentage` are *uncorroborated* (no deterministic signal) → this is
  the FP/FN-prone path; the eval measures it explicitly, and the trust policy treats an
  uncorroborated AI-only S2 more conservatively than a corroborated one.
- **Escalation, only if eval shows flakiness:** add k=3 majority voting (temp ~0.4) for the
  uncorroborated logic findings. Not upfront — temp-0 + worked-example first; add voting only
  if the eval run proves the single call is unstable. (Keeps it simple; avoids over-building.)

## Findings contract (the only shared thing)

Every check prints one JSON object per finding, per line (JSONL):
```
{ "severity": "S1|S2|S3", "file": str, "line": int, "rule": str,
  "message": str, "suggested_fix": str, "source": "deterministic|llm", "confidence": float }
```
That convention is the whole interface — it lets checks mix languages (gitleaks binary,
Python AST, tool wrappers) and still compose.

**`checks/_diff.py` is foundational, not optional.** Three–four Python checks all need the
same primitive: changed files, added lines, post-change file content from the branch, and a
new-file-line → diff-hunk-line mapping (findings need diff-relative line numbers for a PR
comment). Write it once; otherwise the branch/diff plumbing gets copy-pasted across checks and
drifts. Budget it as real work (not ~10 lines) — the line-mapping across AST / diff-cover /
gitleaks outputs is the fiddly part.

## Policy: `decide.py` (trust policy)

Reads JSONL on stdin → dedupe → severity map → decision. The policy is chosen **a priori**
from the severity model (not tuned on 8 PRs — see Eval), and the eval *validates* it:

- **block** on any S1 (secrets / PII exposure / minor retention-minimization auto-block);
- **block** on S2 that is **deterministic** (coverage/mutation) **or** AI-logic that is
  **corroborated** by a deterministic signal;
- **uncorroborated** AI-only S2 (e.g. `streaks`, `progress-percentage`): block-vs-comment is
  **decided by the eval**, not assumed. This is the one FP-prone tier — run it both ways over
  the 8 PRs and pick: block if precision holds (catches the two planted logic bugs), comment-
  only if the AI false-blocks a clean PR. Whichever we ship, `deliverables/EVAL.md` shows the metric that
  justified it;
- **comment** on S3; **approve** if clean.

**Graceful degradation:** no API key → deterministic-only run still produces findings (and
the two uncorroborated logic cases degrade to *undetected* — state this honestly rather than
implying full coverage without the LLM).

## Eval → `deliverables/EVAL.md`

`eval/score.py` runs the gate over all 8 branches → findings JSON, compares to
`eval/ground_truth.yaml` → precision & recall (overall + per severity) and PR-level
block/approve accuracy. Auto-lists FP/FN; write up ≥1 each.

Be honest about what n=8 can and can't do:
- **Validate, don't tune.** ~8 PRs / ~10–12 findings is too small to fit a confidence
  threshold without overfitting, and the reviewer's hidden key differs from ours. Metrics
  *check* the a-priori policy (above); they don't *derive* a magic number. Say this explicitly
  rather than presenting a tuned threshold as "justified by metrics."
- **Mark ambiguous ground truth, reason both ways.** Some labels are genuinely debatable and
  affect the score: `streaks` off-by-one (real bug vs. a definitional choice — if the
  reviewer's key says "sound," our flag is a **false positive**), TODO-without-ticket severity,
  and whether `email-reminders`' direct `email` logging is a *separate* S1 from the committed
  key. `ground_truth.yaml` should flag these as ambiguous, not assert them.
- **Expect the FP from the AI, not the taint check.** The most likely false positive is the
  AI over-reaching on the two *clean* PRs (`lessons-pagination`, `score-validation`); the known
  FN is taint missing `support-context`'s cross-module helper flow. Write up one of each.

## Out-of-scanner recommendations → `REVIEW-NOTES.md`

What a good reviewer recommends but the gate doesn't implement:
- Build redaction into the logging layer (and notifier) so it can't be forgotten (preferred
  fix — DECISIONS.md). Add base-library tests proving the logger redacts PII.
- Switch `redact()` (blocklist, fails open) → allowlist `pick(obj, [safe_fields])` (fails
  closed, DRY). Note the current `redact({...})` call is a no-op on a non-PII dict.

---

## Layout

```
checks/                 # reusable analyzers — each standalone, emit findings (JSONL)
  secrets               #   gitleaks wrapper            (generic)
  coverage              #   diff coverage               (generic)
  todo.py               #   TODO-without-ticket         (generic)
  pii_taint.py          #   PII → sink taint            (service policy; reads PII_FIELDS)
  retention.py          #   retention / minimization    (service policy)
  ai_review.py          #   Claude review               (AI)
decide.py               # findings (stdin) → severity + block/comment/approve + report
eval/
  ground_truth.yaml     # manual classification of the 8 PRs
  score.py              # run over 8 branches → precision/recall + FP/FN
reports/                # generated per-PR JSON + markdown (gitignored)
.github/workflows/quality-gate.yml   # CI runs the SAME `just review` (required — brief asks for CI)
```

## `just` recipes (checks double as dev tools; CI calls the same)

- `just secrets` · `just coverage <branch>` · `just todo <branch>` · `just pii <branch>` ·
  `just retention <branch>` — run any single check
- `just review <branch>` — run all checks | `decide.py`  (CI runs this identical line)
- `just eval` — `eval/score.py`
- `just mutation <branch>` *(optional)*

## Dependencies (kept separate so the service's `requirements.txt` stays CI-identical)

- **Nix flake devShell:** add `gitleaks`.
- **`requirements-dev.txt` (new):** `anthropic`, `coverage`, `pytest-cov`, `diff-cover`,
  (optional `mutmut`). `.envrc` installs both `requirements.txt` and `requirements-dev.txt`.

## Time budget (4–5h) & priority

| Time | Work |
|------|------|
| 0:00–0:30 | scaffold `checks/` + findings contract + `eval/ground_truth.yaml` + deps |
| 0:30–1:15 | wire bought checks: `secrets` (gitleaks), `coverage` (pytest-cov/diff-cover) + recipes |
| 1:15–2:15 | `ai_review.py`: diff plumbing + prompt + structured output |
| 2:15–3:15 | build `pii_taint.py`; then `todo.py` + `retention.py` + `safety_config` |
| 3:15–3:45 | `decide.py` (dedupe + trust policy + report) + `just review` chain + CI |
| 3:45–4:30 | `eval/score.py`: metrics + FP/FN → draft `deliverables/EVAL.md` |
| 4:30–5:00 | polish README/AI-USAGE/DECISIONS/REVIEW-NOTES, end-to-end run, buffer |

**If short on time** (park in DECISIONS.md): ship `ai_review` (hardened: temp-0 +
worked-example) + `decide` + eval + minimal CI (graded core) → then `secrets` + `coverage` +
`pii_taint` → keep `mutation` (it's the only deterministic net under `streaks`). **Cut
`safety_config` and `todo` first** — each guards thin ground (`safety_config` matches 0 of the
8 PRs; `todo` is one S3 regex). Do **not** cut `mutation` first.

## Open decisions

- **Uncorroborated AI-only S2 → block or comment:** decided empirically from the eval run
  (precision on the 8 PRs), not assumed up front. See `decide.py`.
- `mutation`: kept as the deterministic backup for `streaks` (not the first cut). Open
  question is only whether it earns its runtime vs. relying on the hardened AI check alone.
- `ANTHROPIC_API_KEY` availability (gate builds deterministic-first regardless).
- Whether to emit real SARIF (for GitHub code-scanning) vs our JSONL (default JSONL for now).
