"""
normalizer.py — the ONLY place an external LLM is called.

Its job is narrow and non-authoritative: turn a free-text scenario into the
structured six-dimension AssessmentInput so a human can review and edit it in the
form. It does NOT judge legality — that is the rule engine's job. If no LLM key
is configured, the whole app still works; the user just fills the form directly.

Borrows statLens's httpx chat call + robust JSON extraction, adapted for the
compliance-intake prompt.
"""
from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..models.schemas import AssessmentInput


# ─────────────────────────── LLM plumbing (borrowed) ───────────────────────────
def _extract_json_object(text: str) -> dict | None:
    """Find the largest balanced JSON object in a blob of text."""
    try:
        return json.loads(text.strip())
    except Exception:
        pass
    starts = [i for i, c in enumerate(text) if c == "{"]
    for s in starts:
        depth = 0
        for i in range(s, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    cand = text[s:i + 1]
                    try:
                        return json.loads(cand)
                    except Exception:
                        break
    matches = re.findall(r"\{[^{}]*\}", text, re.DOTALL)
    for m in sorted(matches, key=len, reverse=True):
        try:
            return json.loads(m)
        except Exception:
            continue
    return None


def _post_chat(endpoint: str, messages: list[dict], model: str,
               api_key: str, timeout: float, max_tokens: int) -> str:
    url = endpoint.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {"model": model, "messages": messages,
            "temperature": 0.0, "max_tokens": max_tokens}
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, json=body, headers=headers)
        r.raise_for_status()
        data = r.json()
    return data["choices"][0]["message"]["content"]


# ─────────────────────────── the extract prompt ───────────────────────────
SYSTEM_PROMPT = """\
You are a compliance-intake assistant. You read a free-text description of a
business scenario and structure it into six dimensions. You do NOT decide whether
anything is legal or allowed — a separate rule engine does that. Your only job is
faithful extraction.

Reply with a SINGLE JSON object and NOTHING ELSE, in exactly this shape:

{
  "object":     {"object_type": "", "name": "", "source": "",
                 "identifiers": {},
                 "metadata": {"organism": "", "data_type": "", "data_level": "",
                              "sample_origin": ""}},
  "actor":      {"actor_type": "", "country": "", "organization_type": "",
                 "foreign_controlled": null, "role": ""},
  "use_case":   {"category": "", "description": "", "commercial": null,
                 "clinical": null, "ai_training": null, "publication": null,
                 "research_only": null},
  "jurisdiction": {"countries": [], "regions": [], "target_market": [],
                   "analysis_level": ""},
  "data_flow":  {"storage_location": "", "processing_location": "",
                 "cross_border": null, "external_sharing": null,
                 "cloud_processing": null, "third_parties": [],
                 "output_distribution": []},
  "time":       {"assessment_date": "", "effective_on": ""}
}

Rules:
  - Extract ONLY what is stated or clearly implied. Use "" for unknown strings,
    null for unknown booleans, [] for unknown lists. NEVER guess.
  - Booleans are true / false / null (not strings).
  - object_type examples: dataset, drug, genetic_test, agricultural_sample.
  - object.source is where the object comes from (e.g. GEO), not a location.
  - For omics/dataset scenarios, fill object.metadata.organism (e.g. "Homo
    sapiens"), data_type (e.g. "RNA-seq"), data_level, sample_origin.
  - use_case.category is a short slug (e.g. differential_expression_analysis).
  - cross_border is true if data moves between countries.
  - Do NOT add keys, comments, or a workflow/verdict.
"""


def build_messages(text: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"=== SCENARIO ===\n{text.strip()}\n\n"
                                     f"Now output the six-dimension JSON object."},
    ]


# ─────────────────────────── coercion → AssessmentInput ───────────────────────────
def _today() -> str:
    return datetime.date.today().isoformat()


def _sub(obj: Any, key: str) -> dict:
    v = obj.get(key) if isinstance(obj, dict) else None
    return v if isinstance(v, dict) else {}


def _s(v: Any) -> str | None:
    """A value for a string-typed field, or None. Numbers are stringified;
    bools / lists / dicts are rejected so they can never reach a str field
    (pydantic v2 does NOT coerce these, so passing them through would raise)."""
    if isinstance(v, str):
        return v
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return str(v)
    return None


def _req_s(v: Any, default: str) -> str:
    return _s(v) or default


def _b(v: Any) -> bool | None:
    """Tri-state boolean: True / False / None (unknown). Tolerant of a few common
    encodings; anything uninterpretable becomes None."""
    if isinstance(v, bool):
        return v
    if v in (1, "1", "true", "True", "yes"):
        return True
    if v in (0, "0", "false", "False", "no"):
        return False
    return None


def _slist(v: Any) -> list:
    if not isinstance(v, list):
        return []
    return [s for s in (_s(x) for x in v) if s is not None]


def _sdict(v: Any) -> dict:
    """A dict[str, str] — values stringified, unusable ones dropped."""
    if not isinstance(v, dict):
        return {}
    out: dict[str, str] = {}
    for k, val in v.items():
        s = _s(val)
        if s is not None:
            out[str(k)] = s
    return out


