"""Small builder so tests read as scenarios, not schema boilerplate."""
from __future__ import annotations

from app.models.schemas import AssessmentInput

TIME = {"assessment_date": "2026-07-07", "effective_on": "2026-07-07"}


def make_input(*, object=None, actor=None, use_case=None,
               jurisdiction=None, data_flow=None, time=None) -> AssessmentInput:
    return AssessmentInput(
        object=object or {"object_type": "dataset"},
        actor=actor or {},
        use_case=use_case or {"category": "unspecified"},
        jurisdiction=jurisdiction or {},
        data_flow=data_flow or {},
        time=time or TIME,
    )


# The canonical spec example (human GEO, commercial, cross-border, sample unknown).
SPEC_EXAMPLE = {
    "object": {"object_type": "dataset", "name": "GSE12345", "source": "GEO",
               "identifiers": {"geo_accession": "GSE12345"},
               "metadata": {"organism": "Homo sapiens", "data_type": "RNA-seq",
                            "data_level": "processed_matrix", "sample_origin": "unknown"}},
    "actor": {"actor_type": "company", "country": "China",
              "organization_type": "biotech_company", "foreign_controlled": False,
              "role": "data_user"},
    "use_case": {"category": "differential_expression_analysis", "commercial": True,
                 "clinical": False, "ai_training": False, "publication": True,
                 "research_only": False},
    "jurisdiction": {"countries": ["China", "United States"], "regions": [],
                     "target_market": ["China", "United States"], "analysis_level": "country"},
    "data_flow": {"storage_location": "United States", "processing_location": "United States",
                  "cross_border": True, "external_sharing": False, "cloud_processing": True,
                  "third_parties": ["cloud_provider"],
                  "output_distribution": ["internal_report", "publication"]},
    "time": {"assessment_date": "2026-07-07", "effective_on": "2026-07-07"},
    "query": "Can this GEO dataset be used for DEA and commercial biomarker exploration?",
}
