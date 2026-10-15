"""Branch access layer for all checks (diff parsing bought: `unidiff`).

Answers, for one PR branch, the questions every check asks:

  1. which files changed      -> BranchDiff.files / changed_files()
  2. which lines were added   -> FileDiff.added_lines (post-change line numbers)
  3. post-change file content -> file_at(branch, path)
  4. the branch's privacy policy -> load_policy(branch)
     (PII_FIELDS / RETENTION_DAYS from app/privacy.py AT THE BRANCH TIP —
     never hardcoded, parsed with `ast`, never imported/exec'd)

The diff is `git diff <base>...<branch>` (merge-base, same as a PR view).
Run standalone to inspect a branch:

  python -m pii_checker._diff <branch> [--base main] [--file <path>]
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from dataclasses import dataclass, field

from unidiff import PatchSet

PRIVACY_PATH = "app/privacy.py"


def _git(*args: str) -> str:
    res = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout


@dataclass
class AddedLine:
    line: int  # line number in the post-change file (1-based)
    text: str  # content without the leading '+'


@dataclass
class FileDiff:
    path: str  # post-change path
    old_path: str | None  # None when the file is new
    status: str  # added | modified | deleted | renamed
    added_lines: list[AddedLine] = field(default_factory=list)

    @property
    def is_new(self) -> bool:
        return self.status == "added"

    def added_text(self) -> str:
        return "\n".join(al.text for al in self.added_lines)


@dataclass
class BranchDiff:
    branch: str
    base: str
    files: dict[str, FileDiff]  # keyed by post-change path

    def changed_files(self, suffix: str | None = None) -> list[str]:
        """Paths that exist post-change (deletions excluded)."""
        return [
            p
            for p, f in self.files.items()
            if f.status != "deleted" and (suffix is None or p.endswith(suffix))
        ]

    def added_lines(self, path: str) -> list[AddedLine]:
        f = self.files.get(path)
        return f.added_lines if f else []


def diff(branch: str, base: str = "main") -> BranchDiff:
    patch = PatchSet(_git("diff", "--no-color", "-M", f"{base}...{branch}"))
    files: dict[str, FileDiff] = {}
    for pf in patch:
        status = (
            "added" if pf.is_added_file
            else "deleted" if pf.is_removed_file
            else "renamed" if pf.is_rename
            else "modified"
        )
        fd = FileDiff(
            path=pf.path,
            old_path=None if pf.is_added_file else pf.source_file.removeprefix("a/"),
            status=status,
            added_lines=[
                AddedLine(line=ln.target_line_no, text=ln.value.rstrip("\n"))
                for hunk in pf
                for ln in hunk
                if ln.is_added
            ],
        )
        files[fd.path] = fd
    return BranchDiff(branch=branch, base=base, files=files)


def file_at(ref: str, path: str) -> str | None:
    """Post-change content of `path` at `ref` (branch tip); None if absent."""
    try:
        return _git("show", f"{ref}:{path}")
    except RuntimeError:
        return None


@dataclass
class Policy:
    pii_fields: set[str]
    retention_days: dict[str, int]
    source_text: str  # raw privacy.py, for the AI prompt


def load_policy(ref: str) -> Policy:
    """PII_FIELDS / RETENTION_DAYS as defined at `ref` (AST-parsed, not executed)."""
    text = file_at(ref, PRIVACY_PATH)
    if text is None:
        raise RuntimeError(f"{PRIVACY_PATH} missing at {ref}")
    pii: set[str] = set()
    retention: dict[str, int] = {}
    for node in ast.parse(text).body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                continue
            if target.id == "PII_FIELDS":
                pii = set(value)
            elif target.id == "RETENTION_DAYS":
                retention = dict(value)
    return Policy(pii_fields=pii, retention_days=retention, source_text=text)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("branch")
    ap.add_argument("--base", default="main")
    ap.add_argument("--file", help="dump added lines (line/text) for one file")
    args = ap.parse_args()

    bd = diff(args.branch, base=args.base)
    if args.file:
        fd = bd.files.get(args.file)
        if fd is None:
            sys.exit(f"{args.file}: not in diff {args.base}...{args.branch}")
        for al in fd.added_lines:
            print(json.dumps({"line": al.line, "text": al.text}))
    else:
        print(json.dumps({
            "branch": bd.branch,
            "base": bd.base,
            "files": [
                {"path": f.path, "status": f.status, "added_lines": len(f.added_lines)}
                for f in bd.files.values()
            ],
        }, indent=2))


if __name__ == "__main__":
    main()
