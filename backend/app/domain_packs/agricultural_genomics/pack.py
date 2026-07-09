"""Agricultural Genomics pack (stub). Routes correctly; fixed verdict."""
from __future__ import annotations

from pathlib import Path

from ..base import StubPack, DomainPack


def get_pack() -> DomainPack:
    return StubPack(Path(__file__).parent)
