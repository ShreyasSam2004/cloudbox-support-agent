"""Operational CLI.

cloudbox ingest [--source data/knowledge_base] [--force]   index the knowledge base
cloudbox seed-customers                                    load mock accounts into Postgres
cloudbox chat [--customer C1002]                           interactive local chat with the agent
cloudbox prune [--days 30]                                 delete old sessions and traces
cloudbox eval ...                                          run the benchmark (see backend.evaluation.run)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import timedelta
from pathlib import Path

from backend.config.settings import get_settings
from backend.observability.logging import configure_logging


async def _ingest(source: Path, force: bool) -> int:
    from backend.retrieval.embeddings import build_embedder
    from backend.retrieval.ingestion import IngestionPipeline
    from backend.retrieval.vector_store import InMemoryVectorStore, VectorStore

    settings = get_settings()
    embedder = build_embedder(settings)
    pool = None
    store: VectorStore
    if settings.vector_store == "pgvector":
        from backend.retrieval.pgvector_store import PgVectorStore
        from backend.storage.db import create_pool_from_settings, run_migrations

        if settings.database_url is None:
            print("DATABASE_URL is required for VECTOR_STORE=pgvector", file=sys.stderr)
            return 2
        pool = await create_pool_from_settings(settings)
        await run_migrations(pool)
        store = PgVectorStore(pool)
    else:
        store = InMemoryVectorStore(settings.memory_index_path)
    try:
        report = await IngestionPipeline(
            store, embedder, max_chars=settings.chunk_max_chars
        ).ingest_directory(source, force=force)
    finally:
        await embedder.aclose()
        if pool is not None:
            await pool.close()
    print(json.dumps(report.__dict__, indent=2))
    return 1 if report.errors else 0


async def _seed_customers() -> int:
    from backend.storage.customers import JsonCustomerRepository, PostgresCustomerRepository
    from backend.storage.db import create_pool_from_settings, run_migrations

    settings = get_settings()
    if settings.database_url is None:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2
    pool = await create_pool_from_settings(settings)
    try:
        await run_migrations(pool)
        accounts = JsonCustomerRepository(settings.data_dir / "customers" / "customers.json").all()
        count = await PostgresCustomerRepository(pool).upsert_many(accounts)
    finally:
        await pool.close()
    print(f"seeded {count} customers")
    return 0


async def _chat(customer_id: str | None) -> int:
    from backend.container import Container
    from backend.security.auth import Principal
    from backend.storage.sessions import Session

    settings = get_settings()
    container = await Container.create(settings)
    principal = Principal(subject="cli", customer_id=customer_id, authenticated=False)
    session = Session(session_id=uuid.uuid4().hex, owner="cli", bound_customer_id=customer_id)
    print("CloudBox support agent — type 'exit' to quit.")
    try:
        while True:
            try:
                message = (await asyncio.to_thread(input, "\nyou> ")).strip()
            except EOFError:
                break
            if message.lower() in ("exit", "quit"):
                break
            if not message:
                continue
            session.add_user_turn(message)
            result = await container.agent.run(session=session, principal=principal, user_message=message)
            print(f"\n[{' -> '.join(result.trace.trajectory())}]")
            print(f"agent ({result.response_type})> {result.answer}")
            for source in result.sources:
                where = source.section or source.url or ""
                print(f"  [{source.evidence_id}] {source.origin.value}: {source.title} — {where}")
    finally:
        await container.aclose()
    return 0


async def _prune(days: int) -> int:
    from backend.container import Container

    container = await Container.create(get_settings())
    try:
        sessions = await container.sessions.prune(timedelta(days=days))
        traces = await container.traces.prune(timedelta(days=days))
    finally:
        await container.aclose()
    print(f"pruned {sessions} sessions and {traces} traces older than {days} days")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cloudbox")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="index the knowledge base")
    ingest.add_argument("--source", type=Path, default=None)
    ingest.add_argument("--force", action="store_true")
    sub.add_parser("seed-customers", help="load mock customer accounts into Postgres")
    chat = sub.add_parser("chat", help="interactive chat")
    chat.add_argument("--customer", default=None)
    prune = sub.add_parser("prune", help="delete old sessions/traces")
    prune.add_argument("--days", type=int, default=30)
    sub.add_parser("eval", help="run the benchmark", add_help=False)

    args, rest = parser.parse_known_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    if args.command == "ingest":
        return asyncio.run(_ingest(args.source or settings.data_dir / "knowledge_base", args.force))
    if args.command == "seed-customers":
        return asyncio.run(_seed_customers())
    if args.command == "chat":
        return asyncio.run(_chat(args.customer.upper() if args.customer else None))
    if args.command == "prune":
        return asyncio.run(_prune(args.days))
    from backend.evaluation.run import main as eval_main

    return eval_main(rest)


if __name__ == "__main__":
    raise SystemExit(main())
