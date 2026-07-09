"""Regression tests for the adversarial-review findings (all were confirmed real)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.engine import assess
from app.core.normalizer import coerce_to_input
from app.main import app

from .factories import make_input

client = TestClient(app)


# Finding #1 — CN-HGR must fire when sample origin is unstated (normalizer emits "")
def test_cn_hgr_fires_when_sample_origin_absent():
    r = assess(make_input(
        object={"object_type": "dataset", "source": "GEO",
                "metadata": {"organism": "Homo sapiens", "data_type": "RNA-seq"}},  # no sample_origin
        use_case={"category": "differential_expression_analysis", "commercial": True,
                  "clinical": False, "research_only": False},
        jurisdiction={"countries": ["China", "United States"]},
        data_flow={"cross_border": True},
    ))
    ids = {t.rule_id for t in r.triggered_rules}
    assert "CN-HGR-002" in ids
    assert r.overall_verdict == "requires_filing_or_approval"
    assert r.risk_level == "high"


def test_absent_empty_and_unknown_origin_are_equivalent():
    def verdict(origin):
        meta = {"organism": "Homo sapiens", "data_type": "RNA-seq", "data_level": "m"}
        if origin is not None:
            meta["sample_origin"] = origin
        return assess(make_input(
            object={"object_type": "dataset", "source": "GEO", "metadata": meta},
            use_case={"category": "dea", "commercial": True, "clinical": False},
            data_flow={"cross_border": True},
        )).overall_verdict
    assert verdict("unknown") == "requires_filing_or_approval"   # CN-HGR-001
    assert verdict("") == "requires_filing_or_approval"          # CN-HGR-002
    assert verdict(None) == "requires_filing_or_approval"        # CN-HGR-002
    assert verdict("United States") == "conditionally_allowed"   # known non-Chinese → no HGR


# Finding #3 — a non-China jurisdiction must not inherit China's verdict
def test_matrix_non_china_does_not_inherit_china_verdict():
    r = assess(make_input(
        object={"object_type": "dataset", "source": "GEO",
                "metadata": {"organism": "Homo sapiens", "data_type": "RNA-seq",
                             "data_level": "m", "sample_origin": "China"}},
        use_case={"category": "dea", "commercial": False, "clinical": False,
                  "research_only": True, "ai_training": False},
        actor={"country": "United States"},
        jurisdiction={"countries": ["United States"]},
        data_flow={"cross_border": True, "processing_location": "United States"},
    ))
    assert {t.rule_id for t in r.triggered_rules} == {"CN-HGR-001"}  # only the China rule
    us = {j.jurisdiction: j for j in r.jurisdiction_matrix}["United States"]
    assert us.verdict == "insufficient_information"
    assert us.verdict != "requires_filing_or_approval"


# Finding #2 / #8 — coercion must never raise on malformed input
def test_coerce_never_raises_on_malformed_input():
    inp = coerce_to_input({
        "object": {"object_type": 123, "name": ["x"], "identifiers": {"geo": 999}},
        "use_case": {"category": {"nested": 1}, "commercial": "notabool"},
        "jurisdiction": {"countries": ["China", 42, None]},
        "time": {"assessment_date": 20250101},
    })
    assert inp.object.object_type == "123"               # numeric scalar stringified (harmless)
    assert inp.object.name is None                        # list → not a string → None
    assert inp.use_case.category == "unspecified"         # dict → None → default
    assert inp.use_case.commercial is None               # unparseable bool → None
    assert inp.object.identifiers == {"geo": "999"}      # value stringified
    assert inp.jurisdiction.countries == ["China", "42"]  # None dropped, int stringified
    assert isinstance(inp.time.assessment_date, str)     # numeric date stringified, no raise


def test_normalize_endpoint_no_500_on_malformed_input():
    r = client.post("/api/assessments/normalize", json={"input": {
        "object": {"object_type": 123, "identifiers": {"geo": 12345}},
        "use_case": {"category": "x", "commercial": "notabool"},
        "time": {"assessment_date": 20250101},
    }})
    assert r.status_code == 200


# Finding #4 — consent is now a real, fillable path so confidence can reach high
def test_human_confidence_reaches_high_when_all_provided():
    r = assess(make_input(
        object={"object_type": "dataset", "source": "GEO", "metadata": {
            "organism": "Homo sapiens", "data_type": "RNA-seq", "data_level": "m",
            "sample_origin": "United States",
            "data_use_limitations": "research and commercial reuse permitted"}},
        actor={"country": "United States"},
        use_case={"category": "dea", "commercial": True, "clinical": False,
                  "ai_training": False, "research_only": False},
        jurisdiction={"countries": ["United States"]},
        data_flow={"cross_border": False, "processing_location": "United States"},
    ))
    assert not r.missing_information
    assert r.confidence == "high"
