"""pii-checker: deterministic privacy scan of a branch's diff vs main.

A plain tool, same contract as gitleaks/ruff: run it locally or in CI, findings
on stdout (readable on a terminal, JSONL when piped). Exits 1 when any finding
is at or above --fail-on (default S2, i.e. the severities TEAM-STANDARDS.md §6
says block merge; S1 is the highest). --fail-on none always exits 0.

Three rules, everything judged against the branch's OWN app/privacy.py
(PII_FIELDS / RETENTION_DAYS via pii_checker._diff.load_policy):

  pii/log-exposure          a logging call on an ADDED line carries PII —
                            directly (student.full_name), by PII-named variable
                            (email), or one hop through a helper defined in this
                            diff whose body reads PII attributes. redact()/pick()
                            wrapped arguments are considered safe.
  retention/missing-category  an added .append/.add/... persists a value carrying
                            PII fields while the PR declares NO new
                            RETENTION_DAYS category.
  */guardrail-weakened      the PR edits app/privacy.py itself, removing a PII
                            field or loosening/removing a retention category
                            (any other edit to that file -> S3 heads-up).

Seed data includes minors (is_minor=True), so PII exposure is aggravated
(pii-minor) -> S1 throughout.

  python -m pii_checker.deterministic [<branch>] [--base main] [--fail-on S1|S2|S3|none]
"""

from __future__ import annotations

import argparse
import ast
import sys

from pii_checker._diff import PRIVACY_PATH, diff, file_at, load_policy
from pii_checker._findings import Finding, emit

LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "log"}
SAFE_WRAPPERS = {"redact", "pick"}
PERSIST_METHODS = {"append", "add", "insert", "update", "setdefault"}


def _finding(severity, file, line, rule, message, fix, confidence=1.0) -> Finding:
    return Finding(
        severity=severity, file=file, line=line, rule=rule, message=message,
        suggested_fix=fix, source="deterministic", confidence=confidence,
        check="pii_checker",
    )


# ---- rule 1: PII -> log taint ----------------------------------------------

def _pii_in(node: ast.AST, pii: set[str], helpers: set[str]) -> tuple[str, str] | None:
    """(kind, name) if `node` carries PII; stops at redact()/pick()."""
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = child.func.id if isinstance(child.func, ast.Name) else (
                child.func.attr if isinstance(child.func, ast.Attribute) else ""
            )
            if name in SAFE_WRAPPERS:
                return None
            if name in helpers:
                return ("helper", name)
        if isinstance(child, ast.Attribute) and child.attr in pii:
            return ("attribute", child.attr)
        if isinstance(child, ast.Name) and child.id in pii:
            return ("name", child.id)
    return None


def check_log_exposure(trees, added, pii) -> list[Finding]:
    # helpers defined anywhere in the diff whose body reads PII attributes
    helpers = {
        node.name
        for tree in trees.values()
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(isinstance(s, ast.Attribute) and s.attr in pii for s in ast.walk(node))
    }
    out = []
    for path, tree in trees.items():
        for node in ast.walk(tree):
            is_log = (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in LOG_METHODS
            )
            if not is_log or node.lineno not in added[path]:
                continue
            hit = _pii_in(node, pii, helpers)
            if hit is None:
                continue
            kind, name = hit
            via = {
                "attribute": f"PII field `.{name}` is passed to the logger",
                "name": f"variable `{name}` (a PII field name) is passed to the logger",
                "helper": f"helper `{name}()` builds PII fields and its result is logged",
            }[kind]
            out.append(_finding(
                "S1", path, node.lineno, "pii/log-exposure",
                f"PII written to logs ({via}). Seed data includes minors, so this "
                f"is aggravated pii-minor exposure (§3).",
                "Log only non-PII identifiers, or pass the payload through app.privacy.redact().",
                confidence=1.0 if kind != "name" else 0.8,
            ))
    return out


# ---- rule 2: persisted PII copy without a retention category ----------------

