"""BioData pack behaviour: rule firing, verdict merge, confidence, missing-info gating."""
from __future__ import annotations

from app.core.engine import assess

from .factories import make_input


def test_clinical_human_requires_approval():
    r = assess(make_input(
        object={"object_type": "dataset", "source": "GEO",
                "metadata": {"organism": "Homo sapiens", "data_type": "RNA-seq"}},
        use_case={"category": "clinical_screening", "clinical": True, "commercial": False},
        data_flow={"cross_border": False},
    ))
    assert "BIO-CLINICAL-001" in {t.rule_id for t in r.triggered_rules}
    assert r.overall_verdict == "requires_filing_or_approval"
    assert r.risk_level == "high"


def test_verdict_merge_picks_highest_priority():
    # Human + commercial (conditionally_allowed) AND clinical (requires_filing) →
    # the higher-priority verdict wins.
    r = assess(make_input(
        object={"object_type": "dataset", "source": "GEO",
                "metadata": {"organism": "Homo sapiens", "data_type": "RNA-seq",
                             "sample_origin": "United States"}},
        use_case={"category": "biomarker", "commercial": True, "clinical": True},
        data_flow={"cross_border": False},
    ))
    ids = {t.rule_id for t in r.triggered_rules}
    assert {"BIO-HUMAN-001", "BIO-CLINICAL-001"} <= ids
    assert r.overall_verdict == "requires_filing_or_approval"


def test_missing_organism_not_cleared_as_nonhuman():
    # Safety: an unknown organism must NOT satisfy organism_not:[human] and clear.
    r = assess(make_input(
        object={"object_type": "dataset", "source": "GEO",
                "metadata": {"data_type": "RNA-seq"}},
        use_case={"category": "differential_expression_analysis", "research_only": True,
                  "commercial": False, "clinical": False},
        data_flow={"cross_border": False},
    ))
    assert "BIO-GEO-001" not in {t.rule_id for t in r.triggered_rules}
    assert r.overall_verdict != "allowed"


def test_sample_origin_flagged_only_for_human():
    non_human = assess(make_input(
        object={"object_type": "dataset", "source": "GEO",
                "metadata": {"organism": "Mus musculus", "data_type": "RNA-seq",
                             "data_level": "processed_matrix"}},
        actor={"country": "United States"},
        use_case={"category": "differential_expression_analysis", "research_only": True,
                  "commercial": False, "clinical": False, "ai_training": False},
        data_flow={"cross_border": False, "processing_location": "United States"},
    ))
    fields = {m.field for m in non_human.missing_information}
    assert "object.metadata.sample_origin" not in fields
    assert non_human.confidence == "high"


def test_complete_human_commercial_has_medium_confidence():
    # All 5 critical fields present, but sample_origin unknown + consent unknown →
    # rules fire, secondary info missing → confidence medium (not low).
    r = assess(make_input(
        object={"object_type": "dataset", "source": "GEO",
                "metadata": {"organism": "Homo sapiens", "data_type": "RNA-seq",
                             "data_level": "processed_matrix", "sample_origin": "unknown"}},
        actor={"country": "China"},
        use_case={"category": "differential_expression_analysis", "commercial": True,
                  "clinical": False, "ai_training": False, "research_only": False},
        jurisdiction={"countries": ["China", "United States"]},
        data_flow={"cross_border": True, "cloud_processing": True,
                   "processing_location": "United States"},
    ))
    assert r.confidence == "medium"
    # China entry should escalate to the HGR verdict; US should not.
    by_j = {j.jurisdiction: j for j in r.jurisdiction_matrix}
    assert by_j["China"].verdict == "requires_filing_or_approval"
    assert by_j["United States"].verdict == "conditionally_allowed"


def test_evidence_only_referenced_items_returned():
    r = assess(make_input(
        object={"object_type": "dataset", "source": "GEO",
                "metadata": {"organism": "Mus musculus", "data_type": "RNA-seq",
                             "data_level": "x", "sample_origin": "lab"}},
        actor={"country": "US"},
        use_case={"category": "differential_expression_analysis", "research_only": True,
                  "commercial": False, "clinical": False, "ai_training": False},
        data_flow={"cross_border": False, "processing_location": "US"},
    ))
    # BIO-GEO-001 references only EV-GEO-TERMS-001.
    assert [e.evidence_id for e in r.evidence] == ["EV-GEO-TERMS-001"]
    assert r.evidence[0].reliability == "database_terms"
