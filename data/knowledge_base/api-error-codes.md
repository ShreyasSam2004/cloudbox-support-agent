---
doc_id: api-error-codes
title: API Error Codes Reference
doc_type: api_reference
category: api
authority: official
effective_date: 2026-07-01
version: "2026.3"
audience: customer
url: https://docs.cloudbox.example/api/errors
---

# API Error Codes Reference

Errors are returned as JSON with an HTTP status, a machine-readable `error` string, a CloudBox code (`CBX-xxxx`) and a `request_id`. Include the `request_id` whenever you contact support.

```json
{
  "error": "rate_limit_exceeded",
  "code": "CBX-4291",
  "message": "Rate limit of 1000 requests per minute exceeded.",
  "request_id": "req_01HZX3K9Q2"
}
```

## 1. Client errors (4xx)

| HTTP | Error | Code | Meaning | What to do |
|---|---|---|---|---|
| 400 | `invalid_request` | CBX-4000 | Malformed JSON or missing required field | Fix the request body |
| 400 | `invalid_path` | CBX-4002 | File path has unsupported characters or is too long | See [Desktop Sync Troubleshooting §4](troubleshooting-sync.md#4-unsupported-file-names-and-paths) |
| 401 | `invalid_api_key` | CBX-4010 | API key malformed or unknown | Check the key; see [API Authentication](api-authentication.md) |
| 401 | `api_key_revoked` | CBX-4011 | Key revoked, or rotated and grace period expired | Use the new key |
| 403 | `insufficient_scope` | CBX-4031 | Key lacks the scope required | Create a key with the needed scope |
| 403 | `account_locked` | CBX-4032 | The user account that owns the key is locked after failed sign-ins | See [Account Security §3](account-security.md#3-account-lockout) |
| 403 | `account_suspended` | CBX-4033 | Account suspended for non-payment | See [Billing Policy §4](billing-policy.md#4-failed-payments) |
| 404 | `not_found` | CBX-4040 | Resource does not exist or you lack access | Check the ID and permissions |
| 409 | `version_conflict` | CBX-4090 | File changed since you read it | Re-read and retry with the new `ETag` in `If-Match` |
| 413 | `payload_too_large` | CBX-4130 | File exceeds your plan's maximum single upload | Use resumable uploads (`/v2/uploads`); check plan limits |
| 422 | `validation_failed` | CBX-4220 | Field values are invalid | Read `details` in the response |
| 429 | `rate_limit_exceeded` | CBX-4291 | Per-minute rate limit exceeded | Wait `Retry-After`, back off; see [Rate Limits §3.1](api-rate-limits.md#31-rate_limit_exceeded-cbx-4291) |
| 429 | `quota_exceeded` | CBX-4292 | Monthly request quota exhausted | Retrying will not help; see [Rate Limits §3.2](api-rate-limits.md#32-quota_exceeded-cbx-4292) |

## 2. Server errors (5xx)

| HTTP | Error | Code | Meaning | What to do |
|---|---|---|---|---|
| 500 | `internal_error` | CBX-5000 | Unexpected server error | Retry with exponential backoff; contact support with the `request_id` if it persists |
| 502 | `bad_gateway` | CBX-5020 | Upstream error | Retry with backoff |
| 503 | `service_unavailable` | CBX-5030 | Maintenance or incident | Check https://status.cloudbox.example and retry later |

## 3. Retry guidance

Retry **5xx**, `rate_limit_exceeded` and network errors with exponential backoff and jitter. Do **not** retry other 4xx errors without changing the request: they will fail again. In particular, `quota_exceeded` cannot be fixed by retrying.

## 4. Large uploads

Files larger than 100 MB should use resumable uploads: create an upload session with `POST /v2/uploads`, send parts of 8–64 MB, then complete the session. Interrupted uploads can resume from the last confirmed part for up to 7 days.