def check_retention(trees, added, policy, base_policy) -> list[Finding]:
    if set(policy.retention_days) - set(base_policy.retention_days):
        return []  # PR declared a category; adequacy (90d/legal basis) is the AI's call
    out = []
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in PERSIST_METHODS
                and node.lineno in added[path]
            ):
                continue
            pii_found = sorted({
                c.value if isinstance(c, ast.Constant) else c.attr
                for arg in node.args
                for c in ast.walk(arg)
                if (isinstance(c, ast.Constant) and c.value in policy.pii_fields)
                or (isinstance(c, ast.Attribute) and c.attr in policy.pii_fields)
            })
            if pii_found:
                out.append(_finding(
                    "S1", path, node.lineno, "retention/missing-category",
                    f"New persisted copy of personal data ({', '.join(pii_found)}) with "
                    f"no category declared in app.privacy.RETENTION_DAYS. Seed data "
                    f"includes minors (max 90 days without a documented legal basis) (§4).",
                    "Declare a RETENTION_DAYS category (≤90 days for minors unless a legal "
                    "basis is documented in the PR) and store only the fields actually needed.",
                ))
    return out


# ---- rule 3: PR weakens the guardrail file itself ---------------------------

def check_guardrail(bd, policy, base_policy) -> list[Finding]:
    if PRIVACY_PATH not in bd.files:
        return []
    out = []
    for field in base_policy.pii_fields - policy.pii_fields:
        out.append(_finding(
            "S1", PRIVACY_PATH, 0, "pii/guardrail-weakened",
            f"PR removes {field!r} from PII_FIELDS — redact() would stop masking it everywhere (§3).",
            "Keep the field classified as PII, or document why it is no longer personal data.",
        ))
    for category, days in base_policy.retention_days.items():
        new = policy.retention_days.get(category)
        if new is None or new > days:
            what = "removes" if new is None else f"raises {days}→{new} days for"
            out.append(_finding(
                "S1", PRIVACY_PATH, 0, "retention/guardrail-weakened",
                f"PR {what} RETENTION_DAYS category {category!r} — retention may silently "
                f"exceed policy, including for minors (§4).",
                "Keep or tighten the category; longer retention needs a documented legal basis in the PR.",
            ))
    if not out:
        out.append(_finding(
            "S3", PRIVACY_PATH, 0, "quality/guardrail-touched",
            "PR edits app/privacy.py (PII/retention guardrails). Not an observed "
            "weakening, but review the policy change deliberately.",
            "Have a privacy-aware reviewer confirm the policy edit.",
        ))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("branch", nargs="?", default="HEAD")
    ap.add_argument("--base", default="main")
    ap.add_argument(
        "--fail-on",
        choices=["S1", "S2", "S3", "none"],
        default="S2",
        help="exit 1 if any finding is at or above this severity "
        "(S1 = most severe; default S2 = the severities that block merge per §6)",
    )
    args = ap.parse_args()

    bd = diff(args.branch, base=args.base)
    policy = load_policy(args.branch)
    base_policy = load_policy(args.base)

    trees, added = {}, {}
    for path in bd.changed_files(suffix=".py"):
        if not path.startswith("app/"):
            continue
        content = file_at(args.branch, path)
        if content is not None:
            trees[path] = ast.parse(content)
            added[path] = {al.line for al in bd.added_lines(path)}

    findings = (
        check_log_exposure(trees, added, policy.pii_fields)
        + check_retention(trees, added, policy, base_policy)
        + check_guardrail(bd, policy, base_policy)
    )
    for f in findings:
        emit(f)
    # tool semantics (like gitleaks/ruff): nonzero exit at/above the severity threshold
    rank = {"S1": 1, "S2": 2, "S3": 3}
    if args.fail_on != "none" and any(
        rank[f.severity] <= rank[args.fail_on] for f in findings
    ):
        sys.exit(1)


if __name__ == "__main__":
    main()
