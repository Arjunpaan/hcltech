"""
scripts/test_llm.py - Check that the AI model in .env really answers.

Run from the backend folder:   python scripts/test_llm.py          (just test)
                               python scripts/test_llm.py --fix    (also fix .env if it can)

For Gemini it also:
- tries both ways of sending the key (x-goog-api-key header, then Bearer token),
- lists the models your key can use, and checks that LLM_MODEL is one of them.
"""

import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import httpx  # noqa: E402

import config  # noqa: E402
import db  # noqa: E402
from services import llm  # noqa: E402

ENV_FILE = config.PROJECT_ROOT / ".env"


def set_env_value(key: str, value: str) -> None:
    """Write KEY=value into the project's .env file (replace the line or add it)."""
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    for index, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[index] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"   -> updated .env: {key}={value}")


def gemini_list_models(auth: str) -> tuple[int, list[str], str]:
    """Ask Gemini which models this key can use. Returns (status, model names, error text)."""
    headers, params = {}, {"pageSize": 200}
    if auth == "bearer":
        headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"
    elif auth == "query":
        params["key"] = config.LLM_API_KEY
    else:
        headers["x-goog-api-key"] = config.LLM_API_KEY
    try:
        response = httpx.get(f"{config.LLM_BASE_URL}/models", headers=headers, params=params, timeout=30)
    except httpx.HTTPError as exc:
        return 0, [], f"Network error: {exc}"
    if response.status_code != 200:
        return response.status_code, [], response.text[:400]
    names = [m["name"].replace("models/", "") for m in response.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    return 200, names, ""


def try_vertex(base_url: str) -> bool:
    """One tiny call to Vertex AI express mode with the key in the URL."""
    body = {"contents": [{"role": "user", "parts": [{"text": "Reply with exactly: OK"}]}]}
    for model in [config.LLM_MODEL, "gemini-2.5-flash", "gemini-2.0-flash"]:
        try:
            response = httpx.post(f"{base_url}/models/{model}:generateContent",
                                  params={"key": config.LLM_API_KEY}, json=body, timeout=60)
        except httpx.HTTPError as exc:
            print(f"  Vertex ({model}): network error {exc}")
            return False
        print(f"  Vertex ({model}): HTTP {response.status_code} {'OK' if response.status_code == 200 else response.text[:300]}")
        if response.status_code == 200:
            if model != config.LLM_MODEL and "--fix" in sys.argv:
                set_env_value("LLM_MODEL", model)
            return True
        if response.status_code in (401, 403):
            return False  # the key itself is refused; other models will not help
    return False


def main() -> int:
    fix = "--fix" in sys.argv
    db.init_db()
    print(f"AI settings: mode={config.LLM_MODE} provider={config.LLM_PROVIDER} model={config.LLM_MODEL}")
    print(f"             url={config.LLM_BASE_URL}")
    if config.LLM_MODE == "mock":
        print("LLM_MODE=mock: no real AI is used. Set LLM_MODE=hosted in .env to use your key.")
        return 0
    if not config.LLM_API_KEY:
        print("FAIL: LLM_API_KEY is empty in .env")
        return 1

    if config.LLM_PROVIDER == "gemini":
        # 1) Which way of sending the key works?
        working_auth, models = None, []
        # Try every way of sending the key: header, ?key= in the URL, Bearer token.
        for auth in ([config.GEMINI_AUTH] + [a for a in ("api_key", "query", "bearer") if a != config.GEMINI_AUTH]):
            status, models, error = gemini_list_models(auth)
            print(f"Key check ({auth}): HTTP {status} {'OK' if status == 200 else error}")
            if status == 200:
                working_auth = auth
                break
        if not working_auth:
            # Keys starting with "AQ." are often Vertex AI express keys: try that address.
            print("Gemini API did not accept the key. Trying Vertex AI express mode...")
            vertex_url = "https://aiplatform.googleapis.com/v1/publishers/google"
            if try_vertex(vertex_url):
                print("The key works with Vertex AI express mode.")
                if fix:
                    set_env_value("LLM_PROVIDER", "vertex")
                    set_env_value("LLM_BASE_URL", vertex_url)
                    print("Restart the backend so it uses the new settings.")
                return 0
            print("FAIL: the key was not accepted by the Gemini API or by Vertex AI express.")
            print("      Create a normal key at https://aistudio.google.com/apikey (it starts with 'AIza').")
            return 1
        if working_auth != config.GEMINI_AUTH:
            print(f"The key works with GEMINI_AUTH={working_auth}.")
            if fix:
                set_env_value("GEMINI_AUTH", working_auth)
            config.GEMINI_AUTH = working_auth

        # 2) Is the chosen model available to this key?
        flash = [m for m in models if "flash" in m and "image" not in m and "tts" not in m and "live" not in m]
        print(f"Models your key can use ({len(models)}). Flash models: {', '.join(flash[:12]) or 'none'}")
        if config.LLM_MODEL not in models:
            suggestion = next((m for m in flash if "lite" not in m), flash[0] if flash else (models[0] if models else None))
            print(f"WARNING: LLM_MODEL={config.LLM_MODEL} is not in your list. Suggested: {suggestion}")
            if fix and suggestion:
                set_env_value("LLM_MODEL", suggestion)
                config.LLM_MODEL = suggestion

    if config.LLM_PROVIDER == "openai" and "api.openai.com" in config.LLM_BASE_URL:
        # Which models can this OpenAI key use? Pick a fast, good one if ours is missing.
        try:
            response = httpx.get(f"{config.LLM_BASE_URL}/models",
                                 headers={"Authorization": f"Bearer {config.LLM_API_KEY}"}, timeout=30)
        except httpx.HTTPError as exc:
            print(f"FAIL: cannot reach OpenAI: {exc}")
            return 1
        print(f"Key check (OpenAI): HTTP {response.status_code} {'OK' if response.status_code == 200 else response.text[:300]}")
        if response.status_code == 401:
            print("FAIL: OpenAI rejected this key. Create a normal key at platform.openai.com/api-keys.")
            return 1
        # Restricted keys may not be allowed to LIST models but can still USE them: carry on.
        models = sorted(m["id"] for m in response.json().get("data", [])) if response.status_code == 200 else []
        if not models:
            print("Could not list models with this key (restricted key?). Testing a real call instead.")
        preferred = ["gpt-4.1-mini", "gpt-4o-mini", "gpt-4.1", "gpt-4o", "gpt-5-mini", "gpt-5"]
        available = [m for m in preferred if m in models]
        print(f"Good models for this project on your key: {', '.join(available) or 'none of the usual ones'}")
        if models and config.LLM_MODEL not in models:
            suggestion = available[0] if available else None
            print(f"WARNING: LLM_MODEL={config.LLM_MODEL} is not available. Suggested: {suggestion}")
            if fix and suggestion:
                set_env_value("LLM_MODEL", suggestion)
                config.LLM_MODEL = suggestion

    # 3) One real, tiny call (cache off so it really reaches the model).
    config.LLM_CACHE = False
    started = time.time()
    try:
        answer = llm.chat(None, "setup_test", "You are a test. Reply with exactly: OK", "Reply now.")
    except llm.LLMError as exc:
        print(f"FAIL: {exc}")
        return 1
    print(f"SUCCESS: model {config.LLM_MODEL} answered {answer.strip()[:60]!r} in {time.time() - started:.1f}s")
    env_model = next((line.split("=", 1)[1].strip() for line in
                      (ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else [])
                      if line.startswith("LLM_MODEL=")), "")
    if fix and env_model and env_model != config.LLM_MODEL:
        set_env_value("LLM_MODEL", config.LLM_MODEL)   # save the model that actually worked
    return 0


if __name__ == "__main__":
    sys.exit(main())
