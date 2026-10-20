"""Agent integration tests (scripted model, real tools/retrieval/authorization/validation).

The scripted model plays the role of the LLM so each test can pin down one decision path. What is
under test is the runtime: that it executes whatever the model chooses, feeds observations back,
enforces safety boundaries and validates the final reply. Different scripts produce different
trajectories through the *same* code — nothing in the loop prescribes the sequence.
"""

from __future__ import annotations

from typing import Any

from backend.models.base import LLMError, LLMRequest, LLMResponse, Usage
from backend.models.scripted import ScriptedProvider, text_response, tool_response
from backend.tools.web_providers import WebResult
from tests.conftest import (
    anonymous,
    build_container,
    evaluator_says,
    make_settings,
    new_session,
    tool_results_in,
)


def last_observation(request: LLMRequest) -> dict[str, Any]:
    return tool_results_in(request)[-1]


# 1 ------------------------------------------------------------------------------------------------
async def test_relevant_first_retrieval_then_answer(kb_store) -> None:  # type: ignore[no-untyped-def]
    def answer(request: LLMRequest) -> LLMResponse:
        obs = last_observation(request)
        assert obs["retrieval_evaluation"]["relevant"] is True
        eid = obs["results"][0]["evidence_id"]
        return text_response(f"TYPE: answer\nRotate the key in Settings > Developer > API keys [{eid}].")

    container, agent_llm, _ = await build_container(
        kb_store, [tool_response(("search_knowledge_base", {"query": "rotate API key grace period"})), answer]
    )
    session = new_session(None, "How do I reset my API key?")
    result = await container.agent.run(
        session=session, principal=anonymous(), user_message="How do I reset my API key?"
    )

    assert result.trace.trajectory() == ["search_knowledge_base", "answer"]
    assert result.response_type == "answer"
    assert result.sources and result.sources[0].evidence_id == "K1"
    assert result.evidence_summary["grounded"] is True
    assert result.stop_reason == "completed"
    # The tool schemas were offered to the model on every step.
    assert {t.name for t in agent_llm.requests[0].tools} == {
        "search_knowledge_base",
        "web_search",
        "get_customer_account",
    }


# 2 + 3 ---------------------------------------------------------------------------------------------
async def test_poor_retrieval_leads_to_rewritten_queries(kb_store) -> None:  # type: ignore[no-untyped-def]
    seen: list[dict[str, Any]] = []

    def second_search(request: LLMRequest) -> LLMResponse:
        obs = last_observation(request)
        seen.append(obs["retrieval_evaluation"])
        return tool_response(
            ("search_knowledge_base", {"query": "refund eligibility after cancellation renewal charge"})
        )

    def third_search(request: LLMRequest) -> LLMResponse:
        seen.append(last_observation(request)["retrieval_evaluation"])
        return tool_response(
            ("search_knowledge_base", {"query": "charges after cancellation", "document_id": "refund-policy"})
        )

    def answer(request: LLMRequest) -> LLMResponse:
        obs = last_observation(request)
        seen.append(obs["retrieval_evaluation"])
        assert {r["document_id"] for r in obs["results"]} == {"refund-policy"}
        return text_response(f"TYPE: answer\nYou are eligible [{obs['results'][0]['evidence_id']}].")

    evaluator = ScriptedProvider(
        [
            evaluator_says(False, 0.2, "Specific refund eligibility rules", "none"),
            evaluator_says(True, 0.6, "Exact timing rule", "partial"),
            evaluator_says(True, 0.9),
        ]
    )
    container, _, eval_llm = await build_container(
        kb_store,
        [
            tool_response(("search_knowledge_base", {"query": "subscription"})),
            second_search,
            third_search,
            answer,
        ],
        evaluator=evaluator,
    )
    msg = "I cancelled and was charged. Refund?"
    result = await container.agent.run(
        session=new_session(None, msg), principal=anonymous(), user_message=msg
    )

    assert result.trace.trajectory() == ["search_knowledge_base"] * 3 + ["answer"]
    assert seen[0]["relevant"] is False
    assert seen[0]["missing_information"] == "Specific refund eligibility rules"
    assert result.evidence_summary["retrieval_attempts"] == 3
    # The evaluator judged each search against the ORIGINAL customer question.
    assert all(msg in r.messages[0].text for r in eval_llm.requests)


