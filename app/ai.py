"""One place that talks to the AI models (Groq). Every call returns JSON validated against a pydantic model."""
from __future__ import annotations

import json
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


def ask_with_backup(models: list[str], *args, **kwargs):
    """Try each model in turn when one has hit its usage limit. Returns (model used, result)."""
    from groq import RateLimitError
    for i, model in enumerate(models):
        try:
            return model, ask(model, *args, **kwargs)
        except RateLimitError as e:
            if i == len(models) - 1:
                m = re.search(r"try again in ([\dhms.]+)", str(e))
                raise UsageLimit("The AI service's free usage limit is reached" + (f"; try again in about {m.group(1).split('.')[0]}s." if m else ".")) from None


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
