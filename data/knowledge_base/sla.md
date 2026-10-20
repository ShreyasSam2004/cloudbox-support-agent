---
doc_id: sla
title: Service Level Agreement (SLA)
doc_type: legal
category: reliability
authority: official
effective_date: 2026-01-01
version: "2026.1"
audience: customer
url: https://docs.cloudbox.example/legal/sla
---

# Service Level Agreement (SLA)

## 1. Coverage

| Plan | Monthly uptime commitment | Service credits |
|---|---|---|
| Free, Starter | None | No |
| Pro | None (internal target 99.5%) | No |
| Business | 99.9% | Yes |
| Enterprise | 99.95% | Yes |

## 2. Definitions

* **Monthly uptime percentage** = (total minutes in the calendar month − downtime minutes) / total minutes in the month × 100.
* **Downtime** is any period of 5 or more consecutive minutes during which more than 5% of valid API requests to a region fail with 5xx errors, or the web app is unreachable, as measured by CloudBox's monitoring.

## 3. Exclusions

Downtime does not include: scheduled maintenance announced at least 72 hours in advance (maximum 4 hours per month); problems caused by the customer's systems, network or misuse; features labelled beta or preview; force majeure; and failures of third-party networks outside CloudBox's control.

## 4. Status and incident history

Live status and incident history are published at https://status.cloudbox.example.

## 5. Service credits

If monthly uptime falls below the commitment, the customer receives a service credit as a percentage of that month's subscription fee:

| Monthly uptime | Business credit | Enterprise credit |
|---|---|---|
| Below commitment but ≥ 99.0% (Business) / ≥ 99.5% (Enterprise) | 10% | 10% |
| Below 99.0% (Business) / below 99.5% (Enterprise) | 25% | 25% |
| Below 95.0% (Business) / below 99.0% (Enterprise) | 50% | 50% |

Credits are capped at 50% of the monthly fee.

## 6. Claiming credits

Submit a claim to support **within 30 days after the end of the month** in which the downtime occurred, including the dates and times affected and example request IDs. Approved credits are applied to the next invoice. **Credits are not refunds, have no cash value** and are the sole remedy for unavailability.
