"""
services/llm.py - The ONE place that talks to the AI model.

All 8 agents call `chat()`. They do not care which model is behind it.

Modes (set LLM_MODE in .env):
- hosted : a real API. Two formats are supported (LLM_PROVIDER):
             gemini -> Google Gemini's own generateContent API (AI Studio keys)
             openai -> any OpenAI-compatible API: Groq, OpenRouter, Ollama, ...
- mock   : built-in canned answers. No internet, no key, no tokens. Used for
           tests and as a demo backup.
- replay : reuse answers saved from an earlier hosted run (LLM_CACHE). No tokens.

Token saving: with LLM_CACHE=true, every hosted answer is saved in SQLite.
If the exact same question is asked again, the saved answer is used.
"""

import hashlib
import time

import httpx

import config
import db
from services import mock_llm


class LLMError(Exception):
    """Raised when the AI model cannot give an answer."""


def chat(run_id: int | None, agent: str, system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
    """
    Send one question to the AI and return its text answer.
    json_mode=True asks the model to reply with pure JSON (used by the JSON agents).
    Every call (success or failure) is recorded in the llm_calls table.
    """
    mode = config.LLM_MODE
    cache_key = _cache_key(system_prompt, user_prompt)
    started = time.time()

    # 1) Replay / cache: reuse a saved answer if we have one.
    if mode in ("hosted", "replay") and (config.LLM_CACHE or mode == "replay"):
        cached = db.query_one("SELECT response FROM llm_cache WHERE key = ?", (cache_key,))
        if cached:
            _record(run_id, agent, mode, system_prompt, user_prompt, cached["response"],
                    started, from_cache=True)
            return cached["response"]
        if mode == "replay":
            error = "Replay mode: no saved answer for this exact question. Run once in hosted mode first."
            _record(run_id, agent, mode, system_prompt, user_prompt, "", started, error=error)
            raise LLMError(error)

    # 2) Mock: canned answers, no network.
    if mode == "mock":
        answer = mock_llm.respond(agent, system_prompt, user_prompt)
        _record(run_id, agent, mode, system_prompt, user_prompt, answer, started)
        return answer

    # 3) Hosted: call the real API.
    try:
        if config.LLM_PROVIDER in ("gemini", "vertex"):
            answer, usage = _call_gemini(system_prompt, user_prompt, json_mode)
        else:
            answer, usage = _call_hosted(system_prompt, user_prompt, json_mode)
    except Exception as exc:  # network errors, bad key, rate limits...
        _record(run_id, agent, mode, system_prompt, user_prompt, "", started, error=str(exc))
        raise LLMError(f"{agent}: AI call failed: {exc}") from exc

    if config.LLM_CACHE:
        db.execute(
            "INSERT OR REPLACE INTO llm_cache (key, response, created_at) VALUES (?, ?, ?)",
            (cache_key, answer, db.now()),
        )
    _record(run_id, agent, mode, system_prompt, user_prompt, answer, started, usage=usage)
    return answer


def _call_hosted(system_prompt: str, user_prompt: str, json_mode: bool = False) -> tuple[str, dict]:
    """
    POST to {LLM_BASE_URL}/chat/completions (OpenAI format; also Groq, OpenRouter, Ollama).

    Newer OpenAI models refuse some old settings (for example they want
    "max_completion_tokens" instead of "max_tokens", or no "temperature").
    If the API says a setting is not supported, we adjust that one setting and
    try again automatically, so any model name works.
    On HTTP 429 (rate limit) we wait and try again.
    """
    if not config.LLM_API_KEY and "localhost" not in config.LLM_BASE_URL:
        raise LLMError("LLM_API_KEY is empty. Put your key in .env or set LLM_MODE=mock.")

    url = f"{config.LLM_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY or 'ollama'}",
               "Content-Type": "application/json"}
    if config.LLM_ORGANIZATION:
        headers["OpenAI-Organization"] = config.LLM_ORGANIZATION
    if config.LLM_PROJECT:
        headers["OpenAI-Project"] = config.LLM_PROJECT
    body = {
        "model": config.LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": config.LLM_TEMPERATURE,
    }
    # Real OpenAI uses max_completion_tokens; other OpenAI-compatible services use max_tokens.
    if "api.openai.com" in config.LLM_BASE_URL:
        body["max_completion_tokens"] = config.LLM_MAX_TOKENS
    else:
        body["max_tokens"] = config.LLM_MAX_TOKENS
    if config.LLM_REASONING_EFFORT:
        body["reasoning_effort"] = config.LLM_REASONING_EFFORT
    if json_mode:
        body["response_format"] = {"type": "json_object"}  # the prompts say "JSON", as OpenAI requires

    waits = [5, 15, 30]   # seconds to wait after a "too many requests" reply
    rate_retries = 0
    tried_models = {body["model"]}
    for _attempt in range(16):
        response = httpx.post(url, headers=headers, json=body, timeout=config.LLM_TIMEOUT_SECONDS)
        error_text = response.text.lower() if response.status_code >= 400 else ""

        # No credit on the account: waiting will not help, say it clearly.
        if response.status_code == 429 and "insufficient_quota" in error_text:
            raise LLMError("This API key has no credit left (insufficient_quota). Add credit at "
                           "platform.openai.com/settings/organization/billing or use another key.")
        # Wrong kind of key (e.g. an admin key) or invalid key.
        if response.status_code == 401:
            raise LLMError("The API key was rejected (401). Use a normal project/user key from "
                           "platform.openai.com/api-keys (admin keys cannot call models).")
        # This key cannot use this model: switch to the next model in LLM_FALLBACK_MODELS.
        if response.status_code in (403, 404) and any(w in error_text for w in (
                "model_not_found", "does not exist", "do not have access", "not have access", "not found")):
            next_model = next((m for m in config.LLM_FALLBACK_MODELS if m not in tried_models), None)
            if next_model and "localhost" not in config.LLM_BASE_URL:
                print(f"[llm] Model {body['model']} not available to this key; trying {next_model}")
                body["model"] = next_model
                config.LLM_MODEL = next_model   # keep using the one that works
                tried_models.add(next_model)
                continue
        if response.status_code == 429 and rate_retries < len(waits):
            retry_after = response.headers.get("retry-after")
            time.sleep(float(retry_after) if retry_after and retry_after.replace(".", "").isdigit()
                       else waits[rate_retries])
            rate_retries += 1
            continue
        if response.status_code == 400 and _adjust_unsupported_setting(body, response.text):
            continue  # one setting was changed; try again
        if response.status_code >= 400:
            raise LLMError(f"HTTP {response.status_code}: {response.text[:500]}")
        data = response.json()
        choice = data["choices"][0]
        if choice.get("finish_reason") == "length":
            raise LLMError("Answer was cut off (length). Increase LLM_MAX_TOKENS or ask for a smaller feature.")
        text = choice["message"].get("content") or ""
        if not text.strip():
            raise LLMError("The model returned an empty answer.")
        return text, data.get("usage") or {}
    raise LLMError("Rate limit or unsupported settings: still failing after several retries.")


