"""
pipeline.py — the two-phase run with a human-in-the-loop checkpoint.

  ① extract (LLM)        free-text scenario → structured AssessmentInput (facts)
                         + a formal natural-language restatement (understanding).
     ── the client shows an editable schema card here; the user confirms/corrects ──
  ② assess (deterministic + LLM), on the CONFIRMED facts:
     · gate           facts → applicability + off-ramps + per-purpose verdict
     · retrieve (CoT) for each law that APPLIES → reasoning + obligations, each with
                      a citation + a verbatim quote + an official primary-source URL
     · case-scan      a DEEP, case-specific scan free to surface ANY primary-source
                      authority beyond the modeled set (e.g. CA CMIA, FTC Act) —
                      the answer to "our fixed list won't cover every case"
     · verify         fetch the primary source (domain-gated to official sources ONLY)
                      and confirm each quote appears verbatim; unverifiable quotes are
                      dropped, not shown. No "verified" badge — a primary citation +
                      a link to the original IS the proof.
     · narrate (LLM)  writes a case-specific explanation per purpose, constrained NOT
                      to change the rule-decided verdict (fixes identical wording).

Chat: two guarded assistants — scope_chat (left, pre-check: helps articulate, never
gives a verdict) and chat (right, post-report: explains the standing verdict, never
overrides it, routes fact-changes back to a re-check).

The LLM never sets the verdict — the gate does — and every quote it emits must survive
domain-gated quote-verification against an official primary source.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .schema import AssessmentInput
from .gate import assess as gate_assess
from .source_discovery import (
    DISCOVERY_SYSTEM_PROMPT,
    EXTRA_OFFICIAL_HOSTS,
    VALIDATION_SYSTEM_PROMPT,
    discovery_user_prompt,
    validation_user_prompt,
)
from ..core.normalizer import _post_chat, _extract_json_object

_REG = json.loads((Path(__file__).parent / "source_registry.json").read_text())
_LAW_URLS: dict[str, list[str]] = {}
for _s in _REG.get("sources", []):
    if _s.get("url"):
        _LAW_URLS.setdefault(_s["law_id"], []).append(_s["url"])

# Official PRIMARY-source domains only. AI is free to reach laws beyond our modeled
# set, but only if it can point to an official government / legislature source here.
_EXTRA_OFFICIAL = {
    "leginfo.legislature.ca.gov", "www.leginfo.legislature.ca.gov",
} | set(EXTRA_OFFICIAL_HOSTS)


def _host_ok(url: str) -> bool:
    """True only for official primary-source hosts (.gov or an explicit allow-set)."""
    try:
        h = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    if not h:
        return False
    return h.endswith(".gov") or h in _EXTRA_OFFICIAL


def _sub(o, k) -> dict:
    v = o.get(k) if isinstance(o, dict) else None
    return v if isinstance(v, dict) else {}


# LLMs sometimes emit "unknown" / "true" strings into typed fields; coerce so one
# stray value can't fail validation and blank the whole extraction.
_BOOL_FIELDS = {
    "object": {"contains_personal_data", "publicly_available", "includes_children_under_13",
               "non_us_subjects", "has_dua", "terms_restrict_use"},
    "actor": {"foreign_controlled", "for_profit", "meets_state_threshold", "is_funded"},
    "use_case": {"commercial", "clinical", "ai_training", "publication", "research_only",
                 "redistribute", "secondary_use"},
    "data_flow": {"cross_border", "external_sharing", "cloud_processing"},
    "basis": {"consent_covers_use"},
}
_LIST_FIELDS = {
    "object": {"data_categories"},
    "jurisdiction": {"countries", "regions", "target_market"},
    "data_flow": {"third_parties", "output_distribution"},
}


def _coerce_bool(v):
    if v is None or isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("true", "yes", "1"):
        return True
    if s in ("false", "no", "0"):
        return False
    return None


def _coerce_facts(f) -> dict:
    f = f if isinstance(f, dict) else {}
    for sub, names in _BOOL_FIELDS.items():
        d = f.get(sub)
        if isinstance(d, dict):
            for k in names:
                if k in d:
                    d[k] = _coerce_bool(d[k])
    for sub, names in _LIST_FIELDS.items():
        d = f.get(sub)
        if isinstance(d, dict):
            for k in names:
                if k in d and not isinstance(d[k], list):
                    d[k] = [] if d[k] in (None, "") else [str(d[k])]
    obj = f.get("object")
    if isinstance(obj, dict) and isinstance(obj.get("identifiers"), dict):
        obj["identifiers"] = {str(k): ("" if v is None else str(v))
                              for k, v in obj["identifiers"].items()}
    return f


def _build_input(f: dict, text: str) -> AssessmentInput:
    """Construct AssessmentInput resiliently: build each sub-model, and if a sub-dict has a
    field pydantic rejects, keep the fields that DO validate rather than losing the whole
    sub-model (or the whole extraction) to one bad value."""
    from .schema import (ClearanceObject, Actor, UseCase, Jurisdiction, DataFlow,
                         Basis, AssessmentTime)

    def mk(cls, d):
        d = d if isinstance(d, dict) else {}
        try:
            return cls(**d)
        except Exception:
            good = {}
            for k, v in d.items():
                try:
                    cls(**{k: v})
                    good[k] = v
                except Exception:
                    pass
            try:
                return cls(**good)
            except Exception:
                return cls()

    return AssessmentInput(
        object=mk(ClearanceObject, _sub(f, "object")),
        actor=mk(Actor, _sub(f, "actor")),
        use_case=mk(UseCase, _sub(f, "use_case")),
        jurisdiction=mk(Jurisdiction, _sub(f, "jurisdiction")),
        data_flow=mk(DataFlow, _sub(f, "data_flow")),
        basis=mk(Basis, _sub(f, "basis")),
        time=mk(AssessmentTime, _sub(f, "time")),
        query=text,
    )


# ─────────────────────────── ① intake ───────────────────────────
_INTAKE_SYS = """You extract structured facts about a dataset-use scenario for a US
privacy check, and restate your understanding. Output ONE JSON object and nothing else.
Use null for unknown scalars, [] for unknown lists — NEVER guess an unstated fact.

