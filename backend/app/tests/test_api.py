"""API-level tests via FastAPI TestClient (no live server, no network)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from .factories import SPEC_EXAMPLE

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["core_version"] == "0.1.0-alpha.1"


def test_domain_packs():
    data = client.get("/api/domain-packs").json()
    ids = {p["id"] for p in data}
    assert {"biodata", "genetic_testing", "drug_procurement",
            "agricultural_genomics", "custom"} <= ids
    by_id = {p["id"]: p for p in data}
    assert by_id["biodata"]["status"] == "active"
    assert by_id["drug_procurement"]["status"] == "stub"


def test_settings_never_leaks_key():
    s = client.get("/api/settings").json()
    assert "backend" in s and "providers" in s
    assert "api_key" not in s["backend"]          # only has_key + key_hint
    provider_ids = {p["id"] for p in s["providers"]}
    assert {"deepseek", "openai", "claude", "qwen"} <= provider_ids


def test_assessment_spec_example():
    r = client.post("/api/assessments", json=SPEC_EXAMPLE)
    assert r.status_code == 200
    j = r.json()
    assert j["domain_pack_id"] == "biodata"
    assert j["overall_verdict"] == "requires_filing_or_approval"
    assert j["risk_level"] == "high"
    assert j["confidence"] == "medium"
    assert {t["rule_id"] for t in j["triggered_rules"]} >= {"BIO-HUMAN-001", "CN-HGR-001"}
    assert j["disclaimers"]
    assert j["assessment_id"].startswith("asm_")


def test_assessment_never_binary_legal_illegal():
    j = client.post("/api/assessments", json=SPEC_EXAMPLE).json()
    assert j["overall_verdict"] in {
        "allowed", "conditionally_allowed", "requires_filing_or_approval",
        "restricted_not_recommended", "insufficient_information",
    }


def test_normalize_without_key_degrades_gracefully():
    r = client.post("/api/assessments/normalize",
                    json={"text": "human GEO dataset for commercial use, cross-border"})
    assert r.status_code == 200
    j = r.json()
    assert j["llm_used"] is False
    assert any(("LLM" in w) or ("key" in w) for w in j["warnings"])


def test_normalize_structured_routes_and_flags_missing():
    r = client.post("/api/assessments/normalize", json={"input": {
        "object": {"object_type": "dataset", "source": "GEO",
                   "metadata": {"organism": "Homo sapiens", "data_type": "RNA-seq"}},
        "use_case": {"category": "differential_expression_analysis", "commercial": True},
        "data_flow": {"cross_border": True},
    }})
    assert r.status_code == 200
    j = r.json()
    assert j["domain_candidates"][0]["domain_pack_id"] == "biodata"
    fields = {m["field"] for m in j["missing_information"]}
    assert "object.metadata.sample_origin" in fields   # human → sample origin flagged
