"""
gate.py — the deterministic applicability gate + purpose-matrix composer.

NO free legal reasoning here (that is the retrieval agent's job, quote-verified
against primary sources). This layer answers, from structured facts: which laws
are even in play, what are the off-ramps, what's the verdict for research vs
commercial — and what do you still need to find out?

Design invariants:
  * De-identification is the master off-ramp (checked first) but is contingent.
  * The CONTRACT layer (controlled access / license / ToS) is often the real gate
    for a found dataset and is checked independently of any statute.
  * LAWFUL BASIS matters: identifiable + sensitive + no consent (and no IRB for
    research / no commercial grant for commercial) is NOT "just do the paperwork" —
    it escalates toward `restricted`. This is what keeps the gate from being
    over-optimistic (the earlier build ignored consent entirely).
  * Open-world: absence of a modeled trigger is reported as limited coverage,
    never as "cleared". Critical unknown facts route to "insufficient".
  * `requires_approval` = a known path exists (IRB / DUA / license).
    `restricted`      = presumptively not permissible as-is, no ready path.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from .schema import (
    AssessmentInput, DataUseReport, LawFinding, OfframpFinding, PurposeVerdict,
)

ENGINE_VERSION = "0.2.0"

_REGISTRY = json.loads((Path(__file__).parent / "source_registry.json").read_text())
_SOURCES_BY_LAW: dict[str, list[str]] = {}
for _s in _REGISTRY.get("sources", []):
    _SOURCES_BY_LAW.setdefault(_s["law_id"], []).append(_s["source_id"])

# identifiability values that strongly remove a dataset from most statutes
_DEID_STRONG = {"deidentified_hipaa_safeharbor", "deidentified_expert",
                "anonymized", "aggregate"}
_DEID_WEAK = {"deidentified_other", "pseudonymized"}
# values that mean we affirmatively KNOW the data is still identifiable personal data
_IDENTIFIABLE = {"identified", "pseudonymized", "deidentified_other"}
# categories that carry heightened statutory / ethical exposure
_SENSITIVE_CATS = {"health", "genetic", "biometric"}

DISCLAIMERS = [
    "This tool identifies potentially applicable laws and obligations. It is not legal advice and does not determine that a proposed use is lawful.",
    "Coverage is limited to modeled U.S. privacy and data-use laws. It does not cover copyright, intellectual property, non-U.S. laws such as GDPR or PIPL, or every state law. Absence of a flag is not clearance.",
    "Review the cited primary sources directly and consult qualified counsel before making formal decisions.",
]

# verdict severity for merging within one purpose (most severe first)
_VERDICT_PRIORITY = ["restricted", "requires_approval", "conditionally_allowed",
                     "insufficient", "allowed"]


def _merge_verdict(cands: list[str]) -> str:
    present = set(cands)
    for v in _VERDICT_PRIORITY:
        if v in present:
            return v
    return "insufficient"


def _has(lst, item) -> bool:
    return item in (lst or [])


def _yesish(v) -> bool:
    """True only if explicitly True (unknown/None does not count)."""
    return v is True


def _unknown(v) -> bool:
    return v is None


# ─────────────────────────── derived facts ───────────────────────────
def _purposes(inp: AssessmentInput) -> set[str]:
    """Derive the purpose set from the use_case booleans. Unknown → evaluate both."""
    uc = inp.use_case
    ps: set[str] = set()
    if _yesish(uc.commercial):
        ps.add("commercial")
    if _yesish(uc.research_only) or _yesish(uc.publication) or _yesish(uc.clinical):
        ps.add("research")
    if uc.commercial is False and "research" not in ps:
        ps.add("research")          # explicitly non-commercial → treat as research
    return ps or {"research", "commercial"}


def _states(inp: AssessmentInput) -> list[str]:
    return [r.lower() for r in (inp.jurisdiction.regions or [])]


# ─────────────────────────── off-ramps ───────────────────────────
def _deid_offramp(inp: AssessmentInput) -> OfframpFinding | None:
    idf = inp.object.identifiability
    if idf in _DEID_STRONG:
        return OfframpFinding(
            kind="deidentification",
            effect="reduces statutory exposure",
            detail=("The data is de-identified, anonymous, or aggregate, which can place it outside HIPAA and exempt it under many state comprehensive privacy laws. "
                    "That status is conditional: re-identification is prohibited, holders must not attempt re-identification, and contract, license, and intellectual-property restrictions still apply. "
                    "HIPAA Safe Harbor and expert determination are the reliable de-identification pathways."))
    if idf in _DEID_WEAK:
        return OfframpFinding(
            kind="deidentification",
            effect="does NOT remove statutes",
            detail=("The data is only pseudonymized or de-identified by an unspecified method. Under many laws it remains personal data. "
                    "Confirm the de-identification method before relying on this status, especially HIPAA Safe Harbor versus expert determination."))
    return None


def _contract_offramps(inp: AssessmentInput) -> list[OfframpFinding]:
    out: list[OfframpFinding] = []
    d = inp.object
    # The matrix always evaluates a commercial row (as a hypothetical), and _purpose_verdict's
    # commercial contract block fires accordingly; generate commercial off-ramps whenever
    # commercial is not explicitly ruled out, so each commercial verdict has a visible driver.
    commercial = inp.use_case.commercial is not False
    if d.source_type == "controlled_access" and not _yesish(d.has_dua):
        out.append(OfframpFinding(
            kind="contract", effect="blocks use until access granted",
            detail=("The controlled-access dataset does not yet have an approved data use agreement (DUA). "
                    "It generally should not be used until access is approved and the DUA is executed.")))
    if d.license in ("research_only", "noncommercial") and commercial:
        out.append(OfframpFinding(
            kind="contract", effect="license forbids commercial use",
            detail=f"The dataset license is {d.license!r}; commercial use falls outside that grant. Obtain a commercial license or written permission."))
    if d.license in ("none", "unknown", None) and commercial:
        out.append(OfframpFinding(
            kind="contract", effect="no commercial grant",
            detail="There is no express commercial-use grant. Confirm the terms or obtain permission before any commercial use."))
    if d.source_type == "scraped":
        out.append(OfframpFinding(
            kind="contract", effect="scraping risk",
            detail="Scraped data may violate source terms and can raise CFAA and consent issues. Public availability does not mean the data is free of legal restrictions."))
    if _yesish(d.terms_restrict_use):
        out.append(OfframpFinding(
            kind="contract", effect="ToS restricts use",
            detail="The repository or website terms restrict the proposed use. Review the terms provision by provision."))
    return out


# ─────────────────────────── statutory applicability ───────────────────────────
def _law(law_id, name, status, reason) -> LawFinding:
    return LawFinding(law_id=law_id, name=name, status=status, reason=reason,
                      source_ids=_SOURCES_BY_LAW.get(law_id, []))


def _applicable_laws(inp: AssessmentInput, deidentified: bool) -> list[LawFinding]:
    o, a, uc = inp.object, inp.actor, inp.use_case
    cats = o.data_categories
    res = _states(inp)
    res_known = bool(res)
    commercial = _yesish(uc.commercial)          # explicit only; unknown must NOT assume commercial
    out: list[LawFinding] = []

    # HIPAA — health data held by a covered entity / business associate, not de-identified
    if _has(cats, "health"):
        if deidentified:
            out.append(_law("hipaa", "HIPAA", "likely_exempt",
                            "Health data appears to be de-identified through HIPAA Safe Harbor or expert determination, placing it outside HIPAA."))
        elif a.sector in ("healthcare_covered_entity", "business_associate"):
            out.append(_law("hipaa", "HIPAA", "applies",
                            "PHI held by a covered entity or business associate requires authorization, an IRB waiver, or a limited data set plus DUA."))
        elif a.sector in (None, "unknown"):
            out.append(_law("hipaa", "HIPAA", "need_info",
                            "Health data is present. HIPAA applies only when the source or holder is a covered entity or business associate; confirm the data source."))
        else:
            out.append(_law("hipaa", "HIPAA", "not_applicable",
                            "The data is health data but is not held by a HIPAA covered entity; consumer health laws such as WA MHMDA may apply instead."))
        # Consumer health data (WA MHMDA family) — non-HIPAA health data
        if not deidentified and a.sector not in ("healthcare_covered_entity", "business_associate"):
            wa = "applies" if _has(res, "washington") else ("need_info" if not res_known else "not_applicable")
            out.append(_law("wa_mhmda", "WA My Health My Data Act and consumer health law family", wa,
                            "Consumer health data outside HIPAA, including app, wearable, or inferred health data, may require separate opt-in consent under WA MHMDA and similar laws."))

    # COPPA — children under 13, collected online
    if _yesish(o.includes_children_under_13):
        out.append(_law("coppa", "COPPA", "applies",
                        "Data involving children under 13 can require verifiable parental consent and other COPPA obligations if collected online."))
    elif _unknown(o.includes_children_under_13) and _has(cats, "children"):
        out.append(_law("coppa", "COPPA", "need_info",
                        "Children's data is flagged; confirm whether any subjects are under 13."))

    # BIPA — biometric identifiers, Illinois
    if _has(cats, "biometric") and not deidentified:
        bp = "applies" if _has(res, "illinois") else ("need_info" if not res_known else "not_applicable")
        out.append(_law("bipa", "Illinois BIPA and TX / WA biometric laws", bp,
                        "Biometric identifiers such as face, voiceprint, or fingerprint data can require written informed consent before collection; BIPA also provides a private right of action."))

    # Genetic — GINA / state genetic-privacy
    if _has(cats, "genetic"):
        out.append(_law("gina", "GINA and state genetic privacy laws such as IL GIPA", "applies",
                        "Genetic information can trigger GINA restrictions in insurance and employment and stricter state genetic-privacy consent regimes."))

    # FERPA — education records from an educational institution
    if _has(cats, "education"):
        fp = "applies" if a.sector == "educational_institution" else (
            "need_info" if a.sector in (None, "unknown") else "not_applicable")
        out.append(_law("ferpa", "FERPA", fp,
                        "Education records held by federally funded educational institutions are subject to FERPA, unless consent or a research / audit exception applies."))

    # GLBA — financial data at a financial institution
    if _has(cats, "financial"):
        gp = "applies" if a.sector == "financial_institution" else (
            "need_info" if a.sector in (None, "unknown") else "not_applicable")
        out.append(_law("glba", "GLBA", gp,
                        "Nonpublic personal financial information held by a financial institution is subject to GLBA privacy and safeguards requirements."))

    # VPPA — video viewing records
    if _has(cats, "video_viewing"):
        out.append(_law("vppa", "VPPA", "applies",
                        "Video viewing or rental records are protected by VPPA, generally requiring consent and allowing a private right of action."))

    # State comprehensive laws (CCPA/CPRA + VCDPA family) — personal data of state residents
    if o.contains_personal_data is not False:
        if deidentified:
            out.append(_law("ccpa", "State comprehensive privacy laws (CCPA/CPRA and VCDPA family)", "likely_exempt",
                            "State comprehensive privacy laws often exempt de-identified or aggregate data, subject to prohibitions on re-identification."))
        elif _yesish(a.for_profit) or commercial:
            if a.meets_state_threshold is False:
                out.append(_law("ccpa", "State comprehensive privacy laws (CCPA/CPRA and VCDPA family)", "likely_exempt",
                                "The actor appears below size or volume thresholds; comprehensive privacy laws generally bind covered businesses that meet statutory thresholds."))
            else:
                st = "applies" if res_known else "need_info"
                out.append(_law("ccpa", "State comprehensive privacy laws (CCPA/CPRA and VCDPA family)", st,
                                "A for-profit or commercial actor processing state residents' personal data may owe notice, opt-out, access, deletion, and sensitive-data consent or limitation obligations. Applicability depends on thresholds, research exceptions, and each subject's state of residence."))
        elif a.actor_type in ("researcher_individual", "academic_institution", "nonprofit"):
            out.append(_law("ccpa", "State comprehensive privacy laws (CCPA/CPRA and VCDPA family)", "likely_exempt",
                            "Individual, academic, or nonprofit researchers often are not covered businesses, although several states do not exempt nonprofits and upstream obligations may still follow the data."))
        else:
            out.append(_law("ccpa", "State comprehensive privacy laws (CCPA/CPRA and VCDPA family)", "need_info",
                            "Personal data appears to be involved; confirm the subjects' states of residence and whether the actor meets any comprehensive privacy law threshold."))

    # Common Rule / IRB — human-subjects research pathway (identifiable human data only).
    # The matrix always shows a research row, so evaluate whenever identifiable personal
    # data is present; it drives only the research verdict (see _purpose_verdict).
    if _yesish(o.contains_personal_data) and not deidentified:
        irb = inp.basis.irb_status
        if irb in ("approved", "exempt"):
            out.append(_law("common_rule", "Common Rule (45 CFR 46) / IRB", "likely_exempt",
                            f"Human-subjects research pathway is identified, and the IRB status is {irb!r}."))
        else:
            out.append(_law("common_rule", "Common Rule (45 CFR 46) / IRB", "applies",
                            "Research using identifiable human data generally requires IRB review or an exemption / waiver determination under 45 CFR 46. For researchers, this is often the controlling review pathway."))

    return out


# ─────────────────────────── missing info ───────────────────────────
def _missing(inp: AssessmentInput, deidentified: bool) -> list[str]:
    m: list[str] = []
    o, a, uc, b = inp.object, inp.actor, inp.use_case, inp.basis
    purposes = _purposes(inp)
    identifiable = _identifiable(inp, deidentified)
    if _unknown(o.contains_personal_data):
        m.append("Does the dataset contain personal information that can be linked to a specific person? This is a threshold fact for assessment.")
    if o.identifiability in (None, "unknown"):
        m.append("What is the identifiability level: directly identifiable, pseudonymized, de-identified by what method, anonymous, or aggregate only?")
    if not inp.jurisdiction.regions and o.contains_personal_data is not False:
        m.append("Which states or regions are the data subjects residents of? Residence determines which state laws may apply.")
    if o.license in (None, "unknown"):
        m.append("What license or use terms apply to this dataset?")
    if o.source_type in (None, "unknown"):
        m.append("How was the data obtained: public download, controlled access, collaborator, web scraping, or another route?")
    if a.sector in (None, "unknown") and _has(o.data_categories, "health"):
        m.append("Are you or the data source a HIPAA covered entity or business associate? This determines whether HIPAA applies.")
    if (uc.commercial is None and uc.research_only is None
            and uc.publication is None and uc.clinical is None):
        m.append("Will the data be used for research, commercial purposes, or both?")
    if b.consent_covers_use is None and identifiable:
        m.append("Does the consent obtained at collection cover the proposed use? Lack of consent can materially affect the assessment.")
    if ("research" in purposes and b.irb_status in (None, "unknown")
            and identifiable):
        m.append("For research using identifiable human data, has an IRB approved the activity or determined it exempt?")
    return m


# ─────────────────────────── purpose matrix ───────────────────────────
def _identifiable(inp: AssessmentInput, deidentified: bool) -> bool:
    """We affirmatively KNOW the data is still identifiable personal data.
    Unknown does NOT count (that routes to 'insufficient'/missing instead)."""
    o = inp.object
    return (o.contains_personal_data is True) and (o.identifiability in _IDENTIFIABLE) and not deidentified


def _purpose_verdict(purpose: str, inp: AssessmentInput, deidentified: bool,
                     offramps: list[OfframpFinding], laws: list[LawFinding]) -> PurposeVerdict:
    cands: list[str] = []
    o, uc, b = inp.object, inp.use_case, inp.basis

    # hard contract blocks
    if o.source_type == "controlled_access" and not _yesish(o.has_dua):
        cands.append("requires_approval")
    if purpose == "commercial":
        if o.license in ("research_only", "noncommercial"):
            cands.append("restricted")
        elif o.license in ("none", "unknown", None):
            cands.append("requires_approval")

    # statutory pressure
    heavy = {"hipaa", "coppa", "common_rule", "bipa", "gina"}
    for lf in laws:
        if lf.status == "applies":
            if lf.law_id == "common_rule" and purpose != "research":
                continue                     # IRB is a research-only pathway — never inflates commercial
            cands.append("requires_approval" if lf.law_id in heavy else "conditionally_allowed")

    # ── lawful-basis escalation (this is what fixes the over-optimism) ──
    identifiable = _identifiable(inp, deidentified)
    sensitive = bool(set(o.data_categories) & _SENSITIVE_CATS)
    no_consent = b.consent_covers_use is not True     # None or False → basis not established
    if identifiable and no_consent:
        if _yesish(uc.secondary_use):
            cands.append("requires_approval")          # secondary use without consent needs a basis
        if sensitive:
            if purpose == "commercial":
                # identifiable + sensitive + no consent for commercial use → no ready path.
                # NOT gated on license: a copyright/usage license is not a privacy consent
                # (the commercial-license concern is handled separately as a contract off-ramp).
                cands.append("restricted")
            elif purpose == "research" and b.irb_status not in ("approved", "exempt"):
                cands.append("requires_approval")      # IRB (possibly a consent waiver) is the path

    # Only CRITICAL unknowns route to insufficient; a real block/obligation outranks it.
    critical_unknown = (_unknown(o.contains_personal_data)
                        or o.identifiability in (None, "unknown")
                        or (uc.commercial is None and uc.research_only is None
                            and uc.publication is None and uc.clinical is None))
    if critical_unknown:
        cands.append("insufficient")

    if not cands:
        cands.append("allowed")

    verdict = _merge_verdict(cands)
    phrase = {
        "allowed": "the use appears viable with ordinary precautions such as source attribution and compliance with terms.",
        "conditionally_allowed": "the use appears viable only after specific obligations are satisfied.",
        "requires_approval": "authorization, approval, an IRB determination, DUA, or license is required before proceeding.",
        "restricted": "the use is not recommended on the current facts and requires a different use plan or additional authorization.",
        "insufficient": "the use cannot yet be assessed because key facts are missing.",
    }[verdict]

    # per-purpose drivers: which laws / contract blocks actually cause THIS verdict.
    applies = [l for l in laws if l.status == "applies"]
    because_laws = [l.law_id for l in applies
                    if not (l.law_id == "common_rule" and purpose != "research")]
    commercial_only = {"no commercial grant", "license forbids commercial use"}
    because_contract = [ofr.effect for ofr in offramps
                        if ofr.kind == "contract"
                        and not (ofr.effect in commercial_only and purpose != "commercial")]

    return PurposeVerdict(purpose=purpose, verdict=verdict,
                          summary=f"For {'research' if purpose == 'research' else 'commercial use'}: {phrase}",
                          because_laws=because_laws, because_contract=because_contract)


# ─────────────────────────── entry point ───────────────────────────
def assess(inp: AssessmentInput) -> DataUseReport:
    deid = inp.object.identifiability in _DEID_STRONG

    offramps: list[OfframpFinding] = []
    d = _deid_offramp(inp)
    if d:
        offramps.append(d)
    offramps.extend(_contract_offramps(inp))

    laws = _applicable_laws(inp, deidentified=deid)
    missing = _missing(inp, deid)

    matrix = [_purpose_verdict(p, inp, deid, offramps, laws)
              for p in ("research", "commercial")]

    applies_ct = sum(1 for l in laws if l.status == "applies")
    _lbl = {"allowed": "preliminarily viable with ordinary precautions",
            "conditionally_allowed": "viable after conditions are satisfied",
            "requires_approval": "authorization or approval required first",
            "restricted": "not recommended on current facts",
            "insufficient": "cannot be assessed yet; key facts are missing"}
    rv = next((m.verdict for m in matrix if m.purpose == "research"), "insufficient")
    cv = next((m.verdict for m in matrix if m.purpose == "commercial"), "insufficient")
    headline = f"Research: {_lbl[rv]}. Commercial: {_lbl[cv]}."
    if applies_ct:
        headline += f" Approximately {applies_ct} modeled law(s) may apply; see obligations."

    conditions = [o.detail for o in offramps if o.kind == "contract"]

    return DataUseReport(
        assessment_id="due_" + uuid.uuid4().hex[:12],
        engine_version=ENGINE_VERSION,
        normalized_input=inp,
        headline=headline,
        offramps=offramps,
        applicable_laws=laws,
        purpose_matrix=matrix,
        conditions=conditions,
        missing_information=missing,
        coverage_note=("Modeled laws: state comprehensive privacy laws (CCPA/CPRA and the VCDPA family), HIPAA, COPPA, "
                       "FERPA, GLBA, BIPA / biometric privacy laws, GINA / genetic privacy, WA MHMDA / consumer health laws, VPPA, "
                       "and the Common Rule / IRB pathway. Unmodeled laws, contract and intellectual-property restrictions, and non-U.S. laws are outside this assessment; absence of a flag is not clearance."),
        disclaimers=list(DISCLAIMERS),
    )
