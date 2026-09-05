"""Tests for Worker delivery-summary normalization."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DELIVERY_SCRIPT = ROOT / "deploy/worker-entrypoint/delivery.sh"


def _normalize(summary: str) -> str:
    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{DELIVERY_SCRIPT}"; normalize_delivery_summary_response "$1"',
            "bash",
            summary,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _read_result_summary(canonical: str, legacy: str = "") -> str:
    result = subprocess.run(
        [
            "bash",
            "-c",
            (
                f'source "{DELIVERY_SCRIPT}"; '
                'read_harness_result_summary'
            ),
        ],
        env={
            **os.environ,
            "CODIFY_HARNESS_RESULT_FILE": canonical,
            "CODIFY_HARNESS_OUTPUT_FILE": legacy,
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_mermaid_git_upstream_ref_is_encoded_without_changing_valid_shape_syntax():
    summary = """诊断摘要

```mermaid
flowchart TD
    A[读取上游 @{u}] --> B@{ shape: cloud }
```

普通文本中的 @{u} 不应被改写。
"""

    normalized = _normalize(summary)

    assert "A[读取上游 @&#123;u&#125;]" in normalized
    assert "B@{ shape: cloud }" in normalized
    assert "普通文本中的 @{u} 不应被改写。" in normalized


def test_canonical_harness_result_is_preferred_for_delivery_summary(tmp_path: Path):
    canonical = tmp_path / "harness-result.json"
    legacy = tmp_path / "adapter-output.json"
    canonical.write_text('{"result":"canonical summary"}', encoding="utf-8")
    legacy.write_text('{"result":"legacy summary"}', encoding="utf-8")

    assert _read_result_summary(str(canonical), str(legacy)) == "canonical summary"


def test_delivery_summary_keeps_legacy_result_fallback(tmp_path: Path):
    canonical = tmp_path / "harness-result.json"
    legacy = tmp_path / "adapter-output.json"
    canonical.write_text('{"result":""}', encoding="utf-8")
    legacy.write_text('{"result":"legacy summary"}', encoding="utf-8")

    assert _read_result_summary(str(canonical), str(legacy)) == "legacy summary"
