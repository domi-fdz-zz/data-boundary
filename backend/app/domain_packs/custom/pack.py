"""Custom fallback pack (stub). Always scores a small baseline so it wins only
when no real pack matches."""
from __future__ import annotations

from pathlib import Path

from ..base import StubPack, DomainPack


def get_pack() -> DomainPack:
    return StubPack(Path(__file__).parent)