{
 "facts":{
  "object":{"object_type":"","name":"","source":"","identifiers":{},
    "contains_personal_data":null,
    "identifiability":"identified|pseudonymized|deidentified_hipaa_safeharbor|deidentified_expert|deidentified_other|anonymized|aggregate|unknown",
    "data_categories":[],"publicly_available":null,"includes_children_under_13":null,"non_us_subjects":null,
    "source_type":"public_open|public_registered|controlled_access|collaborator|scraped|internal|unknown",
    "license":"permissive|research_only|noncommercial|none|unknown","has_dua":null,"terms_restrict_use":null},
  "actor":{"actor_type":"company|academic_institution|researcher_individual|nonprofit","country":"","organization_type":"","role":"",
    "for_profit":null,"sector":"healthcare_covered_entity|business_associate|financial_institution|educational_institution|none|unknown",
    "meets_state_threshold":null,"is_funded":null,"foreign_controlled":null},
  "use_case":{"category":"","description":"","commercial":null,"clinical":null,"ai_training":null,"publication":null,"research_only":null,"redistribute":null,"secondary_use":null},
  "jurisdiction":{"countries":[],"regions":[],"target_market":[],"analysis_level":null},
  "data_flow":{"storage_location":null,"processing_location":null,"cross_border":null,"external_sharing":null,"cloud_processing":null,"third_parties":[],"output_distribution":[]},
  "basis":{"consent_covers_use":null,"irb_status":"approved|exempt|pending|none|unknown"},
  "time":{"assessment_date":null,"effective_on":null}
 },
 "understanding":"<In formal written English, restate your understanding of the proposed data use in 2-4 sentences: what the data is, its source, whether it includes identifiable or sensitive information, where the subjects reside, who the user is, the intended use, and key uncertainties. Do not state any legal conclusion.>"
}

