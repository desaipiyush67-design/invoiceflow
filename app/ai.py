"""One place that talks to the AI models (Groq). Every call returns JSON validated against a pydantic model."""
from __future__ import annotations

import json
import time
import re
from typing import TypeVar

from groq import BadRequestError
from pydantic import BaseModel, ValidationError

from . import config

T = TypeVar("T", bound=BaseModel)
_client = None


def client():
    global _client
    if _client is None:
        from groq import Groq
        _client = Groq(api_key=config.GROQ_API_KEY, timeout=90, max_retries=4)  # retries cover rate limits (429)
    return _client


def _json_from(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("model returned no JSON")
    return json.loads(m.group(0))


class UsageLimit(RuntimeError):
    """The AI provider refused because a usage limit was reached."""


def _wait_seconds(error: Exception) -> float | None:
    """Groq says how long to wait ("try again in 1m2.5s"). None if it doesn't say."""
    m = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", str(error))
    if not m or not any(m.groups()):
        return None
    h, mins, s = (float(x) if x else 0.0 for x in m.groups())
    return h * 3600 + mins * 60 + s


def ask_with_backup(models: list[str], *args, **kwargs):
    """Try each model in turn when one has hit its usage limit. Returns (model used, result).

    A per-minute limit (wait of a minute or less) is simply waited out; a longer wait (the daily limit)
    moves on to the next model, and if every model is limited the run stops with a clear message."""
    from groq import RateLimitError
    wait = None
    for model in models:
        for _ in range(3):
            try:
                return model, ask(model, *args, **kwargs)
            except RateLimitError as e:
                wait = _wait_seconds(e)
                if wait is None or wait > 65:
                    break
                time.sleep(wait + 1)
    hint = f"; try again in about {int(wait // 60)}m{int(wait % 60)}s" if wait else ""
    raise UsageLimit(f"The AI service's free usage limit is reached{hint}.")


def _effort_for(model: str, effort: str) -> str:
    """Models name their thinking settings differently: gpt-oss takes low/medium/high, qwen takes none/default."""
    if model.startswith("qwen/"):
        return "none" if effort == "none" else "default"
    return {"none": "low", "default": "medium"}.get(effort, effort)


def ask(model: str, system: str, user, schema: type[T], attempts: int = 2, effort: str | None = None) -> T:
    """Send one request and parse the reply into `schema`. If the reply doesn't validate, ask once more with the error."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    last_error = None
    for _ in range(attempts):
        kwargs = {"response_format": {"type": "json_object"}} if isinstance(user, str) else {}
        if effort:
            kwargs["reasoning_effort"] = _effort_for(model, effort)
        try:
            r = client().chat.completions.create(model=model, temperature=0, messages=messages, **kwargs)
        except BadRequestError as e:
            if "json_validate_failed" not in str(e):
                raise
            # The provider's JSON check rejected the reply: ask again without it and validate here instead.
            kwargs.pop("response_format", None)
            r = client().chat.completions.create(model=model, temperature=0, messages=messages, **kwargs)
        reply = r.choices[0].message.content
        try:
            return schema.model_validate(_json_from(reply))
        except (ValueError, ValidationError) as e:
            last_error = e
            messages += [{"role": "assistant", "content": reply or ""},
                         {"role": "user", "content": f"That reply was not valid: {str(e)[:500]}. Reply again with only the JSON object."}]
    raise RuntimeError(f"AI reply could not be parsed: {last_error}")
