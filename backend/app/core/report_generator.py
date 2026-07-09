"""
report_generator.py — merge the triggered rules into one ClearanceReport.

This is the "Templates explain" half. It performs NO legal reasoning of its own;
it only combines what the rules already decided:

  overall_verdict : highest-priority verdict among triggered rules
                    (VERDICT_PRIORITY; insufficient_information is lowest, so a
                    run that also fired a real rule reports that rule's verdict).
  risk_level      : highest risk among triggered rules (RISK_PRIORITY).
  confidence      : high  = rules fired, nothing material missing
                    medium= rules fired, some secondary info missing
                    low   = the critical-missing rule fired, or nothing fired.
  conditions      : prerequisites from the rule(s) that produced the winning
                    (gating) verdict.
  next_actions    : the remaining to-dos from all fired rules, priority = the
                    max risk of the rule(s) that asked for them.
  risks / evidence / triggered_rules / jurisdiction_matrix / disclaimers.
"""
from __future__ import annotations

from ..models.schemas import (
    AssessmentInput,
    ClearanceReport,
    Condition,
    Risk,
    NextAction,
    JurisdictionVerdict,
    EvidenceItem,
    MissingInformation,
    Verdict,
    RiskLevel,
    Confidence,
    VERDICT_PRIORITY,
    RISK_PRIORITY,
)
from .rule_engine import triggered_rule_from, _norm


DISCLAIMERS = [
    "This report is a preliminary compliance clearance assessment and is not legal advice.",
    "v0.1 uses fixture evidence and simplified rules. It should not be used as a "
    "final legal determination.",
]

_GATING_VERDICTS = {
    Verdict.conditionally_allowed.value,
    Verdict.requires_filing_or_approval.value,
    Verdict.restricted_not_recommended.value,
}

_VERDICT_PHRASE = {
    Verdict.allowed.value:
        "appears usable for the stated use with standard precautions",
    Verdict.conditionally_allowed.value:
        "may be usable, but only if specific conditions are satisfied first",
    Verdict.requires_filing_or_approval.value:
        "likely requires filing, approval, or heightened review before use",
    Verdict.restricted_not_recommended.value:
        "is restricted and not recommended without significant changes",
    Verdict.insufficient_information.value:
        "cannot be cleared yet because key information is missing",
}

_RISK_TO_PRIORITY = {
    RiskLevel.critical.value: "high",
    RiskLevel.high.value: "high",
    RiskLevel.medium.value: "medium",
    RiskLevel.low.value: "low",
    RiskLevel.unknown.value: "low",
}

_CHINA_ALIASES = {"china", "中国", "cn", "people's republic of china", "prc"}


# ─────────────────────────── merge primitives ───────────────────────────
def merge_verdict(verdicts: list[str]) -> str:
    present = {v for v in verdicts if v}
    for v in VERDICT_PRIORITY:
        if v in present:
            return v
    return Verdict.insufficient_information.value


def merge_risk(risks: list[str]) -> str:
    present = {r for r in risks if r}
    for r in RISK_PRIORITY:
        if r in present:
            return r
    return RiskLevel.unknown.value


def compute_confidence(matched_rules: list[dict],
                       missing_information: list[MissingInformation]) -> str:
    if not matched_rules:
        return Confidence.low.value
    insufficient_fired = any(
        r.get("verdict") == Verdict.insufficient_information.value
        for r in matched_rules
    )
    if insufficient_fired:
        return Confidence.low.value
    if missing_information:
        return Confidence.medium.value
    return Confidence.high.value


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        k = x.strip().lower() if isinstance(x, str) else x
        if k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


# ─────────────────────────── summary text ───────────────────────────
def _build_summary(assessment: AssessmentInput, overall_verdict: str,
                   n_risks: int, missing_information: list) -> str:
    obj = assessment.object
    uc = assessment.use_case
    df = assessment.data_flow
    meta = obj.metadata or {}

    what = obj.object_type or "object"
    if obj.name:
        what = f"{what} '{obj.name}'"
    if obj.source:
        what = f"{what} from {obj.source}"
    organism = meta.get("organism")
    if organism:
        what = f"{what} ({organism})"

    uses = []
    if uc.commercial:
        uses.append("commercial")
    if uc.clinical:
        uses.append("clinical")
    if uc.ai_training:
        uses.append("AI-training")
    if uc.research_only:
        uses.append("research-only")
    use_str = (", ".join(uses) + " ") if uses else ""
    use_phrase = f"{use_str}{uc.category}".strip()

    flow_bits = []
    if df.cross_border:
        flow_bits.append("cross-border")
    if df.cloud_processing:
        flow_bits.append("cloud processing")
    flow_str = (" with " + " and ".join(flow_bits)) if flow_bits else ""

    lead = (f"This assessment covers a {what} intended for {use_phrase}"
            f"{flow_str}.")
    verdict_line = f"Overall, it {_VERDICT_PHRASE.get(overall_verdict, overall_verdict)}."
    tail = ""
    if n_risks:
        tail = f" {n_risks} risk item(s) were flagged."
    if missing_information:
        tail += (f" {len(missing_information)} piece(s) of information are still "
                 f"missing and should be provided to firm up the assessment.")
    return f"{lead} {verdict_line}{tail}".strip()


