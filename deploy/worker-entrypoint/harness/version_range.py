#!/usr/bin/env python3
"""Advisory semver-range check for harness CLI versions.

``cli_version_range`` in the Runtime Bundle manifest (e.g. ``>=2.1.33 <3.0.0``)
is a fast-startup compatibility hint, NOT an enforced gate: an out-of-range CLI
is logged as a warning and allowed to run. This module evaluates the range so
both adapters can emit that warning without duplicating the parser.
"""

from __future__ import annotations

import argparse
import re
import sys


def _components(version: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", version)
    return tuple(int(part) for part in parts[:3])


def _compare(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    while len(a) < 3:
        a = a + (0,)
    while len(b) < 3:
        b = b + (0,)
    return (a > b) - (a < b)  # -1, 0, 1


def parse_expression(expr: str) -> tuple[str, tuple[int, ...]] | None:
    match = re.fullmatch(r"(>=|<=|>|<|=)?\s*([0-9]+(?:\.[0-9]+){0,2})", expr)
    if not match:
        return None
    return (match.group(1) or "="), _components(match.group(2))


def in_range(version: str, range_spec: str) -> bool:
    """True when version satisfies every space-separated comparison.

    An unparseable token is treated as satisfied (advisory only, never blocks).
    """
    if not range_spec or not version:
        return True
    version_cmp = _components(version)
    for expr in range_spec.split():
        parsed = parse_expression(expr)
        if parsed is None:
            continue
        op, target = parsed
        c = _compare(version_cmp, target)
        if op == ">=" and c < 0:
            return False
        if op == ">" and c <= 0:
            return False
        if op == "<=" and c > 0:
            return False
        if op == "<" and c >= 0:
            return False
        if op == "=" and c != 0:
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--range", required=True)
    args = parser.parse_args()
    if in_range(args.version, args.range):
        return 0
    print(f"{args.version} is outside declared range {args.range}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
