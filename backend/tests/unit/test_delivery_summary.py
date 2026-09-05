"""Tests for Worker delivery-summary normalization."""

from __future__ import annotations

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
