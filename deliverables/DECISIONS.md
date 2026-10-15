# Decisions

Mini-ADRs: trade-offs made, and what was cut (with reasoning). ADRs 1–5 are the core
trade-offs; 6–8 record build-vs-buy reversals and verifications made along the way.
Running notes below the line are the raw working record the ADRs were promoted from.

## ADRs

### 1. Composable checks + JSONL findings contract, not a monolithic "gate" program

- **Context:** the assignment says "AI Quality Gate"; the obvious shape is one program.
  I pushed back twice (over-engineering; assignment-coupled naming).
- **Decision:** independent analyzers (the `checks/` package, since renamed
  `pii_checker/` — ADR 7), each a standalone CLI printing one JSON finding per line
  (`pii_checker/_findings.py` is the whole contract); `decide.py` = the only policy.
  `just review` is a 10-line pipe; CI runs the same recipe. "Gate" exists only in docs.
- **Consequences:** every check doubles as a dev tool (`just pii-check` alone), and
  the trust policy is swappable without touching detection. Cost: shared plumbing had to
  be factored deliberately (`pii_checker/_diff.py`, `pii_checker/_findings.py`) instead of living
  in one process. (Follow-up pushbacks narrowed this further — ADR 2, ADR 7.)

### 2. Standard hygiene stays OUT of the gate — off-the-shelf tools, own CI jobs

- **Context:** the first build wired secrets (gitleaks), diff coverage
  (pytest-cov/diff-cover) and TODO scanning through the gate's findings pipeline.
  User pushback: that's over-engineering — these are solved problems with standard
  CI patterns; wrapping them in our contract adds a layer and zero judgment.
