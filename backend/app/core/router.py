"""
router.py — pick the domain pack for an assessment.

Each pack scores itself via detect(); the router ranks them. The custom pack
carries a small baseline score so it always ranks last-but-nonzero, i.e. it wins
only when no real pack matched.
"""
from __future__ import annotations

from ..models.schemas import AssessmentInput, DomainCandidate
from ..domain_packs import get_all_packs


def route(assessment: AssessmentInput) -> list[DomainCandidate]:
    """Ranked routing candidates, highest score first (custom last)."""
    candidates: list[DomainCandidate] = []
    for pack in get_all_packs():
        score = float(pack.detect(assessment))
        candidates.append(DomainCandidate(
            domain_pack_id=pack.id,
            score=round(score, 2),
            reason=pack.explain(assessment),
        ))
    # Highest score first; on ties, keep 'custom' behind real packs.
    candidates.sort(key=lambda c: (c.score, c.domain_pack_id != "custom"), reverse=True)
    return candidates
