"""Trust policy: findings (JSONL on stdin) -> decision (block / comment / approve).

Policy, chosen a priori from TEAM-STANDARDS.md §6 (validated against deliverables/EVAL.md's
answer key, not tuned on it):

  - block   any S1 (PII exposure, minor retention/minimization, weakened guardrails);
  - block   S2 from a deterministic check, or from the AI when corroborated by a
            deterministic finding (same rule group, same file);
  - S2 from the AI alone (uncorroborated — the FP-prone tier): block or
    comment is a POLICY SWITCH (--ai-s2 / $GATE_AI_S2); run the 8 branches and
    compare reports against deliverables/EVAL.md's answer key to pick.
  - comment on S3 only; approve when there are no findings.

Dedupe: identical (file, line, rule) keeps the highest-confidence copy; an AI
finding that repeats a deterministic (file, rule) is folded into it.

Usage:  cat findings.jsonl | python -m pii_checker --branch <branch>
        (the package's __main__; `python -m pii_checker.decide` works too)
Exit:   0 approve/comment, 1 block, 2 bad input.
Writes reports/<branch>.md and reports/<branch>.json (gitignored).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from pii_checker._findings import Finding, load

SEV_ORDER = {"S1": 0, "S2": 1, "S3": 2}


GROUPS = {  # corroboration works at group level: a deterministic privacy hit
    # (pii/retention) corroborates an AI privacy finding on the same file
    "pii": "privacy", "retention": "privacy", "secrets": "privacy",
    "logic": "correctness", "testing": "correctness",
    "quality": "quality",
}


def family(rule: str) -> str:
    return rule.split("/", 1)[0]


def group(rule: str) -> str:
    return GROUPS.get(family(rule), family(rule))


def dedupe(findings: list[Finding]) -> list[Finding]:
    best: dict[tuple, Finding] = {}
    for f in sorted(findings, key=lambda f: (f.source != "deterministic", -f.confidence)):
        key = (f.file, f.line, f.rule)
        folded = (f.file, f.rule)
        if key in best:
            continue
        if f.source == "llm" and any(
            k[:1] + (k[2],) == folded and v.source == "deterministic"
            for k, v in best.items()
        ):
            continue  # AI repeating a deterministic finding on the same file+rule
        best[key] = f
    return sorted(best.values(), key=lambda f: (SEV_ORDER[f.severity], f.file, f.line))


def corroborated(f: Finding, findings: list[Finding]) -> bool:
    return any(
        d.source == "deterministic"
        and d is not f
        and group(d.rule) == group(f.rule)
        and d.file == f.file
        for d in findings
    )


def decide(findings: list[Finding], ai_s2: str) -> tuple[str, list[str]]:
    reasons = []
    decision = "approve"
    for f in findings:
        if f.severity == "S1":
            decision = "block"
            reasons.append(f"S1 {f.rule} at {f.file}:{f.line}")
        elif f.severity == "S2":
            if f.source == "deterministic" or corroborated(f, findings):
                decision = "block"
                reasons.append(f"S2 {f.rule} at {f.file}:{f.line} ({f.source}, corroborated or deterministic)")
            elif ai_s2 == "block":
                decision = "block"
                reasons.append(f"S2 {f.rule} at {f.file}:{f.line} (AI-only, policy=block)")
            else:
                if decision == "approve":
                    decision = "comment"
                reasons.append(f"S2 {f.rule} at {f.file}:{f.line} (AI-only, policy=comment)")
        elif f.severity == "S3" and decision == "approve":
            decision = "comment"
    return decision, reasons


SEV_MEANING = {  # TEAM-STANDARDS.md §6
    "S1": "S1 — blocks merge",
    "S2": "S2 — blocks merge",
    "S3": "S3 — comment only",
}


def markdown(branch: str, decision: str, findings: list[Finding], ai_ran: bool) -> str:
    icon = {"block": "⛔", "comment": "💬", "approve": "✅"}[decision]
    lines = [f"# Quality gate — `{branch}`", "", f"**Decision: {icon} {decision.upper()}**", ""]
    if findings:
        for f in findings:
            loc = f"{f.file}:{f.line}" if f.line else f.file
            src = "deterministic" if f.source == "deterministic" else f"AI, confidence {f.confidence:.2f}"
            lines += [
                f"- **{SEV_MEANING[f.severity]}** · `{loc}` · {f.rule} ({src})",
                f"  {f.message}",
                f"  **Fix:** {f.suggested_fix}",
                "",
            ]
    else:
        lines += ["No findings.", ""]
    if not ai_ran:
        lines.append(
            "⚠️ The AI review contributed nothing this run (clean PR, no API key, or "
            "API failure — see run logs). Without it, subtle logic bugs and "
            "ineffective-test findings are NOT covered."
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--branch", required=True)
    ap.add_argument(
        "--ai-s2",
        choices=["block", "comment"],
        default=os.environ.get("GATE_AI_S2", "block"),
        help="uncorroborated AI-only S2: block or comment (default from $GATE_AI_S2, else block — see deliverables/EVAL.md)",
    )
    ap.add_argument("--reports-dir", default="reports")
    args = ap.parse_args()

    try:
        findings = dedupe(load(sys.stdin))
    except ValueError as e:
        sys.exit(f"decide: {e}")

    ai_ran = any(f.check == "ai_review" for f in findings)
    decision, _ = decide(findings, args.ai_s2)
    md = markdown(args.branch, decision, findings, ai_ran)

    out = Path(args.reports_dir)
    out.mkdir(parents=True, exist_ok=True)
    slug = args.branch.replace("/", "-")
    (out / f"{slug}.md").write_text(md)
    (out / f"{slug}.json").write_text(
        json.dumps(
            {
                "branch": args.branch,
                "decision": decision,
                "ai_s2_policy": args.ai_s2,
                "ai_ran": ai_ran,
                "findings": [asdict(f) for f in findings],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )

    print(md)
    sys.exit(1 if decision == "block" else 0)


if __name__ == "__main__":
    main()
