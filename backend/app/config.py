"""
config.py - local, user-editable model-service settings.

Key handling (unchanged from statLens):
  - stored 0600 under ~/.config/data-boundary/config.json
  - NEVER returned to the browser (only a masked hint)
  - resolution precedence: env > config file > provider preset

The app ships with no key. A real key is required for model-assisted fact
extraction, assessment narration, source discovery, validation, and Fact Review.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_VERSION = 1

# Selectable = a live OpenAI-compatible /chat/completions backend. All of these
# (including Claude, via Anthropic's OpenAI-compatible endpoint) accept the same
# Bearer-key + /chat/completions shape used by core/normalizer.py.
PROVIDERS: dict[str, dict] = {
    "deepseek": {"label": "DeepSeek", "selectable": True,
                 "default_endpoint": "https://api.deepseek.com/v1",
                 "default_model": "deepseek-chat"},
    "openai": {"label": "ChatGPT (OpenAI)", "selectable": True,
               "default_endpoint": "https://api.openai.com/v1",
               "default_model": "gpt-4o-mini"},
    "claude": {"label": "Claude (Anthropic)", "selectable": True,
               "default_endpoint": "https://api.anthropic.com/v1",
               "default_model": "claude-sonnet-4-5"},
    "qwen": {"label": "Qwen", "selectable": True,
             "default_endpoint": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
             "default_model": "qwen-plus"},
    "custom": {"label": "Custom (OpenAI-compatible)", "selectable": True,
               "default_endpoint": "",
               "default_model": ""},
}
SELECTABLE_PROVIDERS = [k for k, v in PROVIDERS.items() if v["selectable"]]
_DEFAULT_PROVIDER = "deepseek"


def config_path() -> Path:
    root = os.environ.get("CCA_CONFIG_DIR")
    base = Path(root).expanduser() if root else Path.home() / ".config" / "data-boundary"
    return base / "config.json"


def _default_backend() -> dict:
    p = PROVIDERS[_DEFAULT_PROVIDER]
    return {"provider": _DEFAULT_PROVIDER,
            "endpoint": p["default_endpoint"],
            "model": p["default_model"],
            "api_key": ""}


def _infer_provider(endpoint: str) -> str:
    e = (endpoint or "").lower()
    if "anthropic.com" in e:
        return "claude"
    if "openai.com" in e:
        return "openai"
    if "dashscope" in e or "aliyun" in e:
        return "qwen"
    if "deepseek" in e:
        return "deepseek"
    return "custom"


def _norm_backend(raw: dict | None) -> dict:
    """Normalize a backend dict over the default (never raises)."""
    out = _default_backend()
    if isinstance(raw, dict):
        for k in ("provider", "endpoint", "model", "api_key"):
            if raw.get(k) is not None:
                out[k] = raw[k]
        if out["provider"] not in PROVIDERS:
            out["provider"] = _infer_provider(out.get("endpoint", ""))
    return out


def load_config() -> dict:
    """ALWAYS return a normalized {version, backend}."""
    p = config_path()
    data = None
    if p.exists():
        try:
            data = json.loads(p.read_text())
        except Exception:
            data = None
    if not isinstance(data, dict):
        return {"version": CONFIG_VERSION, "backend": _default_backend()}
    return {"version": CONFIG_VERSION, "backend": _norm_backend(data.get("backend"))}


def _write(cfg: dict) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # Create at 0600 up front so the plaintext key is NEVER on disk at a wider
    # mode (write-then-chmod leaves a world-readable window at the default umask).
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(cfg, indent=2))
    # Normalize a pre-existing, looser file too (best-effort).
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass


def save_backend(provider: str, endpoint: str, model: str,
                 api_key: str | None) -> None:
    """Persist the backend. Empty endpoint/model fall back to the provider
    preset; api_key None/'' keeps the stored key. Raises ValueError on a bad
    provider (but 'custom' with a blank endpoint is allowed to be saved)."""
    if provider not in SELECTABLE_PROVIDERS:
        raise ValueError(f"provider {provider!r} is not selectable")
    preset = PROVIDERS[provider]
    cfg = load_config()
    cur = cfg["backend"]
    cfg["backend"] = {
        "provider": provider,
        "endpoint": (endpoint or preset["default_endpoint"]).strip(),
        "model": (model or preset["default_model"]).strip(),
        "api_key": (api_key if api_key else cur.get("api_key", "")),
    }
    cfg["version"] = CONFIG_VERSION
    _write(cfg)


def clear_api_key() -> None:
    """Remove the locally stored API key while preserving provider settings."""
    cfg = load_config()
    cfg["backend"]["api_key"] = ""
    cfg["version"] = CONFIG_VERSION
    _write(cfg)


def resolve_backend() -> tuple[str, str, str]:
    """Return (endpoint, model, api_key); env > file > preset.

    No baked-in credentials — the app ships with NO keys. api_key falls back to
    'dummy' so a local/self-hosted endpoint that ignores auth still works.
    """
    b = load_config()["backend"]
    endpoint = os.environ.get("CCA_LLM_ENDPOINT") or b["endpoint"]
    model = os.environ.get("CCA_LLM_MODEL") or b["model"]
    api_key = os.environ.get("CCA_LLM_API_KEY") or b.get("api_key") or "dummy"
    return endpoint, model, api_key


def has_llm_key() -> bool:
    """True if a real (non-dummy) key is configured — gates the autofill path."""
    _e, _m, k = resolve_backend()
    return bool(k) and k != "dummy"


def masked_key() -> tuple[bool, str]:
    """(has_key, masked) — never expose the raw key."""
    _e, _m, k = resolve_backend()
    if not k or k == "dummy":
        return False, ""
    tail = k[-4:] if len(k) >= 4 else k
    return True, f"••••••••{tail}"


def provider_options() -> list[dict]:
    """Flat list for the UI dropdown."""
    return [{"id": pid, "label": p["label"], "selectable": p["selectable"],
             "default_endpoint": p["default_endpoint"],
             "default_model": p["default_model"]}
            for pid, p in PROVIDERS.items()]
