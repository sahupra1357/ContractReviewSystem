"""Multi-provider LLM adapter — the ONLY path to any model (design §3.5).

Providers are selected by configuration, never hardcoded. Only MASKED text
may be passed to these clients (invariant #1 — applies to every provider).
Tiered routing: `tier="strong"` for legal analysis, `tier="fast"` for
classification/extraction; each provider maps tiers to its own models.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

Tier = Literal["strong", "fast"]


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int


class LLMClient(Protocol):
    provider: str

    def complete(
        self,
        *,
        system: str,
        prompt: str,
        tier: Tier = "strong",
        max_tokens: int = 4096,
    ) -> LLMResponse: ...
