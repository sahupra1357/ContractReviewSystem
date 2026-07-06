"""Provider implementations + factory.

Default: Anthropic Messages API via the official SDK (honors
ANTHROPIC_BASE_URL — e.g. a local proxy). Production: Amazon Bedrock via the
Mantle client (`anthropic.`-prefixed model ids, in-VPC path per the security
review). Also supported through one OpenAI-compatible client: OpenAI GPT,
NVIDIA Nemotron, Mistral, MiniMax, Kimi (Moonshot), Qwen (DashScope).

NOTE: non-Anthropic default model ids are best-effort placeholders — vendors
rotate catalogs quickly; set CRS_LLM_MODEL_STRONG / CRS_LLM_MODEL_FAST
explicitly for those providers.
"""

import time

import httpx

from backend.config import get_settings
from backend.llm.base import LLMResponse, Tier

# tier defaults per provider (strong = legal analysis, fast = extraction)
PROVIDER_MODELS: dict[str, dict[Tier, str]] = {
    "anthropic": {"strong": "claude-opus-4-8", "fast": "claude-haiku-4-5"},
    "bedrock": {"strong": "anthropic.claude-opus-4-8", "fast": "anthropic.claude-haiku-4-5"},
    "openai": {"strong": "gpt-4o", "fast": "gpt-4o-mini"},
    "nvidia": {"strong": "nvidia/llama-3.1-nemotron-70b-instruct",
               "fast": "nvidia/llama-3.1-nemotron-70b-instruct"},
    "mistral": {"strong": "mistral-large-latest", "fast": "mistral-small-latest"},
    "minimax": {"strong": "MiniMax-Text-01", "fast": "MiniMax-Text-01"},
    "kimi": {"strong": "kimi-k2-0711-preview", "fast": "moonshot-v1-8k"},
    "qwen": {"strong": "qwen-max", "fast": "qwen-turbo"},
}

# OpenAI-compatible chat-completions base URLs
OPENAI_COMPAT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "mistral": "https://api.mistral.ai/v1",
    "minimax": "https://api.minimax.io/v1",
    "kimi": "https://api.moonshot.ai/v1",
    "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
}


class _TierModels:
    def __init__(self, provider: str) -> None:
        settings = get_settings()
        defaults = PROVIDER_MODELS[provider]
        self._models: dict[Tier, str] = {
            "strong": settings.llm_model_strong or defaults["strong"],
            "fast": settings.llm_model_fast or defaults["fast"],
        }

    def resolve(self, tier: Tier) -> str:
        return self._models[tier]


class AnthropicClient:
    provider = "anthropic"

    def __init__(self) -> None:
        import anthropic

        settings = get_settings()
        kwargs: dict = {}
        if settings.llm_api_key:
            kwargs["api_key"] = settings.llm_api_key
        if settings.llm_base_url:
            kwargs["base_url"] = settings.llm_base_url
        # otherwise the SDK resolves ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN /
        # an `ant auth login` profile, and honors ANTHROPIC_BASE_URL
        self._client = anthropic.Anthropic(**kwargs)
        self._models = _TierModels(self.provider)

    def complete(self, *, system: str, prompt: str, tier: Tier = "strong",
                 max_tokens: int = 4096) -> LLMResponse:
        model = self._models.resolve(tier)
        started = time.monotonic()
        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        return LLMResponse(
            text=text,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=int((time.monotonic() - started) * 1000),
        )


class BedrockClient:
    """Amazon Bedrock via the Mantle client — the production in-VPC path."""

    provider = "bedrock"

    def __init__(self) -> None:
        from anthropic import AnthropicBedrockMantle  # needs anthropic[bedrock]

        settings = get_settings()
        self._client = AnthropicBedrockMantle(aws_region=settings.aws_region)
        self._models = _TierModels(self.provider)

    def complete(self, *, system: str, prompt: str, tier: Tier = "strong",
                 max_tokens: int = 4096) -> LLMResponse:
        model = self._models.resolve(tier)
        started = time.monotonic()
        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        return LLMResponse(
            text=text,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=int((time.monotonic() - started) * 1000),
        )


class OpenAICompatClient:
    """One client for every OpenAI-compatible chat-completions provider."""

    def __init__(self, provider: str) -> None:
        settings = get_settings()
        self.provider = provider
        self._base_url = settings.llm_base_url or OPENAI_COMPAT_BASE_URLS[provider]
        self._api_key = settings.llm_api_key
        if not self._api_key:
            raise ValueError(f"CRS_LLM_API_KEY is required for provider {provider!r}")
        self._models = _TierModels(provider)

    def complete(self, *, system: str, prompt: str, tier: Tier = "strong",
                 max_tokens: int = 4096) -> LLMResponse:
        model = self._models.resolve(tier)
        started = time.monotonic()
        response = httpx.post(
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": model,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=300.0,
        )
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage") or {}
        return LLMResponse(
            text=data["choices"][0]["message"]["content"],
            model=data.get("model", model),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            latency_ms=int((time.monotonic() - started) * 1000),
        )


def get_llm_client():
    provider = get_settings().llm_provider
    if provider == "anthropic":
        return AnthropicClient()
    if provider == "bedrock":
        return BedrockClient()
    if provider in OPENAI_COMPAT_BASE_URLS:
        return OpenAICompatClient(provider)
    raise ValueError(
        f"unknown CRS_LLM_PROVIDER {provider!r}; supported: anthropic, bedrock, "
        + ", ".join(OPENAI_COMPAT_BASE_URLS)
    )
