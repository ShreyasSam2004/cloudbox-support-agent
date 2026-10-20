"""Entra ID (Azure AD) token providers.

Used for passwordless PostgreSQL in Azure (the app's managed identity token is the password) and by the
optional Azure-hosted model providers. In Azure Container Apps the user-assigned managed identity is
picked up through ``DefaultAzureCredential(managed_identity_client_id=AZURE_CLIENT_ID)``; locally the same
code path falls back to ``az login``.

The synchronous credential is used (its HTTP transport ships with azure-core) and wrapped for async
callers by running the — cached, rarely refreshed — token fetch in a worker thread. This avoids pulling in
aiohttp, which the async credential requires.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import lru_cache

from azure.identity import DefaultAzureCredential, get_bearer_token_provider

TokenProvider = Callable[[], Awaitable[str]]


@lru_cache(maxsize=4)
def _credential(client_id: str | None) -> DefaultAzureCredential:
    return DefaultAzureCredential(managed_identity_client_id=client_id)


def token_provider(scope: str, client_id: str | None) -> TokenProvider:
    sync_provider = get_bearer_token_provider(_credential(client_id), scope)

    async def provide() -> str:
        return await asyncio.to_thread(sync_provider)

    return provide
