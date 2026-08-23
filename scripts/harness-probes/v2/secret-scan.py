#!/usr/bin/env python3
"""Scan V2 probe evidence without displaying matching content.

Only ``file:rule`` pairs are emitted. By default the scan is limited to the V2
probe/evidence directories; ``--staged`` checks every added line in the staged
diff unless explicit paths narrow the scope.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess

RULES = {
    "private-key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "provider-key-prefix": re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|glpat-[A-Za-z0-9_-]{12,})"),
    "authorization-value": re.compile(r"(?i)(?:authorization|x-api-key)\s*[:=]\s*(?:bearer\s+)?[^\s'\"${]{12,}"),
    "credential-assignment": re.compile(r"(?i)(?:api[_-]?key|secret(?:[_-]?key)?|access[_-]?token)\s*[:=]\s*['\"][^'\"${]{12,}"),
}


def scan(label: str, content: str) -> list[str]:
    return [f"{label}:{name}" for name, pattern in RULES.items() if pattern.search(content)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=pathlib.Path)
    parser.add_argument("--staged", action="store_true")
    args = parser.parse_args()
    root = pathlib.Path(__file__).resolve().parents[3]
    paths = args.paths or [root / "scripts/harness-probes/v2", root / "docs/harness-probes/v2"]
    findings: list[str] = []
    for path in paths:
        candidates = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
        for item in candidates:
            try: label = str(item.relative_to(root))
            except ValueError: label = str(item)
            findings.extend(scan(label, item.read_text(errors="replace")))
    if args.staged:
        command = ["git", "diff", "--cached", "--no-ext-diff", "--unified=0"]
        if args.paths:
            command.extend(["--", *map(str, args.paths)])
        diff = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        additions = "\n".join(
            line[1:]
            for line in diff.stdout.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        )
        findings.extend(scan("staged-diff", additions))
    unique = sorted(set(findings))
    for finding in unique: print(finding)
    print(f"secret-scan={'failed' if unique else 'passed'} findings={len(unique)}")
    return 1 if unique else 0


if __name__ == "__main__":
    raise SystemExit(main())
