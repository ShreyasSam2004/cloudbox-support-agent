---
doc_id: api-authentication
title: API Authentication and API Key Management
doc_type: api_reference
category: api
authority: official
effective_date: 2026-05-01
version: "2026.2"
audience: customer
url: https://docs.cloudbox.example/api/authentication
---

# API Authentication and API Key Management

## 1. Authenticating requests

Every request to the CloudBox API must include a secret API key in the `Authorization` header:

```http
GET /v2/files HTTP/1.1
Host: api.cloudbox.example
Authorization: Bearer cbx_live_8f3k...redacted
```

Requests over plain HTTP are rejected. Never embed secret keys in client-side code or mobile apps.

## 2. Key types and scopes

| Prefix | Environment | Notes |
|---|---|---|
| `cbx_live_` | Production | Acts on real data and counts toward quota |
| `cbx_test_` | Sandbox | Isolated sandbox data; does not count toward quota |

Each key has one or more scopes: `files:read`, `files:write`, `billing:read`, `admin`. A request that needs a scope the key lacks fails with `403 insufficient_scope` (CBX-4031).

Organizations can have up to 25 active keys on Starter and Pro, and up to 100 on Business and Enterprise.

## 3. Creating a key

1. Go to **Settings > Developer > API keys**.
2. Click **Create key**, choose the environment and scopes, and name the key.
3. Copy the key immediately. **The full key is shown only once** and cannot be retrieved later.

Owners and Admins can create keys for the organization. Members with the *Developer* permission can create personal keys.

## 4. Rotating ("resetting") a key

If you want to reset an API key — because it may have been exposed, an employee left, or as routine hygiene — rotate it:

1. Go to **Settings > Developer > API keys**.
2. Open the menu (⋯) next to the key and choose **Rotate key**.
3. Copy the new key and deploy it to your applications.

After rotation the **old key keeps working for a 24-hour grace period** so you can deploy the new key without downtime. On Business and Enterprise, admins can configure the grace period anywhere from 0 to 72 hours in **Settings > Developer > Key policy**.

You can also rotate from the CLI:

```bash
cloudbox keys rotate --key-id key_123abc
```

## 5. Revoking a key

If a key is compromised, **revoke** it instead of rotating it. Revocation has no grace period and takes effect within 60 seconds. Requests with a revoked key fail with `401 api_key_revoked` (CBX-4011).

## 6. Lost keys

Lost keys cannot be recovered. Rotate the key to obtain a new one.

## 7. OAuth for third-party apps

Applications acting on behalf of other CloudBox users must use OAuth 2.0 (authorization code flow with PKCE) instead of API keys. See the OAuth guide in the developer portal.

## 8. Related errors

| HTTP | Error | Code | Meaning |
|---|---|---|---|
| 401 | `invalid_api_key` | CBX-4010 | Key is malformed or does not exist |
| 401 | `api_key_revoked` | CBX-4011 | Key was revoked, or rotated and its grace period expired |
| 403 | `insufficient_scope` | CBX-4031 | Key lacks the scope required by the endpoint |

Full list: [API Error Codes](api-error-codes.md).
