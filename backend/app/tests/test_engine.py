"""The five spec scenarios (section 20), exercised through the Core Engine."""
from __future__ import annotations

from app.core.engine import assess
from app.core.router import route
from app.domain_packs import get_pack_by_id

from .factories import make_input


# Test 1 — Human GEO + commercial + cross-border
def test_human_geo_commercial_crossborder():
    inp = make_input(
        object={"object_type": "dataset", "name": "GSE12345", "source": "GEO",
                "metadata": {"organism": "Homo sapiens", "data_type": "RNA-seq",
                             "data_level": "processed_matrix", "sample_origin": "unknown"}},
        actor={"actor_type": "company", "country": "China"},
        use_case={"category": "differential_expression_analysis", "commercial": True,
                  "clinical": False, "research_only": False},
        jurisdiction={"countries": ["China", "United States"]},
        data_flow={"cross_border": True, "cloud_processing": True,
                   "processing_location": "United States"},
    )
    r = assess(inp)
    assert r.domain_pack_id == "biodata"
    assert r.risk_level == "high"
    assert r.overall_verdict in ("conditionally_allowed", "requires_filing_or_approval")
    ids = {t.rule_id for t in r.triggered_rules}
    assert "BIO-HUMAN-001" in ids
    # sample_origin is "unknown" and cross_border is true → HGR rule must fire
    assert "CN-HGR-001" in ids


# Test 2 — Mouse GEO + research-only DEA
def test_mouse_geo_research_only():
    inp = make_input(
        object={"object_type": "dataset", "source": "GEO",
                "metadata": {"organism": "Mus musculus", "data_type": "RNA-seq",
                             "data_level": "processed_matrix", "sample_origin": "lab_mouse"}},
        actor={"country": "United States"},
        use_case={"category": "differential_expression_analysis", "commercial": False,
                  "clinical": False, "research_only": True, "ai_training": False},
        jurisdiction={"countries": ["United States"]},
        data_flow={"cross_border": False, "cloud_processing": False,
                   "processing_location": "United States"},
    )
    r = assess(inp)
    assert r.domain_pack_id == "biodata"
    assert r.overall_verdict == "allowed"
    assert r.risk_level == "low"
    assert "BIO-GEO-001" in {t.rule_id for t in r.triggered_rules}


# Test 3 — Missing organism
def test_missing_organism():
    inp = make_input(
        object={"object_type": "dataset", "source": "GEO",
                "metadata": {"data_type": "RNA-seq"}},
        actor={"country": "China"},
        use_case={"category": "differential_expression_analysis", "commercial": True,
                  "clinical": False},
        jurisdiction={"countries": ["China"]},
        data_flow={"cross_border": True},
    )
    r = assess(inp)
    fields = {m.field for m in r.missing_information}
    assert "object.metadata.organism" in fields
    assert r.overall_verdict == "insufficient_information" or r.confidence == "low"


# Test 4 — Drug procurement routes correctly (stub)
def test_drug_procurement_routes_to_stub():
    inp = make_input(object={"object_type": "drug", "name": "SomeDrug"},
                     use_case={"category": "procurement"})
    cands = route(inp)
    assert cands[0].domain_pack_id == "drug_procurement"
    assert get_pack_by_id("drug_procurement").status == "stub"
    r = assess(inp)
    assert r.domain_pack_id == "drug_procurement"
    assert r.overall_verdict == "insufficient_information"


# Test 5 — Unknown object routes to custom
def test_unknown_object_routes_to_custom():
    inp = make_input(object={"object_type": "unknown", "name": "???"})
    r = assess(inp)
    assert r.domain_pack_id == "custom"
    assert r.overall_verdict == "insufficient_information"
