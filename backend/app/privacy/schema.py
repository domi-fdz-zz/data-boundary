"""
schema.py — the seven-dimension AssessmentInput for the data-use / privacy check.

Structure follows the original clearance model (object / actor / use_case /
jurisdiction / data_flow / time) so the existing schema card can drive it, but
the privacy-decisive facts are PROMOTED to typed fields (not buried in free-form
metadata) so the deterministic gate can key on them:

  * object.identifiability / data_categories / contains_personal_data / license /
    source_type — what US privacy applicability actually turns on;
  * actor.sector / for_profit — is this a HIPAA covered entity, a covered business;
  * basis.consent_covers_use / irb_status — the lawful-basis dimension (added so
    "no consent / no IRB" pushes the verdict down instead of being ignored).

Every fact is tri-state-able (True / False / None=unknown) or a list; "unknown"
is first-class — the gate reasons about it rather than treating it as False.
The China / cross-border fields (foreign_controlled, target_market, cross_border)
are kept for the broader vision but are NOT wired into the US-privacy gate yet.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ClearanceObject(BaseModel):
    """The thing being cleared (a dataset) — provenance, contract, and what's inside."""
    object_type: Optional[str] = None            # dataset / sample / model / ...
    name: Optional[str] = None
    source: Optional[str] = None                 # GEO / dbGaP / Kaggle / a vendor / ...
    identifiers: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    # ── promoted: what is actually in the data (drives which statutes bite) ──
    contains_personal_data: Optional[bool] = None
    # identified / pseudonymized / deidentified_hipaa_safeharbor / deidentified_expert /
    # deidentified_other / anonymized / aggregate / unknown
    identifiability: Optional[str] = None
    # health, financial, education, biometric, genetic, children, contact,
    # precise_geo, video_viewing, driver, behavioral, ...
    data_categories: list[str] = Field(default_factory=list)
    publicly_available: Optional[bool] = None
    includes_children_under_13: Optional[bool] = None
    non_us_subjects: Optional[bool] = None
    # ── promoted: provenance / the contract that rides with the dataset ──
    # public_open / public_registered / controlled_access / collaborator / scraped / internal / unknown
    source_type: Optional[str] = None
    # permissive / research_only / noncommercial / none / unknown
    license: Optional[str] = None
    has_dua: Optional[bool] = None
    terms_restrict_use: Optional[bool] = None


class Actor(BaseModel):
    """Who you are — comprehensive laws only bind covered entities above thresholds."""
    actor_type: Optional[str] = None             # company / academic_institution / researcher_individual / nonprofit
    country: Optional[str] = None
    organization_type: Optional[str] = None
    foreign_controlled: Optional[bool] = None    # dormant (China/cross-border) — not wired into the US gate
    role: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    # ── promoted ──
    for_profit: Optional[bool] = None
    # healthcare_covered_entity / business_associate / financial_institution /
    # educational_institution / none / unknown
    sector: Optional[str] = None
    meets_state_threshold: Optional[bool] = None  # over a comprehensive-law size/volume threshold
    is_funded: Optional[bool] = None              # e.g. NIH funding → DMS/GDS obligations


class UseCase(BaseModel):
    category: Optional[str] = None
    description: Optional[str] = None
    commercial: Optional[bool] = None
    clinical: Optional[bool] = None
    ai_training: Optional[bool] = None
    publication: Optional[bool] = None
    research_only: Optional[bool] = None
    redistribute: Optional[bool] = None
    secondary_use: Optional[bool] = None          # use differs from the original collection purpose
    metadata: dict[str, Any] = Field(default_factory=dict)


class Jurisdiction(BaseModel):
    countries: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)        # US states — drives state-law applicability (residency)
    target_market: list[str] = Field(default_factory=list)  # dormant
    analysis_level: Optional[str] = None


class DataFlow(BaseModel):
    storage_location: Optional[str] = None
    processing_location: Optional[str] = None
    cross_border: Optional[bool] = None            # dormant for the US gate
    external_sharing: Optional[bool] = None
    cloud_processing: Optional[bool] = None
    third_parties: list[str] = Field(default_factory=list)
    output_distribution: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Basis(BaseModel):
    """The lawful-basis dimension — added so 'no consent / no IRB' actually counts."""
    consent_covers_use: Optional[bool] = None
    irb_status: Optional[str] = None               # approved / exempt / pending / none / unknown


class AssessmentTime(BaseModel):
    assessment_date: Optional[str] = None
    effective_on: Optional[str] = None             # the date whose law should apply; default = assessment_date


class AssessmentInput(BaseModel):
    object: ClearanceObject = Field(default_factory=ClearanceObject)
    actor: Actor = Field(default_factory=Actor)
    use_case: UseCase = Field(default_factory=UseCase)
    jurisdiction: Jurisdiction = Field(default_factory=Jurisdiction)
    data_flow: DataFlow = Field(default_factory=DataFlow)
    basis: Basis = Field(default_factory=Basis)
    time: AssessmentTime = Field(default_factory=AssessmentTime)
    query: Optional[str] = None


# ─────────────────────────── output models ───────────────────────────
class LawFinding(BaseModel):
    law_id: str
    name: str
    status: str          # applies / likely_exempt / need_info / not_applicable
    reason: str
    source_ids: list[str] = Field(default_factory=list)


class OfframpFinding(BaseModel):
    kind: str            # deidentification / contract / actor_threshold
    effect: str
    detail: str


class PurposeVerdict(BaseModel):
    purpose: str         # research / commercial
    verdict: str         # allowed / conditionally_allowed / requires_approval / restricted / insufficient
    summary: str
    narration: Optional[str] = None                            # case-specific explanation (does NOT change the verdict)
    because_laws: list[str] = Field(default_factory=list)      # law_ids driving THIS purpose
    because_contract: list[str] = Field(default_factory=list)  # off-ramp effect keys driving THIS purpose


class ResearchLead(BaseModel):
    """A deep-scan finding: a law/authority possibly relevant to THIS case, incl.
    ones outside the modeled set. Always a primary source, always quote-verified;
    surfaced as a direction to check, never as a settled verdict."""
    title: str
    why: str
    citation: Optional[str] = None
    source_url: Optional[str] = None
    quote: Optional[str] = None
    modeled: bool = False


class DataUseReport(BaseModel):
    assessment_id: str
    engine_version: str
    normalized_input: AssessmentInput
    headline: str
    offramps: list[OfframpFinding] = Field(default_factory=list)
    applicable_laws: list[LawFinding] = Field(default_factory=list)
    purpose_matrix: list[PurposeVerdict] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    coverage_note: str = ""
    disclaimers: list[str] = Field(default_factory=list)
