"""
schemas.py — the shared contract for the whole engine.

Input side (what the user describes, structured into six dimensions):
    AssessmentInput = Object + Actor + Use Case + Jurisdiction + Data Flow + Time

Output side (the structured clearance report):
    ClearanceReport = Verdict + Risk + Confidence + Conditions + Risks +
                      Evidence + TriggeredRules + MissingInformation +
                      NextActions + JurisdictionMatrix + Disclaimers

Deliberately NOT a binary legal/illegal answer — the verdict is one of five
clearance states. Rules decide the verdict; templates explain it.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ──────────────────────────── enums ────────────────────────────
class Verdict(str, Enum):
    """Clearance states — never a bare legal/illegal boolean."""
    allowed = "allowed"
    conditionally_allowed = "conditionally_allowed"
    requires_filing_or_approval = "requires_filing_or_approval"
    restricted_not_recommended = "restricted_not_recommended"
    insufficient_information = "insufficient_information"


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"
    unknown = "unknown"


class Confidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class Reliability(str, Enum):
    official_primary = "official_primary"
    official_guidance = "official_guidance"
    database_terms = "database_terms"
    commercial_secondary = "commercial_secondary"
    fixture_placeholder = "fixture_placeholder"
    unknown = "unknown"


# Merge priority when several rules trigger. Highest-priority (index 0) wins.
# insufficient_information is LAST: any concrete verdict outranks it, so a run
# that also fired a real rule reports that rule's verdict (with confidence
# downgraded when information is still missing). See report_generator.
VERDICT_PRIORITY: list[str] = [
    Verdict.restricted_not_recommended.value,
    Verdict.requires_filing_or_approval.value,
    Verdict.conditionally_allowed.value,
    Verdict.allowed.value,
    Verdict.insufficient_information.value,
]

# critical > high > medium > low > unknown
RISK_PRIORITY: list[str] = [
    RiskLevel.critical.value,
    RiskLevel.high.value,
    RiskLevel.medium.value,
    RiskLevel.low.value,
    RiskLevel.unknown.value,
]


# ──────────────────────────── input models ────────────────────────────
class ClearanceObject(BaseModel):
    """The thing being cleared (a dataset, a drug, a sample, ...)."""
    object_type: str
    name: Optional[str] = None
    source: Optional[str] = None
    identifiers: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Actor(BaseModel):
    """Who is using the object, and under what organizational context."""
    actor_type: Optional[str] = None
    country: Optional[str] = None
    organization_type: Optional[str] = None
    foreign_controlled: Optional[bool] = None
    role: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UseCase(BaseModel):
    """What the object is used for."""
    category: str
    description: Optional[str] = None
    commercial: Optional[bool] = None
    clinical: Optional[bool] = None
    ai_training: Optional[bool] = None
    publication: Optional[bool] = None
    research_only: Optional[bool] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Jurisdiction(BaseModel):
    """Which legal jurisdictions and markets are in scope."""
    countries: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    target_market: list[str] = Field(default_factory=list)
    analysis_level: Optional[str] = None


class DataFlow(BaseModel):
    """Where the data lives, where it is processed, and how it moves."""
    storage_location: Optional[str] = None
    processing_location: Optional[str] = None
    cross_border: Optional[bool] = None
    external_sharing: Optional[bool] = None
    cloud_processing: Optional[bool] = None
    third_parties: list[str] = Field(default_factory=list)
    output_distribution: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssessmentTime(BaseModel):
    """assessment_date = when we judge; effective_on = which rule-vintage applies
    (defaults to assessment_date)."""
    assessment_date: str
    effective_on: Optional[str] = None


class AssessmentInput(BaseModel):
    object: ClearanceObject
    actor: Actor
    use_case: UseCase
    jurisdiction: Jurisdiction
    data_flow: DataFlow
    time: AssessmentTime
    query: Optional[str] = None


# ──────────────────────────── output models ────────────────────────────
class Condition(BaseModel):
    condition_id: str
    text: str


class Risk(BaseModel):
    risk_id: str
    level: str
    text: str


class EvidenceItem(BaseModel):
    evidence_id: str
    title: str
    source_type: str
    jurisdiction: Optional[str] = None
    authority: Optional[str] = None
    url: Optional[str] = None
    citation: Optional[str] = None
    effective_date: Optional[str] = None
    last_checked_at: Optional[str] = None
    excerpt: Optional[str] = None
    reliability: str = Reliability.unknown.value


class TriggeredRule(BaseModel):
    rule_id: str
    version: str
    verdict: str
    risk_level: str
    reason: str


class MissingInformation(BaseModel):
    field: str
    severity: str
    message: str


class NextAction(BaseModel):
    action_id: str
    priority: str
    text: str


class JurisdictionVerdict(BaseModel):
    jurisdiction: str
    verdict: str
    risk_level: str
    summary: str


class ClearanceReport(BaseModel):
    assessment_id: str
    core_version: str
    domain_pack_id: str
    domain_pack_version: str

    normalized_input: AssessmentInput

    overall_verdict: str
    risk_level: str
    confidence: str

    summary: str
    conditions: list[Condition] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    triggered_rules: list[TriggeredRule] = Field(default_factory=list)
    missing_information: list[MissingInformation] = Field(default_factory=list)
    next_actions: list[NextAction] = Field(default_factory=list)

    jurisdiction_matrix: list[JurisdictionVerdict] = Field(default_factory=list)

    disclaimers: list[str] = Field(default_factory=list)


# ──────────────────────────── routing / normalize responses ─────────────
class DomainCandidate(BaseModel):
    """One ranked routing candidate returned by the router."""
    domain_pack_id: str
    score: float
    reason: str


class NormalizeResponse(BaseModel):
    """Response of POST /api/assessments/normalize — the AI-autofill step."""
    normalized_input: AssessmentInput
    domain_candidates: list[DomainCandidate] = Field(default_factory=list)
    missing_information: list[MissingInformation] = Field(default_factory=list)
    llm_used: bool = False
    warnings: list[str] = Field(default_factory=list)
