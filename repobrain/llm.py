"""Optional, vendor-neutral LLM step. The offline engine never needs it.

Pick a provider with REPOBRAIN_LLM:
  anthropic  (default if ANTHROPIC_API_KEY is set)   REPOBRAIN_LLM_MODEL to override the model
  openai     any OpenAI-compatible endpoint          OPENAI_API_KEY, REPOBRAIN_LLM_URL (default https://api.openai.com/v1)
  ollama     a local model, nothing leaves the machine   REPOBRAIN_LLM_URL (default http://127.0.0.1:11434)
Every LLM-produced change is verified exactly like a rule-based one (tests + differential fuzzing).
"""
import json, os, urllib.request


def provider():
    p = (os.environ.get("REPOBRAIN_LLM") or "").lower()
    if p in ("anthropic", "openai", "ollama"):
        return p
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return ""


def available():
    p = provider()
    if p == "anthropic": return bool(os.environ.get("ANTHROPIC_API_KEY"))
    if p == "openai": return bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("REPOBRAIN_LLM_URL"))
    return p == "ollama"


def _post(url, body, headers):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"content-type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def ask(prompt, system="", max_tokens=4000):
    p = provider()
    model = os.environ.get("REPOBRAIN_LLM_MODEL")
    if p == "anthropic":
        url = os.environ.get("REPOBRAIN_LLM_URL", "https://api.anthropic.com").rstrip("/") + "/v1/messages"
        data = _post(url, {"model": model or "claude-sonnet-4-6", "max_tokens": max_tokens, "system": system,
                           "messages": [{"role": "user", "content": prompt}]},
                     {"anthropic-version": "2023-06-01", "x-api-key": os.environ["ANTHROPIC_API_KEY"]})
        return "".join(b.get("text", "") for b in data["content"])
    if p == "openai":
        url = os.environ.get("REPOBRAIN_LLM_URL", "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
        key = os.environ.get("OPENAI_API_KEY", "")
        data = _post(url, {"model": model or "gpt-4o-mini", "max_tokens": max_tokens,
                           "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]},
                     {"authorization": f"Bearer {key}"} if key else {})
        return data["choices"][0]["message"]["content"]
    if p == "ollama":
        url = os.environ.get("REPOBRAIN_LLM_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/chat"
        data = _post(url, {"model": model or "llama3.1", "stream": False,
                           "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}, {})
        return data["message"]["content"]
    raise RuntimeError("no LLM configured (set REPOBRAIN_LLM or ANTHROPIC_API_KEY)")
