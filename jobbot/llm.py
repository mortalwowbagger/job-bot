"""LLM client returning structured JSON. Default provider: Claude (Anthropic API).

Claude: structured outputs (output_config.format = our JSON schema), so the reply
text is guaranteed to be JSON matching the schema. (Forced tool calls were used
before, but newer models such as Sonnet 5.5 reject tool_choice "tool".)
Grok is kept as an alternative (`provider: grok` in config.yaml).

Set JOBBOT_FAKE_LLM=1 to get canned responses (tests / dry runs, no cost).
"""
import json
import os
import time

import requests

PROVIDER = "claude"  # overwritten from config.yaml by cli.py


class LLMError(RuntimeError):
    pass


class FatalLLMError(LLMError):
    """Auth/config problems - retrying won't help."""


class RefusalError(LLMError):
    """Model declined this request - skip the job, don't retry."""


def _post(url, headers, body):
    try:
        r = requests.post(url, json=body, headers=headers, timeout=180)
    except requests.RequestException as e:
        raise LLMError(f"network error: {e}") from e
    if r.status_code in (429, 529) or r.status_code >= 500:
        raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
    if r.status_code >= 400:
        raise FatalLLMError(f"HTTP {r.status_code}: {r.text[:500]}")
    return r.json()


def _claude(model, system, user, schema, name):
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise FatalLLMError("ANTHROPIC_API_KEY is not set. Add it to .env (see .env.example).")
    base = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    body = {
        "model": model,
        "max_tokens": 16000,  # room for adaptive thinking on newer models
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "output_config": {"format": {"type": "json_schema", "schema": schema}},
    }
    data = _post(f"{base}/v1/messages",
                 {"x-api-key": key, "anthropic-version": "2023-06-01"}, body)
    stop = data.get("stop_reason")
    if stop == "refusal":
        raise RefusalError(f"model declined ({(data.get('stop_details') or {}).get('category')})")
    if stop == "max_tokens":
        raise LLMError("reply was cut off at max_tokens")
    text = next((b.get("text") for b in data.get("content", []) if b.get("type") == "text"), None)
    try:
        out = json.loads(text)
    except (TypeError, json.JSONDecodeError) as e:
        raise LLMError(f"no structured output in reply (stop_reason={stop}): {e}") from e
    u = data.get("usage", {})
    out["_usage"] = {"total_tokens": u.get("input_tokens", 0) + u.get("output_tokens", 0)}
    return out


def _grok(model, system, user, schema, name):
    key = os.getenv("XAI_API_KEY")
    if not key:
        raise FatalLLMError("XAI_API_KEY is not set. Add it to .env (see .env.example).")
    base = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1").rstrip("/")
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": name, "schema": schema, "strict": True}},
    }
    data = _post(f"{base}/chat/completions", {"Authorization": f"Bearer {key}"}, body)
    try:
        out = json.loads(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise LLMError(f"bad reply: {e}") from e
    out["_usage"] = data.get("usage", {})
    return out


def chat_json(model, system, user, schema, name="result", retries=3):
    if os.getenv("JOBBOT_FAKE_LLM") == "1":
        from . import fake_llm
        return fake_llm.respond(name, user)

    call = {"claude": _claude, "grok": _grok}.get(PROVIDER)
    if call is None:
        raise FatalLLMError(f"Unknown provider {PROVIDER!r} (use claude or grok)")
    last = None
    for attempt in range(retries + 1):
        try:
            return call(model, system, user, schema, name)
        except (FatalLLMError, RefusalError):
            raise
        except LLMError as e:
            last = e
            time.sleep(min(30, 3 * 2 ** attempt))
    raise LLMError(f"{PROVIDER} call failed after {retries + 1} tries: {last}")
