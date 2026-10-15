"""The findings contract — the only thing checks share besides `_diff`.

Every check prints one JSON object per finding, one per line (JSONL), to stdout:

  { "severity": "S1|S2|S3", "file": str, "line": int, "rule": str,
    "message": str, "suggested_fix": str, "source": "deterministic|llm",
    "confidence": float, "check": str }

`rule` is "<standards-section>/<slug>" (e.g. "S3/pii-to-log") so `decide.py` can
dedupe and corroborate by rule family without string-matching messages.
`check` names the emitting tool — extra key, allowed by the contract.
`line` is a post-change file line number; 0 when the finding is file-level.

Deterministic checks emit confidence 1.0; the AI check reports its own.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from typing import Iterable, TextIO

SEVERITIES = ("S1", "S2", "S3")
SOURCES = ("deterministic", "llm")


@dataclass
class Finding:
    severity: str
    file: str
    line: int
    rule: str
    message: str
    suggested_fix: str
    source: str
    confidence: float
    check: str = ""

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"bad severity {self.severity!r} (want {SEVERITIES})")
        if self.source not in SOURCES:
            raise ValueError(f"bad source {self.source!r} (want {SOURCES})")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence {self.confidence} outside [0, 1]")


def emit(finding: Finding, out: TextIO = sys.stdout) -> None:
    """One finding per line: JSONL when piped, readable when on a terminal."""
    if out.isatty():
        loc = f"{finding.file}:{finding.line}" if finding.line else finding.file
        src = "" if finding.source == "deterministic" else f" (llm {finding.confidence:.2f})"
        print(f"{finding.severity} {loc} [{finding.rule}]{src}", file=out)
        print(f"  {finding.message}", file=out)
        print(f"  fix: {finding.suggested_fix}", file=out)
    else:
        print(json.dumps(asdict(finding), ensure_ascii=False), file=out)


def load(lines: Iterable[str]) -> list[Finding]:
    """Parse JSONL (e.g. decide.py's stdin); skips blank lines, raises on bad ones."""
    findings = []
    for n, raw in enumerate(lines, 1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
            findings.append(Finding(**{k: obj[k] for k in Finding.__dataclass_fields__ if k in obj}))
        except (json.JSONDecodeError, TypeError, ValueError, KeyError) as e:
            raise ValueError(f"findings line {n} invalid: {e}: {raw[:120]}") from e
    return findings
