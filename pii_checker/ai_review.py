"""LLM review of a PR branch against TEAM-STANDARDS.md (Claude API).

This check carries the judgment calls the deterministic layer can't make:
logic correctness (off-by-one, wrong formula), test *effectiveness* (a passing
suite is not proof), minimization / legal-basis reasoning, and the pii-minor
aggravation. It is given the standards, the branch's own PII_FIELDS /
RETENTION_DAYS, the diff, post-change file contents, and the deterministic
findings as hints.

Hardening (notes/PLAN.md): structured output via a JSON schema, and the prompt forces
*worked-example reasoning* — every logic/test finding must trace a concrete
input and state expected vs. actual. (notes/PLAN.md asked for temperature 0 as well;
current Claude models reject sampling parameters, so determinism rests on the
schema + worked-example prompt — recorded in deliverables/DECISIONS.md.)

Graceful degradation: no ANTHROPIC_API_KEY (or API failure) → warning on
stderr, no findings, exit 0. The deterministic checks still run; the two
subtle logic cases degrade to *undetected*.

  python -m pii_checker.ai_review <branch> [--base main] [--hints file.jsonl]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pii_checker._diff import _git, diff, file_at, load_policy
from pii_checker._findings import Finding, emit, load

MODEL = os.environ.get("GATE_AI_MODEL", "claude-opus-4-8")

# The review instructions (method, severity model, rule slugs) live in
# prompt.md next to this file — edit the prompt there, not here.
SYSTEM = (Path(__file__).parent / "prompt.md").read_text()

SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["S1", "S2", "S3"]},
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "rule": {"type": "string"},
                    "message": {"type": "string"},
                    "suggested_fix": {"type": "string"},
                    "worked_example": {
                        "type": "string",
                        "description": (
                            "REQUIRED for logic/* and testing/* findings: the concrete "
                            "input you traced and the expected vs. actual values."
                        ),
                    },
                    "confidence": {"type": "number"},
                },
                "required": [
                    "severity", "file", "line", "rule",
                    "message", "suggested_fix", "worked_example", "confidence",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}

def collect_context(branch: str, base: str) -> str:
    bd = diff(branch, base=base)
    policy = load_policy(branch)
    standards = file_at(base, "TEAM-STANDARDS.md") or ""
    raw_diff = _git("diff", "--no-color", f"{base}...{branch}")

    parts = [
        "## TEAM-STANDARDS.md (the rubric)\n" + standards,
        "## Branch privacy policy (app/privacy.py at the branch tip)\n"
        + policy.source_text
        + f"\nParsed: PII_FIELDS={sorted(policy.pii_fields)} "
        + f"RETENTION_DAYS={policy.retention_days}",
        f"## Diff under review ({base}...{branch})\n```diff\n{raw_diff}\n```",
    ]
    for path in bd.changed_files(suffix=".py"):
        content = file_at(branch, path)
        if content is not None:
            parts.append(f"## Post-change content: {path}\n```python\n{content}\n```")
    # store.py shows which students are minors — needed for aggravation judgment
    if "app/store.py" not in bd.files:
        store = file_at(branch, "app/store.py")
        if store:
            parts.append(f"## Context (unchanged): app/store.py\n```python\n{store}\n```")
    return "\n\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("branch", nargs="?", default="HEAD")
    ap.add_argument("--base", default="main")
    ap.add_argument("--hints", help="JSONL file of deterministic findings to pass as hints")
    args = ap.parse_args()

    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print(
            "pii_checker.ai_review: ANTHROPIC_API_KEY not set — AI review SKIPPED. "
            "Deterministic checks still apply; subtle logic/test-quality findings "
            "are NOT covered in this run.",
            file=sys.stderr,
        )
        return

    hints = ""
    if args.hints:
        with open(args.hints) as fh:
            det = load(fh)
        hints = "\n\n## Deterministic findings (hints — do not re-report verbatim)\n" + (
            "\n".join(json.dumps(f.__dict__) for f in det) or "(none)"
        )

    user_content = collect_context(args.branch, args.base) + hints + (
        "\n\nReview this pull request now. Remember: trace concrete inputs for "
        "every logic/test judgment and put the trace in worked_example."
    )

    import anthropic

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": user_content}],
        )
    except anthropic.APIConnectionError as e:
        print(f"pii_checker.ai_review: network error, AI review SKIPPED: {e}", file=sys.stderr)
        return
    except anthropic.APIStatusError as e:
        print(
            f"pii_checker.ai_review: API error {e.status_code}, AI review SKIPPED: {e.message}",
            file=sys.stderr,
        )
        return

    if response.stop_reason == "refusal":
        print("pii_checker.ai_review: model refused the request, AI review SKIPPED", file=sys.stderr)
        return
    if response.stop_reason == "max_tokens":
        print("pii_checker.ai_review: output truncated (max_tokens), AI review SKIPPED", file=sys.stderr)
        return

    text = next(b.text for b in response.content if b.type == "text")
    for f in json.loads(text)["findings"]:
        message = f["message"]
        if f.get("worked_example"):
            message += f" [worked example: {f['worked_example']}]"
        emit(
            Finding(
                severity=f["severity"],
                file=f["file"],
                line=int(f["line"]),
                rule=f["rule"],
                message=message,
                suggested_fix=f["suggested_fix"],
                source="llm",
                confidence=max(0.0, min(1.0, float(f["confidence"]))),
                check="ai_review",
            )
        )


if __name__ == "__main__":
    main()