# ─────────────────────────── jurisdiction matrix ───────────────────────────
def _build_matrix(assessment: AssessmentInput, matched_rules: list[dict],
                  overall_verdict: str, overall_risk: str) -> list[JurisdictionVerdict]:
    countries = assessment.jurisdiction.countries or []
    if not countries:
        return []
    non_cn = [r for r in matched_rules
              if not str(r.get("rule_id", "")).startswith("CN-")]
    out: list[JurisdictionVerdict] = []
    for c in countries:
        is_china = _norm(c) in _CHINA_ALIASES
        subset = matched_rules if is_china else non_cn
        no_specific = False
        if subset:
            v = merge_verdict([r.get("verdict", "") for r in subset])
            rk = merge_risk([r.get("risk_level", "") for r in subset])
        elif is_china:
            # China with only-CN rules (or none): overall already reflects it.
            v, rk = overall_verdict, overall_risk
        else:
            # A non-China jurisdiction with no applicable (non-CN) rule must NOT
            # inherit China's verdict — no basis, so insufficient/unknown.
            v, rk = merge_verdict([]), merge_risk([])
            no_specific = True
        if no_specific:
            summary = (f"No {c}-specific rule was triggered in this assessment; "
                       f"review {c} separately.")
        else:
            note = ""
            if is_china and any(str(r.get("rule_id", "")).startswith("CN-")
                                for r in matched_rules):
                note = " China-specific review (e.g. human genetic resources) may apply."
            summary = (f"For use in {c}, this {_VERDICT_PHRASE.get(v, v)}.{note}").strip()
        out.append(JurisdictionVerdict(jurisdiction=c, verdict=v,
                                       risk_level=rk, summary=summary))
    return out


# ─────────────────────────── the assembler ───────────────────────────
def build_report(*,
                 assessment: AssessmentInput,
                 assessment_id: str,
                 core_version: str,
                 domain_pack_id: str,
                 domain_pack_version: str,
                 matched_rules: list[dict],
                 evidence_items: list[EvidenceItem],
                 missing_information: list[MissingInformation]) -> ClearanceReport:
    """Combine everything into a ClearanceReport. Pure function of its inputs."""
    verdicts = [r.get("verdict", "") for r in matched_rules]
    risks_lvls = [r.get("risk_level", "") for r in matched_rules]
    overall_verdict = merge_verdict(verdicts)
    overall_risk = merge_risk(risks_lvls)
    confidence = compute_confidence(matched_rules, missing_information)

    # risks (one per fired rule, deduped by reason text)
    risk_items: list[Risk] = []
    seen_reason: set[str] = set()
    for r in matched_rules:
        reason = str(r.get("reason", "")).strip()
        if not reason or reason.lower() in seen_reason:
            continue
        seen_reason.add(reason.lower())
        risk_items.append(Risk(
            risk_id=f"risk_{len(risk_items) + 1:03d}",
            level=str(r.get("risk_level", RiskLevel.unknown.value)),
            text=reason,
        ))

    # conditions = prerequisites from the rule(s) that produced the winning verdict
    governing = [r for r in matched_rules if r.get("verdict") == overall_verdict]
    condition_texts: list[str] = []
    if overall_verdict in _GATING_VERDICTS:
        for r in governing:
            condition_texts.extend(r.get("required_actions") or [])
    condition_texts = _dedupe(condition_texts)
    condition_set = {t.strip().lower() for t in condition_texts}
    conditions = [Condition(condition_id=f"cond_{i + 1:03d}", text=t)
                  for i, t in enumerate(condition_texts)]

    # next_actions = every fired rule's actions minus those already listed as
    # conditions; priority = max risk of the rule(s) that asked for it.
    action_risk: dict[str, str] = {}
    order: list[str] = []
    for r in matched_rules:
        for a in (r.get("required_actions") or []):
            key = a.strip().lower()
            if key in condition_set:
                continue
            if key not in action_risk:
                order.append(a)
                action_risk[key] = str(r.get("risk_level", RiskLevel.unknown.value))
            else:
                action_risk[key] = merge_risk([action_risk[key],
                                               str(r.get("risk_level", ""))])
    next_actions = [
        NextAction(action_id=f"act_{i + 1:03d}",
                   priority=_RISK_TO_PRIORITY.get(action_risk[a.strip().lower()], "medium"),
                   text=a)
        for i, a in enumerate(order)
    ]

    triggered = [triggered_rule_from(r) for r in matched_rules]

    summary = _build_summary(assessment, overall_verdict, len(risk_items),
                             missing_information)

    matrix = _build_matrix(assessment, matched_rules, overall_verdict, overall_risk)

    return ClearanceReport(
        assessment_id=assessment_id,
        core_version=core_version,
        domain_pack_id=domain_pack_id,
        domain_pack_version=domain_pack_version,
        normalized_input=assessment,
        overall_verdict=overall_verdict,
        risk_level=overall_risk,
        confidence=confidence,
        summary=summary,
        conditions=conditions,
        risks=risk_items,
        evidence=evidence_items,
        triggered_rules=triggered,
        missing_information=missing_information,
        next_actions=next_actions,
        jurisdiction_matrix=matrix,
        disclaimers=list(DISCLAIMERS),
    )


def build_stub_report(*,
                      assessment: AssessmentInput,
                      assessment_id: str,
                      core_version: str,
                      domain_pack_id: str,
                      domain_pack_version: str,
                      verdict: str,
                      risk_level: str,
                      summary: str,
                      missing_information: list[MissingInformation]) -> ClearanceReport:
    """A minimal report for stub packs — a fixed verdict + explanatory summary,
    no fired rules. Confidence is always low (no rule engine ran)."""
    return ClearanceReport(
        assessment_id=assessment_id,
        core_version=core_version,
        domain_pack_id=domain_pack_id,
        domain_pack_version=domain_pack_version,
        normalized_input=assessment,
        overall_verdict=verdict,
        risk_level=risk_level,
        confidence=Confidence.low.value,
        summary=summary,
        conditions=[],
        risks=[],
        evidence=[],
        triggered_rules=[],
        missing_information=missing_information,
        next_actions=[],
        jurisdiction_matrix=[],
        disclaimers=list(DISCLAIMERS),
    )