# 4 -------------------------------------------------------------------------------------------------
async def test_kb_gap_leads_to_web_search_with_external_label(kb_store) -> None:  # type: ignore[no-untyped-def]
    def use_web(request: LLMRequest) -> LLMResponse:
        return tool_response(("web_search", {"query": "exponential backoff jitter python retry"}))

    def answer(request: LLMRequest) -> LLMResponse:
        obs = last_observation(request)
        assert obs["source"] == "public_web"
        assert "NOT CloudBox policy" in obs["disclaimer"]
        return text_response("TYPE: answer\nUse full jitter [W1] and honour Retry-After [K1].")

    container, _, _ = await build_container(
        kb_store,
        [tool_response(("search_knowledge_base", {"query": "429 Retry-After backoff"})), use_web, answer],
        evaluator=ScriptedProvider(evaluator_says(True, 0.6, "Python implementation details", "partial")),
    )
    q = "How do I implement backoff with jitter in Python?"
    result = await container.agent.run(session=new_session(None, q), principal=anonymous(), user_message=q)

    assert result.trace.trajectory() == ["search_knowledge_base", "web_search", "answer"]
    origins = {s.origin.value for s in result.sources}
    assert origins == {"public_web", "internal_kb"}
    assert "not official CloudBox policy" in result.answer  # validator enforced the label
    assert result.evidence_summary["web_search_used"] is True


# 5 -------------------------------------------------------------------------------------------------
async def test_customer_specific_question_uses_account(kb_store) -> None:  # type: ignore[no-untyped-def]
    def answer(request: LLMRequest) -> LLMResponse:
        results = tool_results_in(request)
        account = next(r for r in results if "account" in r)
        assert account["account"]["subscription"]["cancel_requested_at"] == "2026-10-07T21:14:00Z"
        assert account["account"]["contact"]["email"] == "m***@brightline-studio.example"
        return text_response(
            "TYPE: answer\nYou cancelled before renewal [A1], so you get a full refund [K1]."
        )

    container, _, _ = await build_container(
        kb_store,
        [
            tool_response(
                ("get_customer_account", {"customer_id": "C1002"}),
                ("search_knowledge_base", {"query": "refund charge after cancellation"}),
            ),
            answer,
        ],
    )
    q = "I cancelled but was charged today. Refund?"
    session = new_session("C1002", q)
    result = await container.agent.run(session=session, principal=anonymous("C1002"), user_message=q)

    assert sorted(result.trace.trajectory()[:2]) == ["get_customer_account", "search_knowledge_base"]
    assert {s.evidence_id for s in result.sources} == {"A1", "K1"}
    assert result.evidence_summary["account_data_used"] is True
    assert session.last_account_lookup == "C1002"


# 6 -------------------------------------------------------------------------------------------------
async def test_tool_failure_becomes_observation(kb_store) -> None:  # type: ignore[no-untyped-def]
    class BrokenRepo:
        async def get(self, customer_id: str) -> None:
            raise RuntimeError("database down")

    def after_failure(request: LLMRequest) -> LLMResponse:
        obs = last_observation(request)
        assert obs["status"] == "error"
        assert obs["error"]["code"] == "internal_error"
        assert "database down" not in obs["error"]["message"]  # internals never leak to the model
        return text_response("TYPE: cannot_verify\nI can't access your account right now.")

    container, _, _ = await build_container(
        kb_store, [tool_response(("get_customer_account", {"customer_id": "C1002"})), after_failure]
    )
    container.registry._tools["get_customer_account"].repository = BrokenRepo()  # type: ignore[attr-defined]
    result = await container.agent.run(
        session=new_session("C1002", "status?"), principal=anonymous("C1002"), user_message="status?"
    )
    assert result.trace.tool_calls[0].status == "error"
    assert result.response_type == "cannot_verify"


