"""Live smoke test against the configured model (opt-in: ``LIVE_TESTS=1``).

Asserts properties rather than exact wording: the agent must consult tools, must cite retrieved
evidence, and for a customer-specific question must look at the account.
"""

from __future__ import annotations

import os
import uuid

import pytest

from backend.config.settings import Settings
from backend.container import Container
from backend.security.auth import Principal
from backend.storage.sessions import Session

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("LIVE_TESTS") != "1", reason="LIVE_TESTS!=1"),
]


async def test_live_customer_specific_refund() -> None:
    from datetime import date

    container = await Container.create(
        Settings(
            agent_current_date=date(2026, 10, 9),
            session_store="memory",
            trace_store="memory",
            customer_store="json",
        )
    )
    try:
        question = "I cancelled my subscription but was charged today. Can I get a refund?"
        session = Session(session_id=uuid.uuid4().hex, owner="live", bound_customer_id="C1002")
        session.add_user_turn(question)
        result = await container.agent.run(
            session=session, principal=Principal("live", "C1002", False), user_message=question
        )
        tools = {c.tool for c in result.trace.tool_calls}
        assert "get_customer_account" in tools
        assert "search_knowledge_base" in tools
        assert result.sources, result.answer
    finally:
        await container.aclose()
