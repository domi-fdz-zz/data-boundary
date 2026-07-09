"""
Domain pack registry.

Each pack lives in its own folder and exposes get_pack() -> DomainPack.
get_all_packs() builds them once (cached). The BioData pack is the only one with
real rules in v0.1; the rest are stubs that route correctly and return
insufficient_information.
"""
from __future__ import annotations

from functools import lru_cache

from .base import DomainPack  # noqa: F401  (re-exported for typing)


@lru_cache(maxsize=1)
def get_all_packs() -> list["DomainPack"]:
    from .biodata.pack import get_pack as _biodata
    from .genetic_testing.pack import get_pack as _genetic
    from .drug_procurement.pack import get_pack as _drug
    from .agricultural_genomics.pack import get_pack as _agri
    from .custom.pack import get_pack as _custom
    return [_biodata(), _genetic(), _drug(), _agri(), _custom()]


def get_pack_by_id(pack_id: str) -> "DomainPack":
    packs = get_all_packs()
    for p in packs:
        if p.id == pack_id:
            return p
    for p in packs:
        if p.id == "custom":
            return p
    raise KeyError(f"no pack {pack_id!r} and no custom fallback registered")


def list_domain_packs() -> list[dict]:
    """Summary rows for GET /api/domain-packs."""
    return [{"id": p.id, "name": p.name, "version": p.version, "status": p.status}
            for p in get_all_packs()]