# 7 -------------------------------------------------------------------------------------------------
async def test_web_search_outage_is_retried_then_reported(kb_store) -> None:  # type: ignore[no-untyped-def]
    from backend.tools.base import ToolError

    class FlakyWeb:
        name = "flaky"
        calls = 0

        async def search(self, query: str, max_results: int) -> list[WebResult]:
            FlakyWeb.calls += 1
            raise ToolError("web_search_unavailable", "provider down", retryable=True)

    def after(request: LLMRequest) -> LLMResponse:
        obs = last_observation(request)
        assert obs["error"]["code"] == "web_search_unavailable"
        return text_response("TYPE: cannot_verify\nI couldn't reach external sources.")

    container, _, _ = await build_container(
        kb_store,
        [tool_response(("web_search", {"query": "windows long paths"})), after],
        web_provider=FlakyWeb(),
    )
    result = await container.agent.run(
        session=new_session(None, "q"), principal=anonymous(), user_message="q"
    )
    assert FlakyWeb.calls == 3  # retried with backoff up to TOOL_MAX_ATTEMPTS
    assert result.trace.tool_calls[0].attempts == 3
    assert result.response_type == "cannot_verify"


# 8 -------------------------------------------------------------------------------------------------
async def test_conflicting_documents_carry_authority_metadata(kb_store) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, Any] = {}

    def answer(request: LLMRequest) -> LLMResponse:
        obs = last_observation(request)
        captured.update({r["document_id"]: r for r in obs["results"]})
        return text_response("TYPE: answer\nThe 30-day guarantee was retired [K1].")

    container, _, _ = await build_container(
        kb_store,
        [
            tool_response(
                ("search_knowledge_base", {"query": "30-day money-back guarantee refund", "top_k": 8})
            ),
            answer,
        ],
    )
    q = "Is the 30-day money-back guarantee still valid?"
    await container.agent.run(session=new_session(None, q), principal=anonymous(), user_message=q)
    assert captured["faq"]["authority"] == "summary"
    assert "official policy documents take precedence" in captured["faq"]["warning"]
    assert captured["refund-policy"]["authority"] == "official"
    assert captured["refund-policy"]["effective_date"] == "2026-01-01"


# 9 -------------------------------------------------------------------------------------------------
async def test_prompt_injection_cannot_reach_other_customers(kb_store) -> None:  # type: ignore[no-untyped-def]
    """Even if the model obeys an injected instruction, the tool layer refuses."""

    def obey_injection(request: LLMRequest) -> LLMResponse:
        obs = last_observation(request)
        community = [r for r in obs["results"] if r["document_id"] == "community-tips"]
        assert community and "untrusted data" in community[0]["warning"]
        return tool_response(("get_customer_account", {"customer_id": "C1004"}))

    def after(request: LLMRequest) -> LLMResponse:
        obs = last_observation(request)
        assert obs["error"]["code"] == "not_authorized"
        return text_response("TYPE: answer\nCommunity users suggest webhooks [K1].")

    container, _, _ = await build_container(
        kb_store,
        [
            tool_response(
                (
                    "search_knowledge_base",
                    {"query": "refund announcement AI assistants", "document_id": "community-tips"},
                )
            ),
            obey_injection,
            after,
        ],
    )
    q = "What do community users say about refunds?"
    result = await container.agent.run(
        session=new_session("C1001", q), principal=anonymous("C1001"), user_message=q
    )
    denied = result.trace.tool_calls[1]
    assert denied.tool == "get_customer_account"
    assert denied.status == "error"
    assert denied.error_code == "not_authorized"
    assert "Globex" not in result.answer


