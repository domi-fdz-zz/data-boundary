"""
evidence.py — the evidence retrieval interface + the v0.1 fixture backend.

This is the seam the whole "do we search a legal database?" question hangs on.
In v0.1 the legal knowledge is NOT retrieved live — it is hand-authored by a
domain expert into rules.json (the logic) and evidence_fixtures.json (the
citations). The retriever here just loads those fixtures.

The point of keeping it behind an interface: a later version can swap in a real
retrieval backend (RAG over a legal corpus, or a legal-database API) WITHOUT
touching any rule, pack, or report code. Upper layers only see EvidenceItem.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from ..models.schemas import AssessmentInput, EvidenceItem


class EvidenceRetriever(Protocol):
    """Return the evidence items referenced by a set of evidence_ids.

    A future live-retrieval backend implements the same signature; callers never
    learn whether the item came from a fixture or a real search.
    """

    def retrieve(self, assessment: AssessmentInput,
                 evidence_ids: list[str]) -> list[EvidenceItem]:
        ...


class FixtureEvidenceRetriever:
    """v0.1 backend — loads evidence items from a local JSON fixture file.

    Every returned item keeps its `reliability` tag (e.g. fixture_placeholder),
    so a placeholder is never silently presented as authoritative.
    """

    def __init__(self, fixtures_path: str | Path):
        self._path = Path(fixtures_path)
        self._by_id: dict[str, EvidenceItem] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
        except Exception:
            return
        for item in raw if isinstance(raw, list) else []:
            try:
                ev = EvidenceItem(**item)
            except Exception:
                continue
            self._by_id[ev.evidence_id] = ev

    def all(self) -> list[EvidenceItem]:
        return list(self._by_id.values())

    def retrieve(self, assessment: AssessmentInput,
                 evidence_ids: list[str]) -> list[EvidenceItem]:
        out: list[EvidenceItem] = []
        seen: set[str] = set()
        for eid in evidence_ids:
            if eid in seen:
                continue
            seen.add(eid)
            item = self._by_id.get(eid)
            if item is not None:
                out.append(item)
        return out
