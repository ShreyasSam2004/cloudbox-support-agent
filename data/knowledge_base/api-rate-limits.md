---
doc_id: api-rate-limits
title: API Rate Limits and Quotas
doc_type: api_reference
category: api
authority: official
effective_date: 2026-07-01
version: "2026.3"
audience: customer
url: https://docs.cloudbox.example/api/rate-limits
---

# API Rate Limits and Quotas

CloudBox enforces **two independent limits** on API usage. They return the same HTTP status (429) but have different causes and different fixes, so always check the error code in the response body.

1. **Rate limit** — how many requests per minute your organization may send (a token bucket shared by all keys in the organization).
2. **Monthly quota** — how many requests your organization may send in the current billing period.

## 1. Limits by plan

| Plan | Rate limit | Burst | Monthly quota |
|---|---|---|---|
| Free | 60 requests / min | 120 for 10 s | 10,000 |
| Starter | 300 requests / min | 600 for 10 s | 250,000 |
| Pro | 1,000 requests / min | 2,000 for 10 s | 2,000,000 |
| Business | 3,000 requests / min | 6,000 for 10 s | 10,000,000 |
| Enterprise | Custom (default 10,000 / min) | Custom | Custom |

The Pro rate limit was raised from 600 to 1,000 requests per minute on 2026-07-01. Trials are limited to 300 requests per minute (see the [Free Trial Policy](trial-policy.md)).

## 2. Response headers

Every response includes:

| Header | Meaning |
|---|---|
| `X-RateLimit-Limit` | Requests allowed per minute |
| `X-RateLimit-Remaining` | Requests left in the current window |
| `X-RateLimit-Reset` | Unix time (seconds) when the window resets |
| `X-Quota-Remaining` | Requests left in the monthly quota |

A 429 response also includes `Retry-After`, the number of seconds to wait before retrying.

## 3. Handling 429 errors

### 3.1 `rate_limit_exceeded` (CBX-4291)

You sent more requests per minute than your plan allows. This is temporary.

* Wait for the number of seconds in `Retry-After` before retrying.
* Retry with **exponential backoff with jitter**; never retry in a tight loop.
* Reduce concurrency — the limit is shared by every worker using keys from your organization.
* Replace polling with **webhooks**. Polling for file changes is the most common cause of rate-limit errors.
* Batch work with the **Bulk API** (Pro and above), which has separate limits: 5 concurrent jobs on Pro, 20 on Business.

### 3.2 `quota_exceeded` (CBX-4292)

Your organization has used its entire monthly request quota. **Retrying will not help** — every request fails until the quota resets at the start of the next billing period. To restore service sooner:

* buy an **extra API quota block** (+1,000,000 requests for $20, Pro and Business; applies to the current period only), or
* upgrade to a plan with a higher quota (see [Plans and Pricing](plans-and-pricing.md)).

Check current usage in **Settings > Developer > Usage**.

## 4. Concurrency limits for uploads

Independently of the rate limit, each user can run up to 10 concurrent uploads on Pro and 50 on Business. Exceeding this returns `429 rate_limit_exceeded` with `"scope": "uploads"`.

## 5. Best practices

* Cache responses that do not change often, such as folder listings.
* Use webhooks instead of polling.
* Spread scheduled jobs instead of starting them all at the top of the hour.
* Monitor `X-RateLimit-Remaining` and `X-Quota-Remaining` and alert before you run out.
