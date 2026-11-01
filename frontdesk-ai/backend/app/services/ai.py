"""LLM access with guardrails. The model only produces a JSON reply; it never performs actions."""
import json
import logging
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import get_settings

log = logging.getLogger("app.ai")
T = TypeVar("T", bound=BaseModel)
_TAG_RE = re.compile(r"</?\s*(visitor|business|untrusted)[^>]*>", re.IGNORECASE)


def sanitize(text: str, limit: int = 4000) -> str:
    """Neutralise our delimiter tags so content can't break out of its section."""
    return _TAG_RE.sub("[tag removed]", text or "")[:limit]


def _extract_json(text: str) -> str | None:
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else None


class AIClient:
    def __init__(self) -> None:
        s = get_settings()
        self._client = None
        self._model = s.anthropic_model
        if s.anthropic_api_key:
            from anthropic import Anthropic

            self._client = Anthropic(api_key=s.anthropic_api_key, timeout=s.ai_timeout_seconds, max_retries=2)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def chat_json(self, system: str, messages: list[dict], schema: type[T], max_tokens: int = 800) -> T | None:
        if not self.enabled:
            return None
        system = f"{system}\n\nRespond with ONE JSON object matching this schema and nothing else:\n" \
                 f"{json.dumps(schema.model_json_schema())}"
        try:
            resp = self._client.messages.create(model=self._model, max_tokens=max_tokens, system=system,
                                                messages=messages)
            raw = _extract_json("".join(getattr(b, "text", "") for b in resp.content))
            return schema.model_validate_json(raw) if raw else None
        except ValidationError:
            log.warning("AI output failed schema validation")
            return None
        except Exception as exc:  # network / API errors -> deterministic fallback
            log.warning("AI call failed: %s", type(exc).__name__)
            return None


_client: AIClient | None = None


def get_ai() -> AIClient:
    global _client
    if _client is None:
        _client = AIClient()
    return _client