- **Decision:** the gate owns only what needs service policy or semantics:
  the PII checker (small ASTs reading the branch's own `PII_FIELDS`/`RETENTION_DAYS`;
  initially three files, later merged — ADR 7) + `ai_review`. Hygiene runs as the tools
  themselves —
  `just secrets` (gitleaks), `just coverage` (pytest-cov + diff-cover), `just todos`
  (ruff TD003, selected via CLI flag so the service's lint config stays untouched) —
  each its own sequential step in `checks.yml`'s single job, same `just` command as
  locally (TODOs non-blocking: S3).
- **Consequences:** "blocked" at the standards level becomes *branch protection over
  required jobs* (the `checks` job + the `quality-gate` job), not one process's exit
  code — EVAL.md
  scopes gate metrics accordingly and verifies the standalone hits per tool. We lose
  one aggregated report covering everything; we gain three tools that behave exactly
  as every other repo uses them. The known limit is unchanged: coverage proves
  *execution*, not *assertion* — the false-green zone (`streaks`,
  `fix/progress-percentage`) rides entirely on the AI check.

### 3. Policy values are read from the branch under review, never hardcoded

- **Context:** my requirement — the gate must generalize to the unseen PR, and a PR can
  itself edit the policy.
- **Decision:** `PII_FIELDS` / `RETENTION_DAYS` are AST-parsed (never exec'd) from
  `app/privacy.py` at the branch tip (`load_policy` in `pii_checker/_diff.py`) and injected
  into the AI prompt; the pii-checker's guardrail rule separately flags PRs that weaken
  that file.
- **Consequences:** adding a PII field on main automatically retargets every check; the
  "PR weakens the guardrail" attack is covered. Cost: a PR that *deletes* a field is
  reviewed against its own weaker policy — which is exactly why the guardrail rule S1s it.

### 4. Planned "temperature 0" is impossible on current models — replaced, not silently dropped

- **Context:** notes/PLAN.md hardened the AI check with temp-0 for run-to-run reproducibility.
  The current Claude API (Opus 4.7+) **rejects** `temperature`/`top_p`/`top_k` outright
  (400), and temp-0 never guaranteed identical outputs anyway.
- **Decision:** determinism is pursued structurally instead: strict JSON-schema output
  (`output_config.format`), a mechanical review method in the system prompt (trace a
  concrete input; state what the assertion checks), rule slugs as a fixed vocabulary,
  and corroboration-aware trust tiers in `decide.py` so a wobbling AI finding can't flip
  a decision that deterministic evidence supports.
- **Consequences:** same-diff-same-verdict is now a property of the *policy*, not the
  sampler. Residual wobble is confined to the uncorroborated-AI-only-S2 tier, which is
  the tier the eval explicitly measures (and the escalation path — k=3 voting — is held
  back unless the eval proves instability, per notes/PLAN.md).

### 5. Uncorroborated AI-only S2: block-vs-comment is a measured switch, not an opinion

- **Context:** the one FP-prone tier; n=8 is too small to tune thresholds honestly.
- **Decision:** `pii_checker/decide.py --ai-s2 {block,comment}` (env `GATE_AI_S2`), default `block`.
  To pick: run the gate (with API key) over the 8 branches and hold the reports against
  EVAL.md's answer key — AI catches both planted logic bugs without false-blocking the
  clean PRs → keep `block`; AI over-reaches on clean PRs → flip to `comment`.
- **Consequences:** the policy choice ships with the evidence that justified it instead
  of a hand-wave; flipping it later is a one-flag change.
- **Resolution (2026-10-15, keyed runs over all 8 branches — deliverables/RUN-LOG.md):**
  the AI caught both planted logic bugs as AI-only S2 (0.85–0.95, worked examples) and
  emitted **no S2 on the clean PRs** — **`block` stands.** The single clean-PR finding
  was an S3 (real defect, comment-only; EVAL.md FP analysis), outside this switch's
  scope.

### 6. Diff parsing bought (`unidiff`), not hand-rolled

- **Context:** first build hand-rolled a ~170-line unified-diff parser in
  `pii_checker/_diff.py`, justified by a GitHub-comment *position* mapping `unidiff`
  doesn't provide. User pushback ×2: a prebuilt tool should do this.
- **Decision:** rewrite on `unidiff` (PyPI, mature). While doing it, noticed the
  position mapping was *unused* — findings carry plain file line numbers; nothing
  posts PR comments by position. Deleted it. `_diff.py` is now a ~90-line thin layer:
  `git diff` invocation, changed-files/added-lines dataclasses, `file_at()`.
- **Consequences:** one more (tiny, stable) dev dependency; far less owned parsing
  code. Lesson recorded in AI-USAGE.md: the hand-rolled version's main justification
  was a feature nothing consumed — the pushback was right.

### 7. The answer key is a markdown file, not a scoring harness; the checker is one tool

- **Context:** second round of user pushback: an `eval/` package (ground_truth.yaml +
  score.py computing precision/recall over 8 PRs) is tooling for a comparison that is
  actually a conversation with the reviewer; and three one-rule check files are
  complication without benefit.
- **Decision:** deleted `eval/` entirely — the per-PR expectations and the hand-tallied
  results live in EVAL.md as tables; reproduction = run `just review <branch>` and read.
  Merged `pii_taint`/`retention`/`safety_config` into one `pii_checker/deterministic.py` with
  real tool semantics (branch defaults to HEAD, readable on a TTY / JSONL piped,
  exit 1 on blocking findings — same contract as gitleaks/ruff).
- **Consequences:** ~200 fewer lines and one less concept (no scorer to explain); the
  cost is that re-tallying after a change is manual — acceptable at n=8, and the per-PR
  facts don't churn.

### 8. Double-checked: the deterministic rules can't ride on existing lint tooling

- **Context:** user asked to verify the custom AST rules aren't reinventing an
  existing linter (ruff/flake8 plugin, bandit, semgrep).
- **Findings:** ruff/flake8/pylint/bandit lint one file at a time against fixed rule
  sets — no diff-vs-base conditions, no rules parameterized by another file's runtime
  values, so they can't express any of the three rules without hardcoding `PII_FIELDS`
  (which ADR 3 forbids). **Semgrep is the closest fit** and could host part of rule 1:
  direct `logger.*(… $X.full_name …)` patterns, with `--baseline-commit` for
  diff-awareness — but (a) field names must be literal in the YAML, so we'd need a
  rule-*generator* reading privacy.py (custom code again, just moved); (b) the one-hop
  helper flow that catches `support-context` needs cross-function/cross-file taint =
  Semgrep's paid Pro engine; (c) rule 2 (added PII persist **and** no new
  RETENTION_DAYS key elsewhere in the same diff) and rule 3 (compare parsed policy
  values between base and branch) are cross-file, diff-level *joins* that pattern
  matching can't express at all.
- **Decision:** keep the ~200-line custom AST checker; it encodes exactly the
  service-specific semantics no off-the-shelf tool can. Revisit semgrep only if the
  rule count grows enough to justify a generator.

## Deliberately out of scope (per brief + timebox)

- Real deployment of the service, UI, dashboards, LLM fine-tuning (brief says skip).
- **Mutation testing (`mutmut`)** — the deterministic backup for `streaks`' decorative
  tests. Parked: the hardened AI check covers that case; mutmut's runtime (~minutes per
  branch) buys one corroboration signal. Revisit if the keyed eval shows AI instability
  on `testing/ineffective`. (notes/PLAN.md ranks it above `todo`/`safety_config` if time
  returns.)
