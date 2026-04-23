import json
import os
import time
import urllib.request
import urllib.error
from typing import Optional

from user_data.agents import learning_db

MODELS = {
    "decision": "google/gemini-2.0-flash-lite-001",
    "analysis": "anthropic/claude-sonnet-4.6",
}

DAILY_LIMIT = 200
TIMEOUT_SECONDS = 5
MAX_RETRIES = 2
BASE_URL = "https://openrouter.ai/api/v1/chat/completions"


class CallLimitExceeded(Exception):
    pass


def _load_api_key() -> str:
    secrets_path = os.path.expanduser("~/.secrets")
    with open(secrets_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1]
    raise RuntimeError("OPENROUTER_API_KEY not found in ~/.secrets")


_api_key: Optional[str] = None


def _get_api_key() -> str:
    global _api_key
    if _api_key is None:
        _api_key = _load_api_key()
    return _api_key


def call_llm(prompt: str, tier: str = "analysis", system_prompt: str = "") -> dict:
    if tier not in MODELS:
        raise ValueError(f"Unknown tier '{tier}', must be one of: {list(MODELS.keys())}")

    current_count = learning_db.get_daily_calls()
    if current_count >= DAILY_LIMIT:
        raise CallLimitExceeded(
            f"Daily call limit of {DAILY_LIMIT} reached ({current_count} calls today)"
        )

    model = MODELS[tier]
    api_key = _get_api_key()

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = json.dumps({
        "model": model,
        "messages": messages,
    }).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        if attempt > 0:
            time.sleep(2 ** attempt)

        try:
            req = urllib.request.Request(BASE_URL, data=payload, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                raw = json.loads(resp.read().decode("utf-8"))

            learning_db.increment_daily_calls()

            content = raw["choices"][0]["message"]["content"]
            return _parse_json_response(content)

        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            last_error = e

    raise RuntimeError(f"OpenRouter call failed after {MAX_RETRIES + 1} attempts: {last_error}")


def _parse_json_response(content: str) -> dict:
    content = content.strip()

    if content.startswith("```"):
        lines = content.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"raw_response": content}
