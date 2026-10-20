"""Provider translation tests (no network)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from backend.models.anthropic_provider import AnthropicProvider
from backend.models.base import ChatMessage, LLMRequest, ToolCall, ToolResultBlock, ToolSpec
from backend.models.ollama_provider import OllamaProvider, _recover_text_tool_call
from backend.models.openai_provider import OpenAIProvider

TOOLS = [
    ToolSpec(name="search_knowledge_base", description="d", input_schema={"type": "object", "properties": {}})
]


def _conversation() -> list[ChatMessage]:
    call = ToolCall(id="call_1", name="search_knowledge_base", arguments={"query": "refund"})
    return [
        ChatMessage.user("Refund?"),
        ChatMessage(role="assistant", content=[call]),
        ChatMessage.tool_results(
            [ToolResultBlock(tool_call_id="call_1", name="search_knowledge_base", content="{}")]
        ),
        ChatMessage.system_notice("Step budget exhausted."),
    ]


def test_anthropic_params_cache_tools_and_effort() -> None:
    provider = AnthropicProvider("claude-opus-5-5", api_key="test", client=object())
    params = provider._build_params(
        LLMRequest(
            system="STATIC",
            system_dynamic="DYNAMIC",
            messages=_conversation(),
            tools=TOOLS,
            tool_choice="none",
            effort="medium",
            response_schema={"type": "object"},
        )
    )
    assert params["system"][0] == {"type": "text", "text": "STATIC", "cache_control": {"type": "ephemeral"}}
    assert params["system"][1] == {"type": "text", "text": "DYNAMIC"}
    assert params["tool_choice"] == {"type": "none"}
    assert params["output_config"]["effort"] == "medium"
    assert params["output_config"]["format"]["type"] == "json_schema"
    roles = [m["role"] for m in params["messages"]]
    assert roles == [
        "user",
        "assistant",
        "user",
        "system",
    ]  # notice follows a user turn → native system message
    assert params["messages"][1]["content"][0]["type"] == "tool_use"
    assert params["messages"][2]["content"][0]["tool_use_id"] == "call_1"


def test_anthropic_replays_provider_raw_and_folds_misplaced_system() -> None:
    provider = AnthropicProvider("claude-opus-5-5", api_key="test", client=object())
    raw = [{"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "text", "text": "hi"}]
    messages = [
        ChatMessage.user("q"),
        ChatMessage(role="assistant", content=[], provider_raw=raw, provider_name="anthropic"),
        ChatMessage.system_notice("cite your evidence"),
    ]
    params = provider._build_params(LLMRequest(system="S", messages=messages))
    assert params["messages"][1]["content"] == raw  # thinking blocks replayed unchanged
    assert (
        params["messages"][2]["role"] == "user"
    )  # system notice after an assistant turn → labelled user turn
    assert "[CloudBox platform notice]" in params["messages"][2]["content"]


def test_foundry_disables_unsupported_features() -> None:
    provider = AnthropicProvider("claude-opus-5-5", platform="foundry", client=object())
    assert provider.name == "anthropic_foundry"
    params = provider._build_params(LLMRequest(system="S", messages=_conversation()))
    assert params["messages"][-1]["role"] == "user"  # no mid-conversation system messages on Foundry
    assert provider._use_fallback is False


def test_openai_message_mapping() -> None:
    messages = OpenAIProvider._messages_to_api(
        LLMRequest(system="S", system_dynamic="D", messages=_conversation())
    )
    assert messages[0] == {"role": "system", "content": "S\n\nD"}
    assert messages[2]["tool_calls"][0]["function"]["arguments"] == json.dumps({"query": "refund"})
    assert messages[3] == {"role": "tool", "tool_call_id": "call_1", "content": "{}"}
    assert messages[4]["role"] == "system"


def test_ollama_recovers_text_tool_calls_only_for_offered_tools() -> None:
    call = _recover_text_tool_call(
        '{"name": "search_knowledge_base", "parameters": {"query": "x"}}', {"search_knowledge_base"}
    )
    assert call is not None and call.arguments == {"query": "x"}
    assert _recover_text_tool_call('{"name": "rm_rf", "parameters": {}}', {"search_knowledge_base"}) is None
    assert _recover_text_tool_call("plain answer", {"search_knowledge_base"}) is None


async def test_ollama_request_and_response_translation() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "<think>hidden</think>",
                    "tool_calls": [
                        {"function": {"name": "search_knowledge_base", "arguments": {"query": "q"}}}
                    ],
                },
                "done_reason": "stop",
                "prompt_eval_count": 120,
                "eval_count": 15,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama")
    provider = OllamaProvider("qwen", num_ctx=4096, think=False, client=client)
    response = await provider.complete(LLMRequest(system="S", messages=_conversation(), tools=TOOLS))
    assert captured["options"]["num_ctx"] == 4096
    assert captured["think"] is False
    assert captured["messages"][3]["role"] == "tool"
    assert response.tool_calls[0].name == "search_knowledge_base"
    assert response.text == ""  # reasoning stripped
    assert response.usage.input_tokens == 120


async def test_azure_token_provider_is_async_and_uses_sync_credential(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from backend.models import azure_auth

    calls: list[str] = []

    class FakeCredential:
        def get_token(self, *scopes: str, **_: object) -> object:
            calls.extend(scopes)
            return type("T", (), {"token": "entra-token", "expires_on": 4102444800})()

    azure_auth._credential.cache_clear()
    monkeypatch.setattr(azure_auth, "DefaultAzureCredential", lambda **_: FakeCredential())
    provide = azure_auth.token_provider("https://ossrdbms-aad.database.windows.net/.default", "client-id")
    assert await provide() == "entra-token"
    assert calls == ["https://ossrdbms-aad.database.windows.net/.default"]
    azure_auth._credential.cache_clear()
