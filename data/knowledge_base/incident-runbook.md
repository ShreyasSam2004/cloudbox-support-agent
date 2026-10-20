---
doc_id: incident-runbook
title: Incident Communication Runbook for Support
doc_type: runbook
category: reliability
authority: official-internal
effective_date: 2026-08-01
version: "1.6"
audience: support-staff
url: https://docs.cloudbox.example/internal/runbooks/incident-communication
---

# Incident Communication Runbook for Support

Audience: CloudBox support staff and the support assistant. Use this runbook when customers contact support about errors that may be caused by a CloudBox incident.

## 1. Severity levels

| Severity | Definition | Status page |
|---|---|---|
| SEV1 | Widespread outage or suspected data loss | Major outage |
| SEV2 | Significant degradation for a subset of customers or one region | Partial outage |
| SEV3 | Minor degradation, workaround available | Degraded performance |

## 2. During an active incident

1. Acknowledge the customer's report and link https://status.cloudbox.example.
2. **Do not speculate about root cause** and do not give a resolution time that has not been posted on the status page.
3. **Do not promise SLA credits.** Explain that eligible plans can claim credits after the incident through the process in [SLA §6](sla.md#6-claiming-credits).
4. Ask for affected request IDs and timestamps (UTC) and attach them to the incident ticket.
5. If the customer reports possible data loss, escalate to SEV1 immediately.

## 3. After resolution

Point customers to the post-incident report on the status page when it is published (within 5 business days for SEV1 and SEV2).

## 4. Recent incidents (last 90 days)

| Incident | Date (UTC) | Duration | Impact | Severity |
|---|---|---|---|---|
| INC-2026-0814 | 2026-08-14 09:02–09:20 | 18 min | Elevated web app latency (EMEA) | SEV3 |
| INC-2026-0903 | 2026-09-03 22:40–23:05 | 25 min | Desktop sync delays, no errors | SEV3 |
| INC-2026-1007 | 2026-10-07 14:10–15:25 | 75 min | 503 errors on upload and API endpoints (us-east), more than 5% of requests failing | SEV2 |

Status for incidents older than 90 days is available on the status page history.