data_categories values: health, financial, education, biometric, genetic, children, contact, precise_geo, video_viewing, driver, behavioral.
For jurisdiction.regions, use U.S. state names where the data subjects reside. Choose identifiability/source_type/license/sector/irb_status from the provided enums; if unsure, use unknown or null."""


def extract_facts(text: str, ep: str, model: str, key: str) -> tuple[AssessmentInput, str]:
    raw = _post_chat(ep, [{"role": "system", "content": _INTAKE_SYS},
                          {"role": "user", "content": f"SCENARIO:\n{text}\n\nOutput the JSON."}],
                     model, key, timeout=90, max_tokens=1600)
    obj = _extract_json_object(raw) or {}
    f = _coerce_facts(obj.get("facts") if isinstance(obj.get("facts"), dict) else obj)
    understanding = str(obj.get("understanding") or "").strip()
    return _build_input(f, text), understanding


# ─────────────────────────── ③ retrieve (CoT) ───────────────────────────
_RETRIEVE_SYS = """You are a US privacy-law analyst. For ONE law and ONE scenario, think
step by step about whether and how the law applies, THEN list concrete obligations.
Output ONE JSON object:
{ "reasoning":"<your step-by-step chain of thought>",
  "applies":"yes|no|unclear",
  "obligations":[{"obligation":"<one concise English sentence describing the obligation>","citation":"...","source_url":"<official primary-source URL for the cited provision>","quote":"<verbatim excerpt in the source's ORIGINAL language, <=18 words>"}] }
Write "obligation" in English; keep "quote" as the verbatim original-language text.
Each quote MUST be exact statutory/regulatory language you are confident appears verbatim
in the cited law; if unsure, use "" (empty). source_url MUST be an OFFICIAL PRIMARY source
(government / official legislature domain) — never a blog, law firm, wiki, or summary.
Do NOT fabricate citations, URLs, or quotes."""


def retrieve_for_law(law_name: str, citation_hint: str, facts_summary: str,
                     ep: str, model: str, key: str) -> dict:
    user = (f"LAW: {law_name}\nKNOWN CITATION AREA: {citation_hint}\n\n"
            f"SCENARIO FACTS:\n{facts_summary}\n\nAnalyze and output the JSON.")
    raw = _post_chat(ep, [{"role": "system", "content": _RETRIEVE_SYS},
                          {"role": "user", "content": user}],
                     model, key, timeout=120, max_tokens=1600)
    return _extract_json_object(raw) or {"reasoning": raw[:400], "applies": "unclear",
                                         "obligations": []}


# ─────────────────────────── deep case-scan (extended research) ───────────────────────────
_SCAN_SYS = """You are a meticulous US privacy / data-use legal researcher performing a DEEP,
case-specific scan. Given the specific facts, identify EVERY law, regulation, or binding
authority that could plausibly apply to THESE facts — INCLUDING authorities beyond any fixed
checklist (e.g. state medical-confidentiality laws such as California CMIA; FTC Act §5 and the
FTC Health Breach Notification Rule; state genetic-privacy laws; sectoral rules; contractual /
DUA regimes). Think broadly, case by case; do not limit yourself to well-known federal laws.

For EACH authority output an item (keep it COMPACT so the JSON is not truncated):
{ "title":"<law/authority name (keep its proper name)>",
  "why":"<one concise English sentence explaining why it may apply to this case>",
  "citation":"<specific section if known, else ''>",
  "source_url":"<official PRIMARY-source URL: government / official legislature ONLY>",
  "quote":"<verbatim excerpt in original language, <=18 words, or '' if unsure>" }

