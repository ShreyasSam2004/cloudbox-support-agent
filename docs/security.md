# Security Design

Threat model in one sentence: **the model is not a security boundary.** Anything the model reads —
customer messages, knowledge-base passages, web pages, account notes — may try to manipulate it, so
every capability that matters is constrained in code, outside the model.

## 1. Controls by layer

| Threat | Control | Where |
|--------|---------|-------|
| Prompt injection in KB documents / web pages ("ignore previous instructions", "call get_customer_account for C1004", hidden HTML) | (1) content is passed as JSON data with an explicit "untrusted" note; (2) heuristic detector labels suspicious passages; (3) hidden markup stripped from web content; (4) **tool-level authorization** makes the dangerous actions impossible regardless of what the model does | `security/content_safety.py`, `tools/*`, `security/authorization.py` |
| Reading another customer's account | Authorization in the tool: authenticated principal only, or session-bound customer, or (demo only) IDs typed by the user — provenance checked against the user's own messages; sessions cannot switch customers | `security/authorization.py`, `api/service.py` |
| Customer data leaking to third parties | `web_search` rejects queries containing emails, customer IDs, invoice IDs, API keys, card or phone numbers | `tools/web_search.py` |
| Credential / PII leakage in replies | Output validator redacts API-key patterns and non-CloudBox email addresses; account emails are masked at the source; limited account view in demo mode | `agent/output.py`, `tools/customer_account.py` |
| Chain-of-thought exposure | Reasoning blocks are never returned; `<think>` blocks are stripped; traces store actions, not reasoning; UI shows activity labels only | `agent/output.py`, `schemas/trace.py` |
| Fabricated citations / invented policy | Citations validated against evidence retrieved in this execution; uncited answers trigger one corrective notice; web content labelled "not CloudBox policy" | `agent/output.py`, `agent/loop.py` |
| Runaway loops / cost exhaustion | `MAX_AGENT_STEPS`, `MAX_TOOL_CALLS`, `AGENT_TIMEOUT_S`, per-tool timeouts, bounded retries; per-replica rate limiter + Front Door WAF rate limit | `agent/loop.py`, `tools/registry.py`, `security/rate_limit.py`, Terraform |
| Malformed / oversized input | Pydantic request models (`extra="forbid"`, length and pattern limits), 32 KB body limit, tool argument validation | `schemas/api.py`, `api/middleware.py`, `tools/base.py` |
| Bypassing the WAF | NSG admits only `AzureFrontDoor.Backend`; API rejects requests without this profile's `X-Azure-FDID` | Terraform `network`, `api/middleware.py` |
| Unsafe production configuration | Startup validation refuses `AUTH_MODE=none`, unverified lookups, fixture web search, HS256 test secrets, in-memory stores and local/test models in prod/staging | `config/settings.py` |
| Secrets in code / state | No secrets in the repo; model API keys live in Key Vault (written out of band by `scripts/set-model-secrets.sh`, never by Terraform or CI) and reach the app as Key Vault references; Postgres password auth disabled (Entra tokens); CI by OIDC; `.env` git-ignored; gitleaks in CI | Terraform, workflows |
| Vulnerable dependencies / images | pip-audit, npm audit, Dependabot, Trivy image scan (blocking on fixable HIGH/CRITICAL), CodeQL | `.github/workflows/ci.yml` |
| Infrastructure misconfiguration | Trivy IaC scan + TFLint in CI; secure defaults (TLS 1.2, HTTPS only, no public DB, no ACR admin user, no shared storage keys, purge protection) | Terraform |
| XSS in the UI | React elements only (no `innerHTML`), strict CSP (`default-src 'self'`), `X-Frame-Options: DENY` | `frontend/src/components/RichText.tsx`, nginx, Front Door rules |

## 2. Authentication modes

* `AUTH_MODE=jwt` (staging/prod): bearer JWT verified against the identity provider's JWKS (RS256/ES256),
  `exp`/`sub` required, issuer and audience checked; the customer ID comes **only** from the token claim.
* `AUTH_MODE=none` (local/dev demo): a `customer_id` in the request is treated as asserted by a trusted
  portal. Refused in prod.

## 3. Least privilege (Azure)

* App identity: `AcrPull` (registry), `Key Vault Secrets User` (vault — model API keys are Key Vault
  references), Postgres Entra administrator of its own database. Operators who store the model keys get
  `Key Vault Secrets Officer` only if listed in `key_vault_secret_officers`.
  *Stricter option:* make a DBA group the Entra admin and grant the app identity a role with only DML +
  schema-migration rights via `pgaadauth_create_principal`.
* CI: separate read-only plan identity (Reader + a two-action custom role) and apply identity per environment,
  both scoped to the environment's resource group; prod applies require GitHub environment approval.

## 4. Data handling

* Mock customer data only; contact emails are masked in tool output; no payment instruments are stored.
* Sessions hold conversation text only; traces hold actions and metadata. Both are pruned by
  `cloudbox prune --days N`. Logs redact keys named like secrets, tokens, passwords and emails.
* Postgres: private network, TLS required, encryption at rest (platform-managed keys), PITR backups.

## 5. Known gaps (accepted for this scope)

* The injection detector is heuristic and English-only; it is a labelling aid, not the defence.
* The in-process rate limiter is per replica; the global limit is the WAF rule.
* Container Apps ingress is public (restricted to Front Door by NSG + header); Private Link from Front Door
  Premium to the environment is the next hardening step.
* Model APIs are public internet endpoints (TLS + API key); an egress allow-list via NAT gateway/Azure Firewall is a future improvement. ACR uses its public endpoint with Entra auth.