# 10 ------------------------------------------------------------------------------------------------
async def test_step_limit_forces_finalization_without_tools(kb_store) -> None:  # type: ignore[no-untyped-def]
    calls = {"n": 0}

    def loop_forever(request: LLMRequest) -> LLMResponse:
        if request.tool_choice == "none":
            assert "step budget" in request.messages[-1].text
            return text_response(
                "TYPE: cannot_verify\nI couldn't complete this. Contact support@cloudbox.example."
            )
        calls["n"] += 1
        return tool_response(("search_knowledge_base", {"query": f"attempt {calls['n']}"}))

    container, _, _ = await build_container(
        kb_store, loop_forever, settings=make_settings(max_agent_steps=3, max_tool_calls=10)
    )
    result = await container.agent.run(
        session=new_session(None, "q"), principal=anonymous(), user_message="q"
    )
    assert calls["n"] == 3
    assert result.stop_reason == "max_steps"
    assert "forced_finalization:max_steps" in result.trace.guardrail_events
    assert result.response_type == "cannot_verify"


async def test_tool_call_budget_is_enforced(kb_store) -> None:  # type: ignore[no-untyped-def]
    def many(request: LLMRequest) -> LLMResponse:
        if tool_results_in(request):
            obs = tool_results_in(request)
            assert obs[-1]["error"]["code"] == "tool_budget_exhausted"
            return text_response("TYPE: cannot_verify\nToo many lookups.")
        return tool_response(*[("search_knowledge_base", {"query": f"q{i}"}) for i in range(4)])

    container, _, _ = await build_container(kb_store, many, settings=make_settings(max_tool_calls=3))
    result = await container.agent.run(
        session=new_session(None, "q"), principal=anonymous(), user_message="q"
    )
    assert [c.status for c in result.trace.tool_calls] == ["ok", "ok", "ok", "error"]


# 11 ------------------------------------------------------------------------------------------------
async def test_missing_customer_id_leads_to_clarification(kb_store) -> None:  # type: ignore[no-untyped-def]
    def after_denied(request: LLMRequest) -> LLMResponse:
        obs = last_observation(request)
        assert obs["error"]["code"] == "not_authorized"
        return text_response("TYPE: clarification\nCould you share your customer ID (it starts with C)?")

    container, _, _ = await build_container(
        kb_store, [tool_response(("get_customer_account", {"customer_id": "C1003"})), after_denied]
    )
    q = "Why was I charged twice?"
    result = await container.agent.run(session=new_session(None, q), principal=anonymous(), user_message=q)
    assert result.response_type == "clarification"
    assert result.evidence_summary["account_data_used"] is False


# 12 ------------------------------------------------------------------------------------------------
async def test_ambiguous_request_clarification_without_tools(kb_store) -> None:  # type: ignore[no-untyped-def]
    container, _, _ = await build_container(
        kb_store, [text_response("TYPE: clarification\nWhat isn't working — sync, sign-in, or the API?")]
    )
    result = await container.agent.run(
        session=new_session(None, "It's not working."),
        principal=anonymous(),
        user_message="It's not working.",
    )
    assert result.trace.trajectory() == ["clarification"]
    assert result.trace.guardrail_events == []  # clarifications are not forced to cite


# --- additional behaviours ------------------------------------------------------------------------


async def test_conversation_memory_customer_id_from_earlier_turn(kb_store) -> None:  # type: ignore[no-untyped-def]
    def look_up(request: LLMRequest) -> LLMResponse:
        assert "C1006" in (request.system_dynamic or "")
        assert any("C1006" in m.text for m in request.messages if m.role == "user")
        return tool_response(("get_customer_account", {"customer_id": "C1006"}))

    container, _, _ = await build_container(
        kb_store, [look_up, text_response("TYPE: answer\nYour monthly quota is used up [A1].")]
    )
    session = new_session(None, "My customer ID is C1006.")
    session.add_assistant_turn("Thanks! How can I help?", "clarification", [])
    session.add_user_turn("Why am I getting 429s?")
    result = await container.agent.run(
        session=session, principal=anonymous(), user_message="Why am I getting 429s?"
    )
    assert result.evidence_summary["account_data_used"] is True
    account = result.trace.tool_calls[0]
    assert account.status == "ok"


