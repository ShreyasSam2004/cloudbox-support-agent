"""Build LLM providers from configuration.

Deployed environments use Azure-hosted models (enforced in settings):

* ``anthropic_foundry`` — Claude on Microsoft Foundry (``AsyncAnthropicFoundry``), Entra ID auth.
* ``azure_openai`` — Azure OpenAI deployments (``AsyncAzureOpenAI``), Entra ID auth.

``anthropic`` / ``openai`` (direct APIs) and ``ollama`` (local) remain available for development.
"""

from __future__ import annotations

from typing import Literal

from backend.config.settings import LLMProviderName, Settings
from backend.models.base import LLMProvider

Role = Literal["agent", "evaluator", "judge"]


def _require(value: str | None, name: str) -> str:
    if not value:
        raise ValueError(f"{name} must be set for this provider")
    return value


def _secret(value: object | None) -> str | None:
    get = getattr(value, "get_secret_value", None)
    return get() if callable(get) else None


def build_provider(settings: Settings, provider: LLMProviderName, model: str) -> LLMProvider:
    if provider == "anthropic_foundry":
        import anthropic

        from backend.models.anthropic_provider import AnthropicProvider
        from backend.models.azure_auth import token_provider

        api_key = _secret(settings.anthropic_foundry_api_key) if settings.azure_auth == "api_key" else None
        client = anthropic.AsyncAnthropicFoundry(
            resource=settings.anthropic_foundry_resource,
            api_key=api_key,
            azure_ad_token_provider=None
            if api_key
            else token_provider(settings.azure_token_scope, settings.azure_client_id),
            timeout=settings.llm_timeout_s,
            max_retries=settings.llm_max_retries,
        )
        return AnthropicProvider(model, platform="foundry", client=client)

    if provider == "azure_openai":
        import openai

        from backend.models.azure_auth import token_provider
        from backend.models.openai_provider import OpenAIProvider

        api_key = _secret(settings.azure_openai_api_key) if settings.azure_auth == "api_key" else None
        azure_client = openai.AsyncAzureOpenAI(
            azure_endpoint=_require(settings.azure_openai_endpoint, "AZURE_OPENAI_ENDPOINT"),
            api_version=settings.azure_openai_api_version,
            api_key=api_key,
            azure_ad_token_provider=None
            if api_key
            else token_provider(settings.azure_token_scope, settings.azure_client_id),
            timeout=settings.llm_timeout_s,
            max_retries=settings.llm_max_retries,
        )
        # For Azure OpenAI the "model" is the deployment name.
        return OpenAIProvider(model, None, client=azure_client, name="azure_openai")

    if provider == "anthropic":
        from backend.models.anthropic_provider import AnthropicProvider

        return AnthropicProvider(
            model,
            _secret(settings.anthropic_api_key),
            timeout_s=settings.llm_timeout_s,
            max_retries=settings.llm_max_retries,
            refusal_fallback=settings.anthropic_refusal_fallback,
        )
    if provider == "openai":
        from backend.models.openai_provider import OpenAIProvider

        return OpenAIProvider(
            model,
            _secret(settings.openai_api_key),
            base_url=settings.openai_base_url,
            timeout_s=settings.llm_timeout_s,
            max_retries=settings.llm_max_retries,
        )
    if provider == "ollama":
        from backend.models.ollama_provider import OllamaProvider

        return OllamaProvider(
            model,
            base_url=settings.ollama_base_url,
            num_ctx=settings.ollama_num_ctx,
            keep_alive=settings.ollama_keep_alive,
            think=settings.ollama_think,
            timeout_s=max(settings.llm_timeout_s, 300.0),
        )
    raise ValueError(f"provider {provider!r} cannot be built from settings (scripted is test-only)")


def build_llm(settings: Settings, role: Role = "agent") -> LLMProvider:
    if role == "agent":
        return build_provider(settings, settings.llm_provider, settings.agent_model)
    if role == "evaluator":
        return build_provider(
            settings, settings.effective_evaluator_provider, settings.effective_evaluator_model
        )
    provider = settings.judge_provider or settings.llm_provider
    model = settings.judge_model or settings.agent_model
    return build_provider(settings, provider, model)