- k=3 majority voting for AI logic findings — escalation only if the eval proves the
  single call unstable (notes/PLAN.md).
- Real SARIF output / GitHub code-scanning upload — JSONL is machine-comparable and
  enough for the eval; SARIF is an adapter away if wanted.
- Posting the report as a PR comment from CI — report is uploaded as a workflow
  artifact instead (no GitHub remote in the local flow).

---

## Running notes (raw working record — all resolved items promoted into the ADRs above)

### 2026-10-11

- **Build vs buy for diff parsing** — user pushback ×2; initially kept hand-rolled,
  then reversed on the second pushback. Resolved → **ADR 6** (bought `unidiff`; the
  justifying position-mapping feature turned out to be unused and was deleted).
- **Hygiene checks pulled out of the gate** — user pushback: coverage/secrets/TODO are
  standard tooling, not gate checks. Resolved → **ADR 2** (own `just` recipes + own CI
  jobs in `checks.yml`; gate keeps only policy/judgment checks).
- **Everything of ours lives in `pii_checker/`** (user direction, 2026-10-11 late):
  `decide.py` moved into the package, runnable as `python -m pii_checker`
  (`__main__.py`); the deterministic tool gained `--fail-on S1|S2|S3|none`
  (default S2 — §6's blocking severities) so its exit code is a tunable CI gate;
  `just check-all` = lint + coverage + pii-check; `checks.yml` runs each check as its
  own sequential step via the same just commands.

### 2026-10-10

- Docs convention: real guidance in `AGENTS.md`, `CLAUDE.md` = thin pointer (house rule).
- Review PRs via local `git diff main..<branch>`; no GitHub remote required. `open_prs.sh`
  is the evaluator's publish script, not part of running the gate.
- _Open questions to resolve as we build:_ gate dir layout (`gate/`?), LLM structured-output
  format (JSON schema for machine-comparable findings), which checks go deterministic vs.
  LLM, blocking threshold / trust policy, how CI consumes the diff.

- **Insight — PII redaction is opt-in, blocklist-based, and not DRY (root cause of the
  log-PII traps).** `app.privacy.redact()` must be called manually, so it's forgettable —
  which is exactly how `fix/mobile-sync-visibility` and `feature/support-context` leak PII to
  logs (they just don't call it). It's also a *blocklist* (`PII_FIELDS`) → **fails open**: a
  new PII field on `Student` leaks until added. And the one real call site rebuilds the dict
  by hand — `redact({"student_id": …, "lesson_id": …})` — which contains no PII fields, so
  `redact()` is effectively a no-op there; the real protection is the manual field selection.
  - _Better designs (for narrative / recommendations, NOT edits to the seed service):_
    (a) allowlist projection `pick(obj, [safe_fields])` → **fails closed** + DRY;
    (b) redaction built into logging via a structured-logging processor / `logging.Filter`
    that masks PII keys on every record → can't-forget + DRY.
  - _Preferred (user):_ **(b) — redaction built into the logging layer** (the central
    "router" every log record passes through), so it's automatic and impossible to forget,
    rather than relying on each call site to opt in. This is the recommendation we lead with.
  - _Gate payoff:_ a cheap deterministic check — "diff adds a `logger.*` call referencing a
    PII field (`full_name`/`email`/`birthdate`) or a `Student` object not wrapped in
    `redact()`/`pick()`" — catches the log-PII PRs without an LLM. Good "AI + deterministic"
    story and a strong root-cause talking point for the review session.
