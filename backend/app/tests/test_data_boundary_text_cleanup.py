"""Regression tests for model-output text cleanup."""
from __future__ import annotations

from app.privacy.pipeline import _plain_dialog_text


def test_plain_dialog_text_removes_markdown_source_syntax():
    raw = """## Basis

1. **Research use** requires `IRB review`.

- **Commercial use** is blocked.
```text
No code fence should remain.
```
"""
    cleaned = _plain_dialog_text(raw)
    assert "**" not in cleaned
    assert "`" not in cleaned
    assert "```" not in cleaned
    assert not cleaned.startswith("#")
    assert "Research use" in cleaned
    assert "IRB review" in cleaned
