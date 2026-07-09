"""
main.py - FastAPI app for Data Boundary.

Endpoints
    GET  /                              serve the packaged single-page UI
    GET  /health                        {status, core_version}
    GET  /api/domain-packs              registered legacy rule packs
    POST /api/assessments/normalize     legacy free-text normalization endpoint
    POST /api/assessments               legacy structured assessment endpoint
    GET  /api/settings                  LLM backend + providers (never the raw key)
    POST /api/settings                  save the LLM backend
    POST /api/test_connection           ping the configured LLM

The current product UI uses the /api/datause/* endpoints.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import CORE_VERSION, PKG_DATA
from .models.schemas import AssessmentInput, NormalizeResponse
from .core.engine import assess as engine_assess
from .core.router import route
from .core.normalizer import extract_from_text, coerce_to_input, blank_input
from .domain_packs import list_domain_packs, get_pack_by_id
from .config import (resolve_backend, save_backend, clear_api_key, load_config, masked_key,
                     provider_options, has_llm_key, _infer_provider,
                     SELECTABLE_PROVIDERS)
from .privacy.pipeline import (extract_facts as datause_extract,
                               assess_run as datause_assess,
                               scope_chat as datause_scope, chat as datause_chat)
# aliased so it does NOT shadow models.schemas.AssessmentInput used by /api/assessments
from .privacy.schema import AssessmentInput as DataUseInput

INDEX_HTML = Path(str(PKG_DATA / "index.html"))
DATAUSE_HTML = Path(str(PKG_DATA / "datause.html"))

app = FastAPI(title="Data Boundary", version=CORE_VERSION)


# ─────────────────────────── request models ───────────────────────────
class NormalizeRequest(BaseModel):
    text: Optional[str] = None            # free-text scenario (AI-autofill path)
    input: Optional[dict[str, Any]] = None  # partial/edited structured form


# ─────────────────────────── static + health ───────────────────────────
_NOCACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}


@app.get("/")
def root():
    # The privacy data-use checker is the current focus; serve it at / .
    # no-cache so the browser always fetches the latest UI during active dev.
    if DATAUSE_HTML.exists():
        return FileResponse(str(DATAUSE_HTML), headers=_NOCACHE)
    if INDEX_HTML.exists():
        return FileResponse(str(INDEX_HTML), headers=_NOCACHE)
    return JSONResponse({"detail": "UI not built yet — see /docs for the API."},
                        status_code=404)


@app.get("/compliance")
def compliance_page():
    if INDEX_HTML.exists():
        return FileResponse(str(INDEX_HTML))
    raise HTTPException(404, "compliance UI not built")


class DataUseExtractRequest(BaseModel):
    text: Optional[str] = None


@app.post("/api/datause/extract")
def api_datause_extract(req: DataUseExtractRequest):
    """Phase ①: free text → structured facts (LLM) + a formal restatement. Fast.
    The client then shows the editable schema card for the user to confirm/correct."""
    if not req.text or not req.text.strip():
        raise HTTPException(400, "provide a scenario description in 'text'")
    if not has_llm_key():
        raise HTTPException(400, "No LLM key configured — set one in Settings.")
    ep, model, key = resolve_backend()
    try:
        inp, understanding = datause_extract(req.text[:20000], ep, model, key)
    except Exception as e:  # pragma: no cover — defensive
        raise HTTPException(500, f"extract failed ({type(e).__name__})")
    return {"facts": inp.model_dump(), "understanding": understanding}


class DataUseAssessRequest(BaseModel):
    facts: dict[str, Any] = {}
    verify: bool = True


@app.post("/api/datause/assess")
def api_datause_assess(req: DataUseAssessRequest):
    """Phase ②: CONFIRMED facts → gate verdict + per-law CoT retrieval + deep case-scan
    + domain-gated quote-verification + per-purpose narration. Slow (several LLM calls)."""
    if not has_llm_key():
        raise HTTPException(400, "No LLM key configured — set one in Settings.")
    try:
        inp = DataUseInput(**(req.facts or {}))
    except Exception as e:
        raise HTTPException(400, f"invalid facts ({type(e).__name__})")
    ep, model, key = resolve_backend()
    try:
        out = datause_assess(inp, ep, model, key, verify=req.verify)
    except Exception as e:  # pragma: no cover — defensive
        raise HTTPException(500, f"assess failed ({type(e).__name__})")
    return {
        "facts": out["input"].model_dump(),
        "facts_summary": out["facts_summary"],
        "report": out["report"].model_dump(),
        "retrievals": out["retrievals"],
        "extended": out["extended"],
        "source_research": out.get("source_research", {}),
    }


class DataUseScopeRequest(BaseModel):
    history: list[dict[str, Any]] = []
    question: str


@app.post("/api/datause/scope")
def api_datause_scope(req: DataUseScopeRequest):
    """Left-panel pre-check assistant: helps articulate the scenario, gathers facts,
    stays in the data-use/privacy domain, and never issues a verdict."""
    if not req.question or not req.question.strip():
        raise HTTPException(400, "empty question")
    if not has_llm_key():
        raise HTTPException(400, "No LLM key configured — set one in Settings.")
    ep, model, key = resolve_backend()
    try:
        ans = datause_scope(req.history[-20:], req.question.strip()[:4000], ep, model, key)
    except Exception as e:  # pragma: no cover — defensive
        raise HTTPException(500, f"scope chat failed ({type(e).__name__})")
    return {"answer": ans}


class DataUseChatRequest(BaseModel):
    context: str = ""
    history: list[dict[str, Any]] = []
    question: str


@app.post("/api/datause/chat")
def api_datause_chat(req: DataUseChatRequest):
    """Right-panel report-grounded assistant: explains the standing rule-decided verdict,
    never overrides it, and routes fact-changes back to a re-check."""
    if not req.question or not req.question.strip():
        raise HTTPException(400, "empty question")
    if not has_llm_key():
        raise HTTPException(400, "No LLM key configured — set one in Settings.")
    ep, model, key = resolve_backend()
    try:
        ans = datause_chat(req.context[:8000], req.history[-20:], req.question.strip()[:4000], ep, model, key)
    except Exception as e:  # pragma: no cover — defensive
        raise HTTPException(500, f"chat failed ({type(e).__name__})")
    return {"answer": ans}


@app.get("/health")
def health():
    return {"status": "ok", "core_version": CORE_VERSION}


@app.get("/api/domain-packs")
def domain_packs():
    return list_domain_packs()


# ─────────────────────────── normalize (AI-autofill) ───────────────────────────
@app.post("/api/assessments/normalize", response_model=NormalizeResponse)
def normalize(req: NormalizeRequest):
    warnings: list[str] = []
    llm_used = False

    if req.input is not None:
        # The client already has structured fields (e.g. re-routing after edits).
        # coerce_to_input is hardened never to raise; guard anyway so a malformed
        # edited form degrades to a warning instead of a 500.
        try:
            inp = coerce_to_input(req.input, query=req.text)
        except Exception as e:  # pragma: no cover — defensive
            inp = blank_input(query=req.text)
            warnings.append(f"Could not use the submitted form as-is: {e}")
    elif req.text and req.text.strip():
        if has_llm_key():
            ep, mdl, key = resolve_backend()
            res = extract_from_text(req.text, ep, mdl, key)
            inp, warnings, llm_used = res.input, res.warnings, res.llm_used
        else:
            inp = blank_input(query=req.text)
            warnings.append("No LLM key configured — add one in Settings to auto-fill "
                            "the form from text, or fill the form manually.")
    else:
        inp = blank_input()

    candidates = route(inp)
    top = candidates[0].domain_pack_id if candidates else "custom"
    pack = get_pack_by_id(top)
    missing = pack.get_missing_information(inp)

    return NormalizeResponse(
        normalized_input=inp,
        domain_candidates=candidates,
        missing_information=missing,
        llm_used=llm_used,
        warnings=warnings,
    )


# ─────────────────────────── run assessment ───────────────────────────
@app.post("/api/assessments")
def run_assessment(assessment: AssessmentInput):
    try:
        report = engine_assess(assessment)
    except Exception as e:  # pragma: no cover — defensive
        raise HTTPException(500, f"assessment failed: {type(e).__name__}: {e}")
    return report


# ─────────────────────────── settings ───────────────────────────
@app.get("/api/settings")
def get_settings():
    cfg = load_config()["backend"]
    has_key, hint = masked_key()
    return {
        "backend": {"provider": cfg["provider"], "endpoint": cfg["endpoint"],
                    "model": cfg["model"], "has_key": has_key, "key_hint": hint},
        "providers": provider_options(),
    }


@app.post("/api/settings")
def post_settings(provider: str = Form(""), endpoint: str = Form(""),
                  model: str = Form(""), api_key: str = Form("")):
    prov = provider or _infer_provider(endpoint)
    if prov not in SELECTABLE_PROVIDERS:
        raise HTTPException(400, f"provider {prov!r} is not selectable")
    try:
        save_backend(prov, endpoint, model, api_key or None)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return get_settings()


@app.post("/api/settings/clear_key")
def post_settings_clear_key():
    clear_api_key()
    return get_settings()


@app.post("/api/test_connection")
def test_connection():
    from .core.normalizer import _post_chat
    ep, mdl, key = resolve_backend()
    if not has_llm_key():
        return {"ok": False, "endpoint": ep, "model": mdl,
                "error": "no API key configured"}
    try:
        out = _post_chat(ep, [{"role": "user", "content": "reply with the single word: ok"}],
                         mdl, key, timeout=60, max_tokens=64)
        return {"ok": True, "endpoint": ep, "model": mdl,
                "sample": (out or "").strip()[:40] or "(empty)"}
    except Exception as e:
        msg = str(e)
        if "401" in msg or "403" in msg:
            msg = "authentication failed — check the API key"
        return {"ok": False, "endpoint": ep, "model": mdl, "error": msg[:200]}


if __name__ == "__main__":
    import uvicorn
    from . import LOCAL_WEB_PORT
    uvicorn.run(app, host="127.0.0.1", port=LOCAL_WEB_PORT)