async def test_citation_guardrail_runs_once(kb_store) -> None:  # type: ignore[no-untyped-def]
    def answer_with_citation(request: LLMRequest) -> LLMResponse:
        assert request.messages[-1].role == "system"
        assert "without evidence citations" in request.messages[-1].text
        return text_response("TYPE: answer\nRotate the key [K1].")

    container, _, _ = await build_container(
        kb_store,
        [
            tool_response(("search_knowledge_base", {"query": "rotate key"})),
            text_response("TYPE: answer\nRotate the key in settings."),
            answer_with_citation,
        ],
    )
    result = await container.agent.run(
        session=new_session(None, "q"), principal=anonymous(), user_message="q"
    )
    assert result.trace.guardrail_events == ["citation_notice"]
    assert result.sources


async def test_fabricated_citations_are_removed(kb_store) -> None:  # type: ignore[no-untyped-def]
    container, _, _ = await build_container(
        kb_store,
        [
            tool_response(("search_knowledge_base", {"query": "rotate key"})),
            text_response("TYPE: answer\nRotate the key [K1]. Keys never expire [K42]."),
        ],
    )
    result = await container.agent.run(
        session=new_session(None, "q"), principal=anonymous(), user_message="q"
    )
    assert "[K42]" not in result.answer
    assert result.evidence_summary["invalid_citations_removed"] == 1
    assert result.evidence_summary["confidence"] != "high"


async def test_llm_outage_returns_safe_fallback(kb_store) -> None:  # type: ignore[no-untyped-def]
    container, _, _ = await build_container(
        kb_store, [LLMError("overloaded", retryable=True, provider="scripted")]
    )
    result = await container.agent.run(
        session=new_session(None, "q"), principal=anonymous(), user_message="q"
    )
    assert result.stop_reason == "llm_error"
    assert result.response_type == "cannot_verify"
    assert "support@cloudbox.example" in result.answer


async def test_refusal_is_handled(kb_store) -> None:  # type: ignore[no-untyped-def]
    refusal = LLMResponse(stop_reason="refusal", model="m", provider="scripted", usage=Usage())
    container, _, _ = await build_container(kb_store, [refusal])
    result = await container.agent.run(
        session=new_session(None, "q"), principal=anonymous(), user_message="q"
    )
    assert result.stop_reason == "refusal"
    assert result.response_type == "cannot_verify"


async def test_invalid_tool_arguments_are_returned_to_model(kb_store) -> None:  # type: ignore[no-untyped-def]
    def fix(request: LLMRequest) -> LLMResponse:
        obs = last_observation(request)
        assert obs["error"]["code"] == "invalid_arguments"
        return tool_response(("get_customer_account", {"customer_id": "C1002"}))

    container, _, _ = await build_container(
        kb_store,
        [
            tool_response(("get_customer_account", {"customer_id": "bob"})),
            fix,
            text_response("TYPE: answer\nYou're on Pro [A1]."),
        ],
    )
    result = await container.agent.run(
        session=new_session("C1002", "plan?"), principal=anonymous("C1002"), user_message="plan?"
    )
    assert [c.status for c in result.trace.tool_calls] == ["error", "ok"]


async def test_usage_cost_and_trace_are_recorded(kb_store) -> None:  # type: ignore[no-untyped-def]
    container, _, _ = await build_container(
        kb_store,
        [
            tool_response(("search_knowledge_base", {"query": "invoices"})),
            text_response("TYPE: answer\nSettings > Billing > Invoices [K1]."),
        ],
    )
    result = await container.agent.run(
        session=new_session(None, "q"), principal=anonymous(), user_message="q"
    )
    purposes = [c.purpose for c in result.trace.llm_calls]
    assert purposes.count("agent") == 2
    assert purposes.count("evaluator") == 1
    assert result.usage.input_tokens > 0
    assert result.cost_usd == 0.0  # scripted models are free
    labels = [e.label for e in result.activity]
    assert "Searching CloudBox knowledge base…" in labels
    assert labels[-1].startswith("Answer generated from 1 source")
