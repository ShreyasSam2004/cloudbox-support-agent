from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.api.dependencies import get_container
from backend.api.service import run_chat
from backend.observability.logging import get_logger
from backend.schemas.api import ChatRequest, ChatResponse
from backend.schemas.trace import ActivityEvent

router = APIRouter(prefix="/api/v1", tags=["chat"])
log = get_logger(__name__)


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    """Run the support agent for one customer message and return the answer with sources."""
    return await run_chat(get_container(request), request, body)


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest, request: Request) -> StreamingResponse:
    """Like ``/chat``, but streams user-safe activity events (SSE) before the final answer."""
    container = get_container(request)
    queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()

    async def emit(event: ActivityEvent) -> None:
        await queue.put(("activity", event.model_dump_json()))

    async def worker() -> None:
        try:
            response = await run_chat(container, request, body, emit=emit)
            await queue.put(("final", response.model_dump_json()))
        except HTTPException as exc:
            await queue.put(("error", json.dumps({"status": exc.status_code, "message": exc.detail})))
        except Exception:
            log.exception("chat_stream.failed")
            await queue.put(("error", json.dumps({"status": 500, "message": "Internal error."})))

    task = asyncio.create_task(worker())

    async def stream() -> AsyncIterator[str]:
        try:
            while True:
                event, data = await queue.get()
                yield _sse(event, data)
                if event in ("final", "error"):
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
