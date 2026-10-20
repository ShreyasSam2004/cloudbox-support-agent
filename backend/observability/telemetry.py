"""Azure Monitor / Application Insights via OpenTelemetry.

Enabled when ``APPLICATIONINSIGHTS_CONNECTION_STRING`` is set (injected from Key Vault in Azure
Container Apps). Exports request/dependency traces (FastAPI, httpx, asyncpg spans) and Python logs,
so a single operation ID links the HTTP request, every LLM call and every tool call.
"""

from __future__ import annotations

from backend.config.settings import Settings
from backend.observability.logging import get_logger

log = get_logger(__name__)


def configure_telemetry(settings: Settings) -> bool:
    if settings.applicationinsights_connection_string is None:
        return False
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(
        connection_string=settings.applicationinsights_connection_string.get_secret_value(),
        logger_name="backend",
        resource_attributes={
            "service.name": settings.service_name,
            "deployment.environment": settings.environment,
        },
    )
    log.info("telemetry.azure_monitor_enabled")
    return True