def coerce_to_input(obj: dict, *, query: str | None = None,
                    default_date: str | None = None) -> AssessmentInput:
    """Build a valid AssessmentInput from a loose/partial dict. Injects safe
    defaults for the three required fields and sanitizes EVERY field to its schema
    type, so this must NEVER raise — a malformed value degrades to empty/None and
    is surfaced by the missing-information machinery rather than 500-ing."""
    obj = obj if isinstance(obj, dict) else {}
    # Some models wrap the payload under an "input"/"assessment" key.
    for wrap in ("input", "assessment", "assessment_input"):
        if isinstance(obj.get(wrap), dict):
            obj = obj[wrap]
            break

    o = _sub(obj, "object")
    ac = _sub(obj, "actor")
    uc = _sub(obj, "use_case")
    ju = _sub(obj, "jurisdiction")
    dfw = _sub(obj, "data_flow")
    tm = _sub(obj, "time")

    date = _s(default_date) or _s(tm.get("assessment_date")) or _today()

    payload = {
        "object": {
            "object_type": _req_s(o.get("object_type"), "unknown"),
            "name": _s(o.get("name")),
            "source": _s(o.get("source")),
            "identifiers": _sdict(o.get("identifiers")),
            "metadata": o.get("metadata") if isinstance(o.get("metadata"), dict) else {},
        },
        "actor": {
            "actor_type": _s(ac.get("actor_type")),
            "country": _s(ac.get("country")),
            "organization_type": _s(ac.get("organization_type")),
            "foreign_controlled": _b(ac.get("foreign_controlled")),
            "role": _s(ac.get("role")),
            "metadata": ac.get("metadata") if isinstance(ac.get("metadata"), dict) else {},
        },
        "use_case": {
            "category": _req_s(uc.get("category"), "unspecified"),
            "description": _s(uc.get("description")),
            "commercial": _b(uc.get("commercial")),
            "clinical": _b(uc.get("clinical")),
            "ai_training": _b(uc.get("ai_training")),
            "publication": _b(uc.get("publication")),
            "research_only": _b(uc.get("research_only")),
            "metadata": uc.get("metadata") if isinstance(uc.get("metadata"), dict) else {},
        },
        "jurisdiction": {
            "countries": _slist(ju.get("countries")),
            "regions": _slist(ju.get("regions")),
            "target_market": _slist(ju.get("target_market")),
            "analysis_level": _s(ju.get("analysis_level")),
        },
        "data_flow": {
            "storage_location": _s(dfw.get("storage_location")),
            "processing_location": _s(dfw.get("processing_location")),
            "cross_border": _b(dfw.get("cross_border")),
            "external_sharing": _b(dfw.get("external_sharing")),
            "cloud_processing": _b(dfw.get("cloud_processing")),
            "third_parties": _slist(dfw.get("third_parties")),
            "output_distribution": _slist(dfw.get("output_distribution")),
            "metadata": dfw.get("metadata") if isinstance(dfw.get("metadata"), dict) else {},
        },
        "time": {
            "assessment_date": date,
            "effective_on": _s(tm.get("effective_on")) or date,
        },
        "query": _s(query) or _s(obj.get("query")),
    }
    return AssessmentInput(**payload)


def blank_input(*, query: str | None = None,
                default_date: str | None = None) -> AssessmentInput:
    """Minimal valid input when there is nothing to extract (no LLM / empty)."""
    return coerce_to_input({}, query=query, default_date=default_date)


# ─────────────────────────── public entry ───────────────────────────
@dataclass
class ExtractResult:
    input: AssessmentInput
    raw: str = ""
    warnings: list[str] = field(default_factory=list)
    llm_used: bool = False


def extract_from_text(text: str, endpoint: str, model: str, api_key: str,
                      *, timeout: float = 120.0,
                      default_date: str | None = None) -> ExtractResult:
    """Call the LLM to structure `text`. On any failure, degrade to a blank input
    carrying the text as `query` (plus a warning) — never raise to the caller."""
    warnings: list[str] = []
    try:
        raw = _post_chat(endpoint, build_messages(text), model, api_key,
                         timeout=timeout, max_tokens=2048)
    except Exception as e:
        return ExtractResult(
            input=blank_input(query=text, default_date=default_date),
            raw="", warnings=[f"LLM call failed: {type(e).__name__}: {e}"],
            llm_used=False,
        )
    obj = _extract_json_object(raw)
    if obj is None:
        warnings.append("LLM output was not valid JSON; returning an empty form.")
        return ExtractResult(
            input=blank_input(query=text, default_date=default_date),
            raw=raw, warnings=warnings, llm_used=True,
        )
    try:
        inp = coerce_to_input(obj, query=text, default_date=default_date)
    except Exception as e:
        warnings.append(f"Could not coerce LLM JSON into the schema: {e}")
        inp = blank_input(query=text, default_date=default_date)
    return ExtractResult(input=inp, raw=raw, warnings=warnings, llm_used=True)
