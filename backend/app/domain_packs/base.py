"""
base.py — the DomainPack interface and two concrete, config-driven bases.

A domain pack is a self-contained folder:

    <pack>/
      config.json            id / name / version / routing hints / field_map /
                             required_fields (missing-info specs) / stub defaults
      rules.json             the deterministic rules (empty for stubs)
      evidence_fixtures.json  the citations (empty for stubs)
      pack.py                exposes get_pack() -> DomainPack

ConfigDrivenPack implements the full flow from that data, so the "real" BioData
pack needs no bespoke Python. StubPack short-circuits to a fixed verdict +
explanatory summary (still reporting any missing information).
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .. import CORE_VERSION
from ..models.schemas import (
    AssessmentInput,
    ClearanceReport,
    EvidenceItem,
    MissingInformation,
)
from ..core.rule_engine import evaluate_rules, rule_matches, resolve_path, is_missing, _norm
from ..core.evidence import FixtureEvidenceRetriever
from ..core.report_generator import build_report, build_stub_report


# ─────────────────────────── the interface ───────────────────────────
@runtime_checkable
class DomainPack(Protocol):
    id: str
    name: str
    version: str
    status: str
    supported_object_types: list[str]

    def detect(self, assessment: AssessmentInput) -> float:
        """Confidence in [0, 1] that this pack should handle the assessment."""
        ...

    def explain(self, assessment: AssessmentInput) -> str:
        """One-line reason for the detect score (shown by the router)."""
        ...

    def normalize(self, assessment: AssessmentInput) -> AssessmentInput:
        """Normalize domain-specific fields (default: identity)."""
        ...

    def get_missing_information(self, assessment: AssessmentInput) -> list[MissingInformation]:
        """Material fields whose absence weakens the assessment."""
        ...

    def retrieve_evidence(self, assessment: AssessmentInput) -> list[EvidenceItem]:
        """Candidate evidence pool (v0.1: local JSON fixtures)."""
        ...

    def apply_rules(self, assessment: AssessmentInput,
                    evidence: list[EvidenceItem]) -> list[dict]:
        """Return the raw rule dicts that matched (carry required_actions +
        evidence_ids for the report)."""
        ...

    def generate_report(self, assessment: AssessmentInput,
                        evidence: list[EvidenceItem],
                        triggered_rules: list[dict],
                        missing_information: list[MissingInformation]) -> ClearanceReport:
        ...


# ─────────────────────────── config-driven base ───────────────────────────
class ConfigDrivenPack:
    """A full domain pack driven entirely by its JSON files."""

    def __init__(self, pack_dir: str | Path):
        self.dir = Path(pack_dir)
        cfg = self._load_json("config.json", {})
        self._cfg: dict = cfg if isinstance(cfg, dict) else {}
        self.id: str = self._cfg.get("id", self.dir.name)
        self.name: str = self._cfg.get("name", self.id)
        self.version: str = self._cfg.get("version", "0.1.0")
        self.status: str = self._cfg.get("status", "active")
        self.supported_object_types: list[str] = self._cfg.get("supported_object_types", [])
        self._sources: list[str] = [s.lower() for s in self._cfg.get("supported_sources", [])]
        self._metadata_signals: list[str] = self._cfg.get("metadata_signals", [])
        self.field_map: dict[str, str] = self._cfg.get("field_map", {})
        self._required_fields: list[dict] = self._cfg.get("required_fields", [])
        rules = self._load_json("rules.json", [])
        self.rules: list[dict] = rules if isinstance(rules, list) else []
        self.evidence = FixtureEvidenceRetriever(self.dir / "evidence_fixtures.json")

    def _load_json(self, name: str, default: Any) -> Any:
        p = self.dir / name
        if not p.exists():
            return default
        try:
            return json.loads(p.read_text())
        except Exception:
            return default

    # ── routing ──
    def detect(self, assessment: AssessmentInput) -> float:
        ot = (assessment.object.object_type or "").lower()
        src = (assessment.object.source or "").lower()
        meta = assessment.object.metadata or {}
        # baseline lets the custom fallback pack always score just above zero, so
        # it wins only when no real pack matches (never beats a genuine match).
        score = float(self._cfg.get("baseline_score", 0.0))
        if src and src in self._sources:
            score = max(score, 0.9)
        if ot and ot in [t.lower() for t in self.supported_object_types]:
            score = max(score, 0.7)
        if self._metadata_signals and any(k in meta for k in self._metadata_signals):
            score = max(score, 0.6)
        return score

    def explain(self, assessment: AssessmentInput) -> str:
        ot = (assessment.object.object_type or "")
        src = (assessment.object.source or "")
        meta = assessment.object.metadata or {}
        bits: list[str] = []
        if src and src.lower() in self._sources:
            bits.append(f"source '{src}' is handled by this pack")
        if ot and ot.lower() in [t.lower() for t in self.supported_object_types]:
            bits.append(f"object_type '{ot}' is supported")
        sig = [k for k in self._metadata_signals if k in meta]
        if sig:
            bits.append("metadata signals present: " + ", ".join(sig))
        return "; ".join(bits) if bits else "no strong routing signal"

    # ── normalize ──
    def normalize(self, assessment: AssessmentInput) -> AssessmentInput:
        return assessment

    # ── missing information ──
    def _when_holds(self, assessment: AssessmentInput, when: dict | None) -> bool:
        if not when:
            return True
        return rule_matches(assessment, {"conditions": when}, self.field_map)

    def get_missing_information(self, assessment: AssessmentInput) -> list[MissingInformation]:
        out: list[MissingInformation] = []
        seen_fields: set[str] = set()
        for spec in self._required_fields:
            if not isinstance(spec, dict):
                continue
            if not self._when_holds(assessment, spec.get("when")):
                continue
            alias = spec.get("alias") or spec.get("field")
            if not alias:
                continue
            field_name = spec.get("field", alias)
            if field_name in seen_fields:
                continue
            path = self.field_map.get(alias, spec.get("field", alias))
            val = resolve_path(assessment, path)
            missing_vals = [_norm(v) for v in spec.get("missing_values", [])]
            treat_missing = is_missing(val) or (
                isinstance(val, str) and _norm(val) in missing_vals
            )
            if treat_missing:
                seen_fields.add(field_name)
                out.append(MissingInformation(
                    field=field_name,
                    severity=spec.get("severity", "medium"),
                    message=spec.get("message", ""),
                ))
        return out

    # ── evidence ──
    def retrieve_evidence(self, assessment: AssessmentInput) -> list[EvidenceItem]:
        return self.evidence.all()

    # ── rules ──
    def apply_rules(self, assessment: AssessmentInput,
                    evidence: list[EvidenceItem]) -> list[dict]:
        return evaluate_rules(assessment, self.rules, self.field_map)

    # ── report ──
    def generate_report(self, assessment: AssessmentInput,
                        evidence: list[EvidenceItem],
                        triggered_rules: list[dict],
                        missing_information: list[MissingInformation]) -> ClearanceReport:
        matched = triggered_rules
        referenced: list[str] = []
        for r in matched:
            referenced.extend(r.get("evidence_ids") or [])
        ev = self.evidence.retrieve(assessment, referenced)
        return build_report(
            assessment=assessment,
            assessment_id=_new_assessment_id(),
            core_version=CORE_VERSION,
            domain_pack_id=self.id,
            domain_pack_version=self.version,
            matched_rules=matched,
            evidence_items=ev,
            missing_information=missing_information,
        )


class StubPack(ConfigDrivenPack):
    """A placeholder pack — routes correctly, returns a fixed verdict + summary.

    Still reports missing_information from config so the response is useful.
    """

    def apply_rules(self, assessment: AssessmentInput,
                    evidence: list[EvidenceItem]) -> list[dict]:
        return []

    def generate_report(self, assessment: AssessmentInput,
                        evidence: list[EvidenceItem],
                        triggered_rules: list[dict],
                        missing_information: list[MissingInformation]) -> ClearanceReport:
        return build_stub_report(
            assessment=assessment,
            assessment_id=_new_assessment_id(),
            core_version=CORE_VERSION,
            domain_pack_id=self.id,
            domain_pack_version=self.version,
            verdict=self._cfg.get("stub_verdict", "insufficient_information"),
            risk_level=self._cfg.get("stub_risk_level", "unknown"),
            summary=self._cfg.get("stub_summary",
                                  "The system could not confidently clear this assessment."),
            missing_information=missing_information,
        )


def _new_assessment_id() -> str:
    return "asm_" + uuid.uuid4().hex[:12]