Rules: output AT MOST 8 items, most relevant first. PRIMARY sources ONLY (government / official
legislature domains). NEVER cite blogs, law firms, Wikipedia, or secondary summaries. If you
cannot point to a real primary source, OMIT the item. Do NOT fabricate URLs or quotes.
Output ONE JSON object: {"leads":[ ... ]}."""


def _salvage_leads(raw: str) -> list[dict]:
    """Recover lead objects even from truncated JSON: collect every balanced {...}
    (at any depth) that parses and looks like a lead. Tolerates a cut-off outer wrapper."""
    stack, frags = [], []
    instr = esc = False
    for i, ch in enumerate(raw):
        if instr:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                instr = False
            continue
        if ch == '"':
            instr = True
        elif ch == '{':
            stack.append(i)
        elif ch == '}' and stack:
            frags.append(raw[stack.pop():i + 1])
    out = []
    for fr in frags:
        try:
            o = json.loads(fr)
        except Exception:
            continue
        if isinstance(o, dict) and o.get("title") and "source_url" in o:
            out.append(o)
    return out


def case_scan(facts_summary: str, modeled_law_names: list[str],
              ep: str, model: str, key: str) -> list[dict]:
    user = (f"SCENARIO FACTS:\n{facts_summary}\n\n"
            f"Already covered by our built-in engine (you may still add these if a specific "
            f"provision matters, but focus on what's NOT here):\n- " + "\n- ".join(modeled_law_names)
            + "\n\nDo the deep scan and output the JSON.")
    raw = _post_chat(ep, [{"role": "system", "content": _SCAN_SYS},
                          {"role": "user", "content": user}],
                     model, key, timeout=180, max_tokens=3800)
    obj = _extract_json_object(raw) or {}
    leads = obj.get("leads") if isinstance(obj, dict) else None
    if not (isinstance(leads, list) and leads):
        leads = _salvage_leads(raw)          # recover from truncation / wrapper loss
    return leads if isinstance(leads, list) else []


# ─────────────────────────── source discovery + validation agents ───────────────────────────
def _source_key(src: dict) -> str:
    url = str(src.get("source_url") or "").strip().lower()
    if url:
        return url.split("#", 1)[0]
    return (str(src.get("title") or "").strip().lower() + "|" +
            str(src.get("citation") or "").strip().lower())


def _dedupe_sources(sources: list[dict], limit: int = 8) -> list[dict]:
    seen, out = set(), []
    for src in sources or []:
        if not isinstance(src, dict):
            continue
        key = _source_key(src)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(src)
        if len(out) >= limit:
            break
    return out


def discover_legal_sources(facts_summary: str, modeled_law_names: list[str],
                           ep: str, model: str, key: str) -> list[dict]:
    raw = _post_chat(
        ep,
        [{"role": "system", "content": DISCOVERY_SYSTEM_PROMPT},
         {"role": "user", "content": discovery_user_prompt(facts_summary, modeled_law_names)}],
        model, key, timeout=180, max_tokens=3200,
    )
    obj = _extract_json_object(raw) or {}
    sources = obj.get("sources") if isinstance(obj, dict) else None
    return _dedupe_sources(sources if isinstance(sources, list) else [], limit=8)


def validate_legal_source(facts_summary: str, source: dict, official: bool,
                          quote_status: str, ep: str, model: str, key: str) -> dict:
    raw = _post_chat(
        ep,
        [{"role": "system", "content": VALIDATION_SYSTEM_PROMPT},
         {"role": "user", "content": validation_user_prompt(facts_summary, source, official, quote_status)}],
        model, key, timeout=180, max_tokens=1800,
    )
    obj = _extract_json_object(raw) or {}
    return obj if isinstance(obj, dict) else {
        "evaluation_status": "do_not_use",
        "status_reason": "The validation response could not be parsed into structured JSON.",
        "confidence": "low",
    }


def research_and_validate_sources(facts_summary: str, modeled_law_names: list[str],
                                  ep: str, model: str, key: str, cache: dict,
                                  *, verify: bool = True) -> dict:
    warnings: list[str] = []
    try:
        candidates = discover_legal_sources(facts_summary, modeled_law_names, ep, model, key)
    except Exception as e:
        return {
            "version": "legal_source_research.v1",
            "verdict_effect": "none",
            "leads": [],
            "warnings": [f"source discovery failed ({type(e).__name__})"],
        }

    leads = []
    for idx, src in enumerate(candidates[:6], 1):
        url = str(src.get("source_url") or "").strip()
        official = _host_ok(url)
        if verify and official:
            quote_status, matched_url = verify_quote(src.get("quote", ""), [url], cache)
        elif official:
            quote_status, matched_url = "skipped", ""
        else:
            quote_status, matched_url = "not_official", ""

        try:
            rule = validate_legal_source(
                facts_summary, src, official, quote_status, ep, model, key
            )
        except Exception as e:
            rule = {
                "evaluation_status": "do_not_use",
                "status_reason": f"Validation failed ({type(e).__name__}).",
                "confidence": "low",
            }
            warnings.append(f"validation failed for lead {idx} ({type(e).__name__})")

        verified_quote = src.get("quote", "") if quote_status == "verified" else ""
        leads.append({
            "id": f"lead_{idx}",
            "title": src.get("title", ""),
            "authority_type": src.get("authority_type", ""),
            "jurisdiction": src.get("jurisdiction", ""),
            "topic": src.get("topic", ""),
            "citation": src.get("citation", ""),
            "source_url": url,
            "why_may_matter": src.get("why_it_may_matter", "") or src.get("why", ""),
            "triggering_facts": src.get("triggering_facts", []),
            "validation": {
                "status": "verified" if quote_status == "verified" else (
                    "official_source_no_quote" if official else "not_official"
                ),
                "official_source": official,
                "quote_verified": quote_status == "verified",
                "quote_status": quote_status,
                "matched_url": matched_url,
                "quote": verified_quote,
            },
            "rule": rule,
        })

    return {
        "version": "legal_source_research.v1",
        "verdict_effect": "none",
        "leads": leads,
        "warnings": warnings,
    }


def _legacy_extended_from_source_research(source_research: dict) -> list[dict]:
    out = []
    for lead in (source_research or {}).get("leads", []):
        if not lead.get("validation", {}).get("official_source"):
            continue
        rule = lead.get("rule") or {}
        if rule.get("evaluation_status") == "do_not_use":
            continue
        out.append({
            "title": lead.get("title", ""),
            "why": lead.get("why_may_matter", ""),
            "citation": lead.get("citation", ""),
            "source_url": lead.get("source_url", ""),
            "quote": lead.get("validation", {}).get("quote", ""),
            "verified_quote": lead.get("validation", {}).get("quote_verified", False),
            "evaluation_status": rule.get("evaluation_status", ""),
            "missing_facts": rule.get("missing_facts", []),
        })
    return out


# ─────────────────────────── per-purpose narration ───────────────────────────
_NARRATE_SYS = """The deterministic assessment has already produced fixed conclusions for
the research and commercial purposes. Your task is only to explain each conclusion in
case-specific, concrete English. Hard constraints:
- Do not change, soften, override, or contradict the provided conclusion; explain why it is the conclusion.
- The research and commercial explanations must be different and tailored to that purpose's specific drivers: which law, contract step, approval path, or missing fact matters.
- Each explanation should be 2-4 sentences and should mention how the conclusion would change if a key fact changed.
- Do not use internal terms such as "gate", "rule engine", "CoT", or "verdict"; write for an ordinary product user.
- Do not use Markdown syntax, bold markers, code fences, headings, or backticks.
Output one JSON object: {"research":"...","commercial":"..."}"""


def _narrate(matrix, law_names: dict, facts_summary: str, missing: list[str],
             ep: str, model: str, key: str) -> dict:
    lines = []
    for m in matrix:
        drv = ", ".join([law_names.get(x, x) for x in m.because_laws] + list(m.because_contract)) or "no specific driver"
        lines.append(f"- purpose={m.purpose}; conclusion={m.verdict}; drivers={drv}")
    user = ("Fixed conclusions for both purposes:\n" + "\n".join(lines)
            + f"\n\nScenario facts: {facts_summary}\nStill missing: {', '.join(missing) or 'none'}\n\n"
            "Write one paragraph each for research and commercial, and output JSON.")
    raw = _post_chat(ep, [{"role": "system", "content": _NARRATE_SYS},
                          {"role": "user", "content": user}],
                     model, key, timeout=90, max_tokens=900)
    obj = _extract_json_object(raw) or {}
    return {"research": _plain_dialog_text(str(obj.get("research") or "")),
            "commercial": _plain_dialog_text(str(obj.get("commercial") or ""))}


# ─────────────────────────── verify (domain-gated) ───────────────────────────
_WS = re.compile(r"\s+")
_TAG = re.compile(r"<[^>]+>")


def _norm(s: str) -> str:
    s = _TAG.sub(" ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&sect;", "§")
    s = _WS.sub(" ", s).lower()
    return re.sub(r"[^a-z0-9 §]", "", s)


def _fetch(url: str) -> str:
    try:
        with httpx.Client(timeout=25, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 data-boundary/0.1"}) as c:
            r = c.get(url)
            r.raise_for_status()
            if not _host_ok(str(r.url)):     # a redirect may have left the allowed primary-source hosts
                return ""
            return r.text[:2_000_000]
    except Exception:
        return ""


def verify_quote(quote: str, urls: list[str], cache: dict) -> tuple[str, str]:
    """Return (status, matched_url). Only OFFICIAL primary-source hosts are fetched.
    status ∈ verified / not_found / unreachable / no_quote / no_source."""
    q = _norm(quote or "").strip()
    if len(q) < 8:
        return "no_quote", ""
    allowed = [u for u in (urls or []) if u and _host_ok(u)]
    if not allowed:
        return "no_source", ""
    needle = " ".join(q.split()[:12])       # first ~12 significant words tolerate HTML drift
    reachable = False
    for u in allowed:
        if u not in cache:
            cache[u] = _norm(_fetch(u))
        page = cache[u]
        if page:
            reachable = True
            if needle and needle in page:
                return "verified", u
    return ("not_found" if reachable else "unreachable"), ""


# ─────────────────────────── chat (two guarded assistants) ───────────────────────────
_SCOPE_SYS = """You are an in-product guidance assistant for U.S. data-use and privacy
compliance. The user has not started the preliminary assessment yet and is describing
the data they have and how they plan to use it. Your role:
- Stay within the topic of whether a data use can be assessed under U.S. privacy and data-use rules. If a question is unrelated, politely state that this panel only handles data-use fact review.
- Ask follow-up questions to clarify key facts: what the data is, how it was obtained, whether it includes identifiable or sensitive information, which states the subjects reside in, what kind of organization the user is, whether HIPAA covered-entity status may apply, license / terms, consent / IRB status, and whether the use is research or commercial.
- Use concise English. Do not ask too many questions at once.
- Write like a natural product conversation: short paragraphs, and numbered questions only when helpful. Do not use Markdown syntax, bold markers, code fences, backticks, or heading markers.
Hard boundaries:
- Never conclude that the use is permitted, not permitted, lawful, or unlawful. The preliminary assessment conclusion must come from the assessment flow.
- If the user asks for a conclusion, direct them to complete the facts and click "Start preliminary assessment".
- Do not invent statutes or citations."""

_CHAT_SYS = """You are a follow-up assistant for U.S. data-use and privacy compliance.
The user has completed one preliminary assessment. The conclusions in the "Assessment
Context" below come from the deterministic assessment and must control. Rules:
- Answer in concise English and point to the specific law, obligation, approval path, or missing fact when relevant. Do not restate the entire assessment.
- Write like a natural product conversation: short paragraphs, and numbered points only when helpful. Do not use Markdown syntax, bold markers, code fences, backticks, or heading markers.
- Treat the Assessment Context as binding. You may explain or break it down, but must not override, soften, or contradict it.
- If the user's question changes a key fact, such as de-identification, consent, DUA status, or license terms, do not re-assess from scratch. Explain that the input would change, that the conclusion depends on that fact, and that the user should update the left-side fact card and rerun the assessment. Briefly describe the likely direction of change and why.
- If the matter is uncertain or would support a formal decision, state that the user should review the primary source or consult qualified counsel. Do not give a definitive legal conclusion or invent citations.
- If the question is outside data-use or privacy compliance, politely state the scope."""


def _history_msgs(history: list) -> list:
    out = []
    for h in (history or [])[-6:]:
        role = h.get("role")
        if role in ("user", "assistant") and h.get("content"):
            out.append({"role": role, "content": str(h["content"])[:2000]})
    return out


def _plain_dialog_text(text: str) -> str:
    """Best-effort cleanup for models that ignore the no-Markdown instruction."""
    s = str(text or "")
    s = re.sub(r"```(?:[a-zA-Z0-9_-]+)?\s*([\s\S]*?)```", r"\1", s)
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"__([^_]+)__", r"\1", s)
    s = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", s)
    s = re.sub(r"(?m)^\s*[-*]\s+", "", s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    return s.strip()


def scope_chat(history: list, question: str, ep: str, model: str, key: str) -> str:
    msgs = [{"role": "system", "content": _SCOPE_SYS}] + _history_msgs(history)
    msgs.append({"role": "user", "content": question})
    return _plain_dialog_text(_post_chat(ep, msgs, model, key, timeout=90, max_tokens=700))


def chat(context: str, history: list, question: str,
         ep: str, model: str, key: str) -> str:
    msgs = [{"role": "system", "content": _CHAT_SYS + "\n=== Assessment Context ===\n" + (context or "")}]
    msgs += _history_msgs(history)
    msgs.append({"role": "user", "content": question})
    return _plain_dialog_text(_post_chat(ep, msgs, model, key, timeout=90, max_tokens=900))


# ─────────────────────────── orchestrate ───────────────────────────
def _facts_summary(inp: AssessmentInput) -> str:
    o, a, uc, j, b = inp.object, inp.actor, inp.use_case, inp.jurisdiction, inp.basis
    return (f"source={o.source_type}, license={o.license}, personal_data={o.contains_personal_data}, "
            f"identifiability={o.identifiability}, categories={o.data_categories}, "
            f"regions={j.regions}, children_u13={o.includes_children_under_13}, "
            f"actor={a.actor_type}, for_profit={a.for_profit}, sector={a.sector}, "
            f"commercial={uc.commercial}, research_only={uc.research_only}, publication={uc.publication}, "
            f"ai_training={uc.ai_training}, secondary_use={uc.secondary_use}, "
            f"consent_covers_use={b.consent_covers_use}, irb={b.irb_status}")


def assess_run(inp: AssessmentInput, ep: str, model: str, key: str, *, verify: bool = True) -> dict:
    report = gate_assess(inp)                          # deterministic verdict
    fsum = _facts_summary(inp)
    law_names = {l.law_id: l.name for l in report.applicable_laws}
    cache: dict = {}

    # per-purpose case-specific narration (does NOT change the verdict)
    try:
        narr = _narrate(report.purpose_matrix, law_names, fsum, report.missing_information, ep, model, key)
        for m in report.purpose_matrix:
            m.narration = narr.get(m.purpose) or None
    except Exception:
        pass

    # per-applicable-law retrieval + quote-verification against primary sources
    retrievals = []
    for law in report.applicable_laws:
        if law.status != "applies":
            continue
        try:
            got = retrieve_for_law(law.name, law.law_id, fsum, ep, model, key)
        except Exception:
            continue                          # one law's LLM/network failure must not abort the run
        obs = got.get("obligations") or []
        kept = []
        for ob in obs:
            urls = list(_LAW_URLS.get(law.law_id, []))
            if ob.get("source_url"):
                urls.append(ob["source_url"])
            st, url = verify_quote(ob.get("quote", ""), urls, cache) if verify else ("skipped", "")
            ob["verify_status"] = st
            ob["verify_url"] = url or ob.get("source_url", "")
            if st != "verified":
                ob["quote"] = ""              # never carry an unverified quote as if authoritative
            # keep obligations whose quote is verbatim-verified, or that at least point to an
            # official primary source (a link the user can check); drop pure hallucinations.
            if st in ("verified", "skipped") or (ob.get("verify_url") and _host_ok(ob["verify_url"])):
                kept.append(ob)
        retrievals.append({"law_id": law.law_id, "law": law.name,
                           "reasoning": got.get("reasoning", ""), "obligations": kept})

    # source research is coverage guidance only. It never mutates the deterministic
    # verdict, headline, purpose matrix, or because_laws.
    source_research = research_and_validate_sources(
        fsum, list(law_names.values()), ep, model, key, cache, verify=verify
    )
    extended = _legacy_extended_from_source_research(source_research)

    return {"input": inp, "report": report, "facts_summary": fsum,
            "retrievals": retrievals, "extended": extended,
            "source_research": source_research}
