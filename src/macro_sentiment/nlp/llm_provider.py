"""LLM sağlayıcı soyutlaması — gerçek (Anthropic) + mock (test/çevrimdışı).

LLMSentiment bu protokole bağımlıdır; somut sağlayıcıya değil. Böylece ağ
gerektiren gerçek çağrı ile deterministik test mock'u yer değiştirebilir.
"""
from __future__ import annotations

import json
import logging
from typing import Callable, Protocol, runtime_checkable

log = logging.getLogger(__name__)


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    async def complete_json(self, system: str, user: str) -> dict:
        """Sistem+kullanıcı promptunu çalıştırıp JSON nesnesi döndürür."""
        ...


def _extract_json(text: str) -> dict:
    """Model çıktısından JSON gövdesini ayıklar (kod çiti / önek-sonek toleranslı)."""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{"):]
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("JSON bulunamadı")
    return json.loads(t[start : end + 1])


class AnthropicProvider:
    """Gerçek Anthropic sağlayıcısı (ağ gerekir). anthropic SDK tembel import edilir."""

    name = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6", max_tokens: int = 512) -> None:
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens

    async def complete_json(self, system: str, user: str) -> dict:
        from anthropic import AsyncAnthropic  # ağır/opsiyonel import

        client = AsyncAnthropic(api_key=self.api_key)
        resp = await client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return _extract_json(resp.content[0].text)


class MockLLMProvider:
    """Deterministik test sağlayıcısı. canned bir dict ya da (system,user)->dict fonksiyonu."""

    name = "mock"

    def __init__(self, canned: dict | Callable[[str, str], dict]) -> None:
        self.canned = canned

    async def complete_json(self, system: str, user: str) -> dict:
        return self.canned(system, user) if callable(self.canned) else dict(self.canned)


def build_provider(settings) -> LLMProvider | None:
    """Config'e göre sağlayıcı kurar; anahtar yoksa None (LLM devre dışı)."""
    if not settings.llm_api_key:
        return None
    if settings.llm_provider == "anthropic":
        return AnthropicProvider(settings.llm_api_key, model=settings.llm_model)
    log.warning("Bilinmeyen LLM sağlayıcı: %s", settings.llm_provider)
    return None