def _adjust_unsupported_setting(body: dict, error_text: str) -> bool:
    """
    Read a 400 error and fix the one setting it complains about.
    Returns True if something was changed (so the caller should try again).
    """
    text = error_text.lower()
    token_key = "max_tokens" if "max_tokens" in body else "max_completion_tokens"
    if token_key in body and any(w in text for w in ("too large", "at most", "maximum", "exceeds")) \
            and body[token_key] > 2048:
        body[token_key] = max(2048, body[token_key] // 2)   # model allows fewer output tokens
        return True
    if "max_tokens" in text and "max_tokens" in body:
        body["max_completion_tokens"] = body.pop("max_tokens")
        return True
    if "max_completion_tokens" in text and "max_completion_tokens" in body:
        body["max_tokens"] = body.pop("max_completion_tokens")
        return True
    if "temperature" in text and "temperature" in body:
        body.pop("temperature")
        return True
    if "reasoning_effort" in text and "reasoning_effort" in body:
        body.pop("reasoning_effort")
        return True
    if "response_format" in text and "response_format" in body:
        body.pop("response_format")
        return True
    return False


def _call_gemini(system_prompt: str, user_prompt: str, json_mode: bool) -> tuple[str, dict]:
    """
    POST to {LLM_BASE_URL}/models/{LLM_MODEL}:generateContent (Google Gemini's own format).
    Works for both Google AI Studio keys (provider "gemini") and Vertex AI express keys (provider "vertex").
    On HTTP 429 (free-tier rate limit) we wait and try again, up to 3 times.
    """
    if not config.LLM_API_KEY:
        raise LLMError("LLM_API_KEY is empty. Put your Gemini key in .env or set LLM_MODE=mock.")

    url = f"{config.LLM_BASE_URL}/models/{config.LLM_MODEL}:generateContent"
    headers = {"Content-Type": "application/json"}
    params = {}
    if config.LLM_PROVIDER == "vertex" or config.GEMINI_AUTH == "query":
        params["key"] = config.LLM_API_KEY           # key in the URL: ...?key=YOUR_KEY
    elif config.GEMINI_AUTH == "bearer":
        headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"
    else:
        headers["x-goog-api-key"] = config.LLM_API_KEY
    generation = {"temperature": config.LLM_TEMPERATURE, "maxOutputTokens": config.LLM_MAX_TOKENS}
    if json_mode:
        generation["responseMimeType"] = "application/json"
    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": generation,
    }

    waits = [10, 20, 40]  # free tiers allow only a few requests per minute
    for attempt in range(len(waits) + 1):
        response = httpx.post(url, headers=headers, params=params, json=body, timeout=config.LLM_TIMEOUT_SECONDS)
        if response.status_code in (429, 503) and attempt < len(waits):
            time.sleep(waits[attempt])
            continue
        if response.status_code >= 400:
            raise LLMError(f"HTTP {response.status_code}: {response.text[:600]}")
        data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no answer returned")
            raise LLMError(f"Gemini returned no answer ({reason})")
        candidate = candidates[0]
        parts = (candidate.get("content") or {}).get("parts") or []
        # Skip the model's hidden "thinking" parts; keep only the real answer.
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        finish = candidate.get("finishReason", "")
        if finish == "MAX_TOKENS":
            raise LLMError("Answer was cut off (MAX_TOKENS). Increase LLM_MAX_TOKENS in .env or ask for a smaller feature.")
        if not text.strip():
            raise LLMError(f"Gemini returned an empty answer (finishReason={finish})")
        meta = data.get("usageMetadata") or {}
        return text, {"prompt_tokens": meta.get("promptTokenCount"),
                      "completion_tokens": meta.get("candidatesTokenCount")}
    raise LLMError("Rate limit: still busy after several retries. Wait a minute and press Retry.")


def _cache_key(system_prompt: str, user_prompt: str) -> str:
    """Same model + same prompts = same key."""
    raw = f"{config.LLM_MODEL}\n{system_prompt}\n{user_prompt}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _record(run_id, agent, mode, system_prompt, user_prompt, answer, started,
            usage=None, from_cache=False, error=None) -> None:
    """Write one row to llm_calls so every AI call is visible and auditable."""
    usage = usage or {}
    db.execute(
        "INSERT INTO llm_calls (run_id, agent, mode, model, prompt_chars, response_chars, prompt_tokens, "
        "completion_tokens, duration_ms, from_cache, ok, error, prompt, response, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id, agent, mode, "mock" if mode == "mock" else f"{config.LLM_PROVIDER}:{config.LLM_MODEL}",
            len(system_prompt) + len(user_prompt), len(answer or ""),
            usage.get("prompt_tokens"), usage.get("completion_tokens"),
            int((time.time() - started) * 1000), 1 if from_cache else 0,
            0 if error else 1, error,
            (system_prompt + "\n\n---\n\n" + user_prompt)[:20000], (answer or "")[:20000], db.now(),
        ),
    )
