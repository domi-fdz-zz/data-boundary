"""
engine.py — the Core Engine. Orchestrates the whole clearance flow.

    route → select pack → normalize → missing-info check → retrieve evidence →
    apply rules → generate report

Input here is ALREADY structured (the LLM/free-text normalization, if any,
happened earlier at /api/assessments/normalize). engine.assess() is pure and
deterministic — no network, no LLM.
"""
from __future__ import annotations

from ..models.schemas import AssessmentInput, ClearanceReport
from ..domain_packs import get_pack_by_id
from . import router as router_mod


class ClearanceEngine:
    def assess(self, assessment_input: AssessmentInput) -> ClearanceReport:
        candidates = router_mod.route(assessment_input)
        pack_id = candidates[0].domain_pack_id if candidates else "custom"
        pack = get_pack_by_id(pack_id)

        normalized = pack.normalize(assessment_input)
        missing = pack.get_missing_information(normalized)
        evidence = pack.retrieve_evidence(normalized)
        triggered = pack.apply_rules(normalized, evidence)
        report = pack.generate_report(
            assessment=normalized,
            evidence=evidence,
            triggered_rules=triggered,
            missing_information=missing,
        )
        return report


# Module-level singleton for convenience.
engine = ClearanceEngine()


def assess(assessment_input: AssessmentInput) -> ClearanceReport:
    return engine.assess(assessment_input)
