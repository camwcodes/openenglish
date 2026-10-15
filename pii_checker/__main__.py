"""`python -m pii_checker` — the package's entry point: the decide step.

Findings (JSONL) on stdin -> block / comment / approve + report. See decide.py.
"""

from pii_checker.decide import main

if __name__ == "__main__":
    main()
