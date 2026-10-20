"""Environment-based configuration.

Every value can be set through an environment variable of the same name (case-insensitive) or a
local ``.env`` file. Secrets are typed as ``SecretStr`` so they never appear in logs or reprs.
Production safety rules are enforced at startup in :meth:`Settings._production_guards`.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "dev", "staging", "prod"]
LLMProviderName = Literal["anthropic_foundry", "azure_openai", "anthropic", "openai", "ollama", "scripted"]
EmbeddingProviderName = Literal["azure_openai", "ollama", "openai", "voyage", "hashing"]

# Local-only / test-only providers that deployed environments (staging/prod) must not use.
NON_DEPLOYABLE_LLM_PROVIDERS = ("ollama", "scripted")
NON_DEPLOYABLE_EMBEDDING_PROVIDERS = ("ollama", "hashing")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ service
    environment: Environment = "local"
    service_name: str = "cloudbox-support-agent"
    log_level: str = "INFO"
    log_json: bool = True
    data_dir: Path = Path("data")

    # ------------------------------------------------------------------ LLM
    llm_provider: LLMProviderName = "anthropic"
    agent_model: str = "claude-sonnet-5-5"
    agent_effort: str | None = Field(
        default="medium", description="Anthropic output_config.effort for the agent loop."
    )
    agent_max_output_tokens: int = 16000
    evaluator_provider: LLMProviderName | None = None  # defaults to llm_provider
    evaluator_model: str | None = None  # defaults to agent_model
    evaluator_effort: str | None = "low"
    judge_provider: LLMProviderName | None = None  # offline evaluation only
    judge_model: str | None = None
    llm_timeout_s: float = 90.0
    llm_max_retries: int = 2

    # Azure (managed identity is the default auth; API keys are a local-dev fallback)
    azure_auth: Literal["managed_identity", "api_key"] = "managed_identity"
    azure_client_id: str | None = Field(
        default=None, description="Client ID of the user-assigned managed identity (AZURE_CLIENT_ID)."
    )
    azure_token_scope: str = "https://cognitiveservices.azure.com/.default"  # noqa: S105 - OAuth scope, not a secret
    anthropic_foundry_resource: str | None = None
    anthropic_foundry_api_key: SecretStr | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_api_key: SecretStr | None = None

    anthropic_api_key: SecretStr | None = None
    anthropic_refusal_fallback: bool = True
    openai_api_key: SecretStr | None = None
    openai_base_url: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    ollama_num_ctx: int = 8192
    ollama_keep_alive: str = "30m"
    ollama_think: bool | None = Field(
        default=None, description="Send `think` to Ollama (False disables reasoning on qwen3-style models)."
    )

    # ------------------------------------------------------------------ embeddings
    embedding_provider: EmbeddingProviderName = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    voyage_api_key: SecretStr | None = None

    # ------------------------------------------------------------------ storage
    vector_store: Literal["pgvector", "memory"] = "pgvector"
    session_store: Literal["postgres", "memory"] = "postgres"
    customer_store: Literal["postgres", "json"] = "postgres"
    trace_store: Literal["postgres", "memory"] = "postgres"
    database_url: SecretStr | None = None
    database_auth: Literal["password", "entra"] = Field(
        default="password",
        description="entra = passwordless: the managed identity's Entra token is the Postgres password.",
    )
    database_token_scope: str = "https://ossrdbms-aad.database.windows.net/.default"  # noqa: S105 - OAuth scope
    db_pool_min: int = 1
    db_pool_max: int = 10
    memory_index_path: Path = Path(".data/kb_index.json")

    # ------------------------------------------------------------------ retrieval
    retrieval_mode: Literal["hybrid", "vector"] = "hybrid"
    retrieval_top_k: int = Field(default=4, ge=1, le=10)  # measured: reports/retrieval/report.md
    retrieval_candidate_k: int = Field(default=20, ge=5, le=100)
    rrf_k: int = 60
    retrieval_lexical_weight: float = Field(
        default=1.0, ge=0.0, le=2.0, description="Weight of keyword (BM25) results in hybrid fusion."
    )
    retrieval_rerank_pool: int = Field(
        default=20,
        ge=0,
        le=30,
        description="Candidates the retrieval evaluator re-ranks per search (0 or <= top_k disables re-ranking).",
    )
    retrieval_evaluator_enabled: bool = True
    observation_chunk_chars: int = Field(
        default=2000, description="Max characters of each passage shown to the agent and the evaluator."
    )
    chunk_max_chars: int = Field(default=1600, ge=200, le=8000, description="Chunker size limit (ingestion).")

    # ------------------------------------------------------------------ agent
    max_agent_steps: int = Field(default=8, ge=1, le=25)
    max_tool_calls: int = Field(default=12, ge=1, le=50)
    agent_timeout_s: float = 180.0
    tool_timeout_s: float = 30.0
    tool_max_attempts: int = 3
    citation_guardrail_enabled: bool = True
    context_max_turns: int = 6
    agent_current_date: date | None = Field(
        default=None, description="Pin the agent's 'today' (reproducible evaluation)."
    )

    # ------------------------------------------------------------------ web search
    web_search_provider: Literal["tavily", "fixture", "disabled"] = "fixture"
    tavily_api_key: SecretStr | None = None
    web_search_max_results: int = 4
    web_search_blocked_domains: list[str] = Field(default_factory=list)

    # ------------------------------------------------------------------ security
    auth_mode: Literal["none", "jwt"] = "none"
    jwt_jwks_url: str | None = None
    jwt_hs256_secret: SecretStr | None = None
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    jwt_customer_claim: str = "customer_id"
    allow_unverified_customer_lookup: bool = Field(
        default=True,
        description="Demo mode: allow account lookups for customer IDs the user typed in chat.",
    )
    rate_limit_per_minute: int = 30
    trust_forwarded_for: bool = False
    front_door_id: str | None = Field(
        default=None,
        description="Azure Front Door profile ID; when set, API requests must carry a matching X-Azure-FDID.",
    )
    cors_allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    admin_api_key: SecretStr | None = None
    max_message_chars: int = 4000
    max_request_bytes: int = 32_768

    # ------------------------------------------------------------------ observability
    applicationinsights_connection_string: SecretStr | None = None
    expose_trace_in_response: bool = True

    # ------------------------------------------------------------------ derived
    @property
    def effective_evaluator_provider(self) -> LLMProviderName:
        return self.evaluator_provider or self.llm_provider

    @property
    def effective_evaluator_model(self) -> str:
        return self.evaluator_model or self.agent_model

    @property
    def is_production(self) -> bool:
        return self.environment == "prod"

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        """Refuse to boot production with demo-grade settings."""
        if self.environment not in ("staging", "prod"):
            return self
        problems: list[str] = []
        if self.environment == "prod":
            if self.auth_mode == "none":
                problems.append("AUTH_MODE=none is not allowed in prod")
            if self.allow_unverified_customer_lookup:
                problems.append("ALLOW_UNVERIFIED_CUSTOMER_LOOKUP must be false in prod")
            if self.web_search_provider == "fixture":
                problems.append("WEB_SEARCH_PROVIDER=fixture is a test double")
            if self.jwt_hs256_secret is not None:
                problems.append("JWT_HS256_SECRET is for local testing; use JWKS in prod")
        for name, value in (
            ("LLM_PROVIDER", self.llm_provider),
            ("EVALUATOR_PROVIDER", self.effective_evaluator_provider),
        ):
            if value in NON_DEPLOYABLE_LLM_PROVIDERS:
                problems.append(f"{name}={value} is local/test-only; use a hosted model API")
        if self.embedding_provider in NON_DEPLOYABLE_EMBEDDING_PROVIDERS:
            problems.append(f"EMBEDDING_PROVIDER={self.embedding_provider} is local/test-only")
        if "memory" in (self.vector_store, self.session_store, self.trace_store):
            problems.append("in-memory stores are not allowed outside local/dev/test")
        if problems:
            raise ValueError("Unsafe configuration for " + self.environment + ": " + "; ".join(problems))
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
