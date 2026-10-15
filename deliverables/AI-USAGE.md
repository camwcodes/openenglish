# AI Usage

How AI (Claude Code, Opus 4.8) was used to build the AI Quality Gate. The curated
section below is the deliverable (tools, the 5 prompts that mattered, the discarded
output); the full working record — all 45 prompts and the interaction log — follows it
as the appendix it was curated from.

## Tools used

- **Claude Code** (Opus 4.8) — the only AI tool used, end to end: repo exploration,
  dev-env setup (Nix/direnv/just), planning, building the gate, and a fresh-context
  audit of the result before submission.

## The five prompts that mattered (curated from the full log below)

1. **The design seed (#29):** *"Draft a plan. I reviewed the PRs manually; I think the
   core is redaction of sensitive material — detect a Student object flowing into
   logging/notifications/etc. without being passed correctly. Scan the PRs to test
   this. Also suggest ideas I haven't thought of."* — My own read of the PRs set the
   direction; the AI's job was to pressure-test it. The redaction insight became the
   deterministic taint rule (`pii/log-exposure`), and "scan the PRs to test it" became
   the working method for everything after.
2. **Generalize, don't memorize (#31):** *"For LLM checks, don't hardcode PII fields —
   use what's defined in privacy.py."* — Became ADR 3, the one requirement that makes
   the gate work on the unseen PR: every check and the AI prompt read
   `PII_FIELDS`/`RETENTION_DAYS` from the branch under review.
3. **Shape pushback (#35–36):** *"Do we need entire programs? Why not separate commands
   + a runner? Feels over-engineered. Think deeply about a generic pattern, not the
   assignment's language."* — Killed the monolithic `gate/` program; produced the
   composable tools + JSONL findings contract + thin policy layer (ADR 1).
4. **The simplification rounds (#40–42):** *"This is over-engineered: `_diff` should be
   a prebuilt tool; coverage shouldn't be part of the gate — standard tool, own recipe,
   own CI runner. … For eval/: record what we thought the output should be in a markdown
   file — no tooling to compare answers."* — Three rounds of cutting AI-built scaffolding
   (ADRs 2, 6, 7): bought `unidiff`, pulled hygiene out of the gate, deleted the eval
   harness in favor of this answer key.
5. **Keeping the AI verifiable (#38):** *"Read AGENTS.md then notes/PLAN.md — source of
   truth, build to the plan, don't redesign. … Stop after each step; hand me the exact
   verification command."* — The working agreement: the AI builds, I verify each step
   myself before the next one.

## Discarded / corrected AI output (curated — the two we'd present)

- **Custom infrastructure where standard tools existed (log rows O + P).** The AI
  hand-rolled a ~170-line diff parser and defended it citing a GitHub comment-position
  mapping; on the second pushback it rewrote on `unidiff` — and the position mapping
  turned out to be **unused by every consumer**. Likewise it wired secrets/coverage/TODO
  scanning through the gate's findings pipeline; they're now plain gitleaks /
  pytest-cov+diff-cover / ruff TD003 invocations with their own CI steps. *Why
  discarded:* in both cases the AI's strongest justification evaporated under
  inspection — a feature nothing consumed, a contract layer adding no judgment.
  ADRs 2 and 6.
- **A stale assumption that survived two reviews (log row M).** The plan hardened the AI
  check with "temperature 0 for reproducibility" — the current Claude API rejects
  sampling parameters outright (400). Caught against live API docs at build time, before
  shipping a broken call. *Why it matters:* reviewed-and-approved AI output still
  carried a wrong premise; the replacement (strict JSON-schema output + a mechanical
  worked-example method + corroboration tiers in the trust policy) is a stronger
  determinism story than a sampler flag ever was. ADR 4.

---

## Appendix A — full prompt log (chronological, 2026-10-10 → 11)

Faithful paraphrase of every prompt I (the candidate) gave, in order. The curated
section above was drawn from this.

1. `/init` — extract/verify both zips (inspect, don't re-extract), read the challenge PDF,
   understand the assignment and help me understand it, then init.
2. Are you going to update AI-USAGE.md with notes, or what do you suggest to track that?
3. yeah (approve scaffolding AI-USAGE.md + DECISIONS.md as running logs).
4. Convert the PDF to markdown, keep the original.
5. Analyse the codebase; create a markdown file describing each file, the structure, how it
   works together, main coding structures/design — I'll read it then read the code.
6. How do I run the tests and start the local server?
7. I want to use direnv (installed) + Nix to set up the software (just python3), create the
   Python env and source it. What are my options first?
8. [chose] Flake + nix-direnv; Hybrid venv + pip.
9. Does `eval "$(nix print-dev-env)"` work now — am I good at this step?
10. [pasted terminal] `eval` → `zsh: read-only variable: LINENO`.
11. [pasted terminal] `which python3` → `/usr/bin/python3` (PATH not applied).
12. Create a markdown file explaining this setup — how it works, files used, choices made.
13. Update AGENTS.md with appropriate information.
14. Update README.md too, but keep the other method for non-Nix users.
15. I want something to put common commands in (not a Makefile). What are my options — alias?
    some program with config?
16. Let's go with just.
17. Go through the docs/README and update to use the new just commands.
18. Add a command to hit the health endpoint of the local dev server.
19. Add one for lessons too — what's a better name for both?
20. Also put curl into Nix (better reproducibility).
21. Add jq to Nix too.
22. I'm not sure — should the user choose to pipe to jq, or should we do it for them?
23. Create one for `GET /students/{id}/progress` — can just take the id as an argument?
24. I tested. (declined my re-verify)
25. What are the options for a just command to POST?
26. option 2 please.
27. Just give me the command to test. (declined my re-verify)
28. Back to the project — summarize what I'm supposed to do again.
29. Draft a plan. I reviewed the PRs manually; I think the core is redaction of sensitive
    material — detect a Student object flowing into logging/notifications/etc. without being
    passed correctly. Scan the PRs to test this. Also suggest ideas I haven't thought of.
30. What is a sink and taint?
31. I like the three types (Deterministic, AI, architecture). Explain mutation testing. Secret
    scanning + TODO scanning: yes. For LLM checks, don't hardcode PII fields — use what's
    defined in privacy.py. Not sure about retention — what could go wrong? Update the plan.
32. How will this work? More deterministic testing, but it's a PR scanner. Maybe scan for
    missing tests, or harden base libraries (logger) and use LLM to check it's called
    correctly. Note extra out-of-scanner changes for the interview. Any external tools?
33. Use the secrets scanner + code coverage, in the scanner and as just dev tools. Unsure about
    mutation but open. Update the plan.
34. I don't understand the file structure. Could we use skills? What's a different structure?
    Same code runnable by devs (just) and by CI.
35. Still unsure — do we need entire programs? Why not separate commands + a runner? Feels
    over-engineered. Think deeply.
36. Do we have to call it gate/? Some checks are useful outside the gate — maybe a scripts
    folder. Think deeply about a generic pattern, not the assignment's language.
37. Go with your pick (`checks/`). Update the plan. Save my prompt list + track my concerns/
    push-backs/questions/changes; I'll clear context then have you review the plan.

### Session 2026-10-11 (build)

38. Read AGENTS.md then notes/PLAN.md — source of truth, build to the plan, don't redesign.
    Build in order: `_diff.py` → findings contract → bought checks (gitleaks,
    pytest-cov/diff-cover) → `ai_review.py` (structured output, worked-example prompting,
    policy read from the branch, graceful no-key degradation) → deterministic checks →
    `decide.py` (AI-S2 as a policy switch the eval decides) → `eval/` → CI + docs.
    Stop after each step; hand me the exact verification command.
39. Step 1 works. This feels like something premade might cover (diff parsing) — note that
    pushback. Continue through the remaining steps while I'm away.
40. This is over-engineered: `_diff` should be a prebuilt tool; coverage shouldn't be part
    of the gate — standard tool, own `just` recipe, own GitHub Actions runner. Same for
    secrets and TODO: separate.
41. Still too complicated: scope `checks/` to a pii-checker; what are eval/ground_truth
    and eval/score?; severities — weren't the requirements just warn-or-danger?; the
    output is hard to read.
42. For eval/: record what we thought the output should be in a markdown file — no
    tooling to compare answers. The PII checker should be like real life: a tool we run
    locally and in CI. Then I have a conversation with the interviewer.
43. I meant rename the directory to pii-checker; one file for AI tooling, one for
    deterministic checks. Pull the ai_reviewer prompt into a markdown/text file. And
    double-check the deterministic checks really can't be done by existing lint tooling.
44. Why is decide.py outside? I want a just command for each check, a combined one
    (lint, coverage, pii), a separate pii command, a GitHub Actions workflow running the
    checks one at a time, and the pii checker should exit with error above a severity
    threshold — make it a command-line argument.
45. I shouldn't need `-m pii_checker.decide` — just `-m pii_checker`; add a __main__.

---

## Appendix B — interaction log: concerns, push-backs, questions, changes

The signal behind the prompts — what I challenged and what changed as a result.

| # | Type | What | Resolution / change |
|---|------|------|---------------------|
| A | push-back | Don't change things outside the project (tried `nix profile install` + edit global `~/.config/direnv/direnvrc`). I manage my system with Nix declaratively. | Switched to project-local only: flake + `.envrc` using `eval "$(nix print-dev-env)"`; nix-direnv left for me to add declaratively. Saved to memory. |
| B | correction | Root `CLAUDE.md` was drafted with full content. | House rule: real content in `AGENTS.md`, `CLAUDE.md` = thin pointer. |
| C | technical | Manual `eval "$(nix print-dev-env)"` in zsh → `LINENO` warning, PATH not applied. | Root cause: bash-targeted script in zsh. Fixed by loading via direnv/`.envrc` (runs in bash). |
| D | question | What is sink / taint? | Clarified: taint = tracking PII from source; sink = where it escapes (log/notify/persist/response). |
| E | design | jq: let the user pipe, or auto-pipe for them? | Auto-pipe `| jq .` — jq is TTY-aware (pretty interactively, plain JSON when piped), so no composability lost. |
| F | workflow | Prefer to run verification myself ("I tested", "just give me the command"). | I hand over commands instead of auto-running checks. Saved to memory. |
| G | change | `just prs` / `just diff` were thin git wrappers. | Dropped; raw git is clearer. |
| H | requirement | LLM must not hardcode PII fields. | Source of truth = `app/privacy.py` `PII_FIELDS`, injected into the prompt and read by the taint check. |
| I | push-back | A monolithic `gate/` program felt over-engineered. | Redesigned to composable commands + a JSON-lines findings contract + thin `decide.py`. Saved to memory. |
| J | push-back | Don't name things after the assignment ("gate"). | Generic structure: `checks/` (mechanism) vs `decide.py`/`eval/` (policy); "gate" only in docs. |
| K | open | Mutation testing — unsure. | Kept optional/stretch (only earns its keep on `streaks`); parked in DECISIONS.md at build time. |
| L | push-back | `checks/_diff.py` hand-rolled — isn't there something premade (`unidiff`)? | Recorded as ADR 6: kept custom (the GitHub position mapping is custom either way; zero extra dep); swap path documented. |
| M | correction | notes/PLAN.md's "temperature 0" hardening turned out impossible — current Claude models (Opus 4.7+) reject sampling params with a 400. | Caught against live API docs at build time, before shipping a broken call. Replaced by structural determinism (JSON schema output + mechanical worked-example method + corroboration tiers); ADR 4. |
| N | prediction-check | notes/PLAN.md asserted the taint check would MISS `support-context`'s cross-module helper flow (the "known FN"). | The one-hop PII-carrying-function pass catches it; smoke run on the 8 branches disproved the plan's prediction. EVAL.md keeps the disproven prediction for honesty. |
| O | push-back ×2 | `_diff.py` hand-rolled despite `unidiff` existing; AI defended it citing a position-mapping feature. | On the second pushback: rewrote on `unidiff` — and the position mapping turned out to be UNUSED by every consumer. The AI's build-justification was a feature nothing needed. ADR 6. |
| P | push-back | AI wired secrets/coverage/TODO through the gate's findings pipeline. Over-engineered: these are standard tools with standard CI patterns. | Pulled out of the gate entirely: `just secrets`/`coverage`/`todos` wrap gitleaks, pytest-cov+diff-cover, ruff TD003; each gets its own CI job (`pr-hygiene.yml`, since consolidated into `checks.yml` as sequential steps). Gate keeps only policy/judgment checks. ADR 2. |
| Q | question | What are S1/S2 — weren't the requirements warn-or-danger? | Clarified: S1/S2/S3 are TEAM-STANDARDS.md §6's own scale (S1/S2 block, S3 comments); warn-vs-danger ≈ the decision (comment vs block), which decide.py outputs. Reports now spell out the meaning ("S1 — blocks merge"). |
| R | push-back | eval/ (ground_truth.yaml + score.py) is tooling for a comparison that's really a conversation; three one-rule check files too complicated; output hard to read. | Deleted eval/ — answer key + hand-tallied results live in EVAL.md. Merged the three checks into one tool with gitleaks-like semantics (TTY-readable / JSONL piped / exit 1 on findings); later renamed to `pii_checker/deterministic.py`. decide.py report switched from a wide table to a readable list. ADR 7. |
| S | verify-request | Double-check the deterministic rules can't be existing lint tooling (ruff plugin, bandit, semgrep). | Checked: ruff/flake8/bandit = fixed per-file rules, can't read PII_FIELDS from the branch or see the diff. Semgrep could host the direct-attribute slice of rule 1 (via a rule generator + `--baseline-commit`), but the helper-hop needs the paid Pro engine, and rules 2–3 are cross-file diff-level joins pattern matching can't express. Custom AST stands. ADR 8. |
| T | design | decide.py shouldn't sit at repo root; wants per-check just commands + a combined one + checks run one at a time in CI + a severity threshold flag on the pii checker. | decide.py moved into `pii_checker/` (entry: `python -m pii_checker` via `__main__.py`); `--fail-on S1\|S2\|S3\|none` added (default S2 = §6's blocking severities, exposed as `just pii-check <branch> <severity>`); `just check-all` = lint + coverage + pii-check; `checks.yml` runs each check as its own sequential step using the same just commands. |

---

## Appendix C — all correction/discard candidates

The full set the curated pair above was chosen from, with the "why I distrusted it"
color:
- **(A)** AI reached outside the project to install/configure system-level tooling; corrected
  to a project-local, declarative-friendly setup. *Why it matters:* the AI's default
  ("just install it") conflicts with a Nix-managed system; the fix keeps the repo portable
  and the user's system untouched.
- **(I/J)** AI proposed a monolithic, assignment-named program; corrected to a composable,
  generically-named toolbox. *Why it matters:* the checks are reusable dev tools; coupling
  them to a throwaway "gate" framing would have made them less useful and harder to reason
  about.
- **(B)** AI put full guidance in `CLAUDE.md`; corrected to the thin-pointer house rule.
- **(O/P)** AI built custom infrastructure where standard tools existed — a hand-rolled
  diff parser (defended with a feature that turned out to be unused) and gate-wrapped
  secrets/coverage/TODO checks. *Why it matters:* the strongest argument for each custom
  piece evaporated under inspection (`position` mapping had zero consumers; the hygiene
  wrappers added a contract layer but no judgment). Discarded for `unidiff` + plain
  tool invocations with their own CI jobs.
- **(M)** The reviewed-and-hardened plan itself contained AI output that had to be
  discarded at build time: "run the LLM at temperature 0" — the current API rejects the
  parameter entirely. *Why it matters:* a design reviewed twice still carried a stale
  assumption; checking against live API docs before implementation caught it, and the
  replacement (schema-constrained output + worked-example method + corroboration tiers)
  is a stronger determinism story than a sampler flag ever was.
