"""Composition root: builds every component from settings (with test overrides).

Only this module knows which concrete implementation backs each interface. The agent sees tools;
tools see repositories/retrievers; nothing above the storage layer knows about SQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time

import asyncpg

from backend.agent.loop import AgentRunner
from backend.agent.prompts import build_static_prompt
from backend.common.clock import Clock, FixedClock, SystemClock
from backend.config.settings import Settings
from backend.models.base import LLMProvider
from backend.models.factory import build_llm
from backend.models.metered import MeteredLLM
from backend.observability.logging import get_logger
from backend.retrieval.embeddings import Embedder, build_embedder
from backend.retrieval.evaluator import RetrievalEvaluator
from backend.retrieval.retriever import Retriever
from backend.retrieval.vector_store import InMemoryVectorStore, VectorStore
from backend.security.auth import Authenticator
from backend.security.rate_limit import SlidingWindowRateLimiter
from backend.storage.customers import CustomerRepository, JsonCustomerRepository, PostgresCustomerRepository
from backend.storage.sessions import InMemorySessionStore, PostgresSessionStore, SessionStore
from backend.storage.traces import InMemoryTraceStore, PostgresTraceStore, TraceStore
from backend.tools.customer_account import GetCustomerAccountTool
from backend.tools.knowledge_base import SearchKnowledgeBaseTool
from backend.tools.registry import ToolRegistry
from backend.tools.web_providers import (
    DisabledWebSearchProvider,
    FixtureWebSearchProvider,
    TavilyWebSearchProvider,
    WebSearchProvider,
)
from backend.tools.web_search import WebSearchTool

log = get_logger(__name__)


def build_clock(settings: Settings) -> Clock:
    if settings.agent_current_date is not None:
        return FixedClock(datetime.combine(settings.agent_current_date, time(12, 0), tzinfo=UTC))
    return SystemClock()


def build_web_provider(settings: Settings) -> WebSearchProvider:
    if settings.web_search_provider == "fixture":
        return FixtureWebSearchProvider(settings.data_dir / "web_fixtures" / "pages.json")
    if settings.web_search_provider == "tavily" and settings.tavily_api_key is not None:
        return TavilyWebSearchProvider(settings.tavily_api_key.get_secret_value())
    return DisabledWebSearchProvider()


@dataclass
class Container:
    settings: Settings
    clock: Clock
    llm: LLMProvider
    evaluator_llm: LLMProvider | None
    embedder: Embedder
    store: VectorStore
    retriever: Retriever
    evaluator: RetrievalEvaluator
    registry: ToolRegistry
    agent: AgentRunner
    sessions: SessionStore
    customers: CustomerRepository
    traces: TraceStore
    authenticator: Authenticator
    rate_limiter: SlidingWindowRateLimiter
    pool: asyncpg.Pool | None = None

    @classmethod
    async def create(
        cls,
        settings: Settings,
        *,
        llm: LLMProvider | None = None,
        evaluator_llm: LLMProvider | None = None,
        embedder: Embedder | None = None,
        store: VectorStore | None = None,
        web_provider: WebSearchProvider | None = None,
        clock: Clock | None = None,
    ) -> Container:
        pool: asyncpg.Pool | None = None
        needs_db = "postgres" in (settings.session_store, settings.customer_store, settings.trace_store) or (
            store is None and settings.vector_store == "pgvector"
        )
        if needs_db:
            from backend.storage.db import create_pool_from_settings, run_migrations

            pool = await create_pool_from_settings(settings)
            await run_migrations(pool)

        if store is None:
            if settings.vector_store == "pgvector":
                from backend.retrieval.pgvector_store import PgVectorStore

                assert pool is not None
                store = PgVectorStore(pool)
            else:
                store = InMemoryVectorStore(settings.memory_index_path)

        customers: CustomerRepository
        if settings.customer_store == "postgres":
            assert pool is not None
            customers = PostgresCustomerRepository(pool)
        else:
            customers = JsonCustomerRepository(settings.data_dir / "customers" / "customers.json")
        sessions: SessionStore = (
            PostgresSessionStore(pool)
            if settings.session_store == "postgres" and pool
            else InMemorySessionStore()
        )
        traces: TraceStore = (
            PostgresTraceStore(pool) if settings.trace_store == "postgres" and pool else InMemoryTraceStore()
        )

        embedder = embedder or build_embedder(settings)
        await store.ensure_index(embedder.model, embedder.dim)
        retriever = Retriever(
            store,
            embedder,
            mode=settings.retrieval_mode,
            candidate_k=settings.retrieval_candidate_k,
            rrf_k=settings.rrf_k,
            lexical_weight=settings.retrieval_lexical_weight,
        )

        agent_llm: LLMProvider = MeteredLLM(llm or build_llm(settings, "agent"))
        if evaluator_llm is not None:
            eval_llm: LLMProvider | None = MeteredLLM(evaluator_llm)
        elif llm is not None:
            eval_llm = agent_llm  # tests: share the injected provider
        elif (settings.effective_evaluator_provider, settings.effective_evaluator_model) == (
            settings.llm_provider,
            settings.agent_model,
        ):
            eval_llm = agent_llm
        else:
            eval_llm = MeteredLLM(build_llm(settings, "evaluator"))
        evaluator = RetrievalEvaluator(
            eval_llm,
            enabled=settings.retrieval_evaluator_enabled,
            effort=settings.evaluator_effort,
            passage_chars=settings.observation_chunk_chars,
        )

        registry = ToolRegistry(
            [
                SearchKnowledgeBaseTool(
                    retriever,
                    evaluator,
                    chunk_chars=settings.observation_chunk_chars,
                    default_top_k=settings.retrieval_top_k,
                    rerank_pool=settings.retrieval_rerank_pool,
                ),
                WebSearchTool(
                    web_provider or build_web_provider(settings),
                    blocked_domains=settings.web_search_blocked_domains,
                ),
                GetCustomerAccountTool(customers),
            ],
            default_timeout_s=settings.tool_timeout_s,
            max_attempts=settings.tool_max_attempts,
        )
        catalog = await store.list_documents()
        clock = clock or build_clock(settings)
        agent = AgentRunner(agent_llm, registry, settings, clock, build_static_prompt(catalog))
        log.info(
            "container.ready",
            llm_provider=agent_llm.name,
            model=agent_llm.model,
            vector_store=type(store).__name__,
            documents=len(catalog),
        )
        return cls(
            settings=settings,
            clock=clock,
            llm=agent_llm,
            evaluator_llm=eval_llm,
            embedder=embedder,
            store=store,
            retriever=retriever,
            evaluator=evaluator,
            registry=registry,
            agent=agent,
            sessions=sessions,
            customers=customers,
            traces=traces,
            authenticator=Authenticator(settings),
            rate_limiter=SlidingWindowRateLimiter(settings.rate_limit_per_minute),
            pool=pool,
        )

    async def aclose(self) -> None:
        await self.llm.aclose()
        if self.evaluator_llm is not None and self.evaluator_llm is not self.llm:
            await self.evaluator_llm.aclose()
        await self.embedder.aclose()
        if self.pool is not None:
            await self.pool.close()
