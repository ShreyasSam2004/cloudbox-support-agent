# CloudBox Support Agent — agentic, self-correcting RAG on Azure

An autonomous customer-support agent for **CloudBox**, a fictional cloud-storage/API SaaS. The LLM decides
what it needs, which of three tools to use, whether retrieved evidence is good enough, when to search
again, when to check the customer's account, when to use the web, when to ask a question — and when to
stop. Answers are grounded in cited evidence; public-web information is never passed off as CloudBox policy.

```text
customer ─► Front Door + WAF ─► FastAPI ─► agent loop ◄──► Claude (Anthropic API)
                                              │
                         ┌────────────────────┼─────────────────────┐
              search_knowledge_base     get_customer_account     web_search
              (pgvector + FTS, RRF,     (authorized in code)     (PII-guarded,
               LLM retrieval evaluator)                           labelled external)
```

Contents: [What it does](#1-what-the-system-does) · [Why naive RAG is insufficient](#2-why-naive-rag-is-insufficient) ·
[What makes it agentic](#3-what-makes-this-agentic) · [Architecture](#4-architecture) · [Agent loop](#5-agent-loop) ·
[Tools](#6-tool-architecture) · [Retrieval](#7-retrieval-pipeline) · [Self-correction](#8-self-correction-mechanism) ·
[Evaluation](#9-evaluation-methodology) · [Local setup](#10-local-setup) · [Cloud architecture](#11-cloud-architecture) ·
[Terraform](#12-terraform-deployment) · [Environment variables](#13-environment-variables) · [Testing](#14-testing) ·
[Observability](#15-observability) · [Security](#16-security) · [Cost](#17-cost-considerations) ·
[Future work](#18-future-improvements)

---

## 1. What the system does

Customers ask things like *"How do I reset my API key?"*, *"Why was I charged twice?"*, *"I cancelled
yesterday and was charged today — refund?"*, *"My API returns 429"*. The agent:

* searches CloudBox's documentation (20 realistic docs: policies, pricing tables, API reference, error codes,
  troubleshooting, SLA, runbook, FAQ, release notes, community posts) and cites what it uses;
* looks at the customer's own account when the answer depends on it (cancellation vs. renewal timestamps,
  pending authorization holds vs. duplicate charges, quota vs. rate-limit 429s, lockout history, contract terms);
* uses the public web only for non-CloudBox knowledge, labelled as such;
* asks a concise clarifying question when it genuinely lacks information, and says "I can't verify that" instead
  of inventing policy;
* streams safe activity events to the UI ("Searching CloudBox knowledge base…", "Checking customer account…",
  "Answer generated from 3 sources.") — never its reasoning.

## 2. Why naive RAG is insufficient

Single-shot `question → top-k → answer` fails on support traffic in predictable ways:

* **The answer is in the account, not the docs.** "Why am I getting 429s?" has opposite answers for a customer
  who exhausted the monthly quota (retrying never helps) and one exceeding the per-minute limit (back off).
* **Exceptions live in other documents.** Refund rules change for Enterprise (addendum), trial conversions,
  and annual renewals with a usage threshold.
* **Retrieval picks the plausible-but-wrong passage.** The FAQ still advertises a retired 30-day guarantee;
  Terms of Service mention refunds without answering anything.
* **Some questions need outside knowledge** (how to enable Windows long paths) **or none of it** (do you sign
  HIPAA BAAs? → not documented; don't invent).

## 3. What makes this agentic

| Requirement | Where it lives |
|---|---|
| The LLM selects every action; nothing hard-codes "retrieve → grade → rewrite → answer" | `backend/agent/loop.py` — the loop only executes what the model asked for |
| Exactly three capability tools with JSON-schema interfaces | `backend/tools/` |
| Multiple / repeated KB searches with rewritten queries and document filters | model-chosen; evidenced by trajectories in the benchmark report |
| Retrieval quality is evaluated by an LLM and **returned to the agent** as an observation | `backend/retrieval/evaluator.py`, `tools/knowledge_base.py` |
| The agent decides what to do with a bad verdict (rewrite, account, web, abstain) | no code branches on the verdict |
| Clarifying questions, bounded execution (`MAX_AGENT_STEPS`, tool budget, wall clock) | prompt + `loop.py` |

Proof by test: `tests/integration/test_agent_scenarios.py` drives the *same* runtime through different
trajectories (search→answer; search→search→search→answer; search→web→answer; account∥search→answer;
clarification without tools; step-limit forced finalization; injected instructions blocked by the tool layer).

## 4. Architecture

```text
backend/
  agent/          loop, prompts, context builder, output validation
  tools/          tool base + registry (validation, budget, timeout, retry, tracing), the 3 tools, web providers
  retrieval/      parsing, structure-aware chunking, embeddings, pgvector + in-memory stores, hybrid retriever,
                  ingestion, LLM retrieval evaluator
  models/         provider abstraction: Anthropic (Claude), OpenAI (and OpenAI-compatible endpoints),
                  Ollama (local), scripted (tests); metering decorator
  evaluation/     dataset, baseline RAG, deterministic metrics, optional LLM judge, runner, report
  api/            FastAPI app, routes (chat, SSE stream, sessions, admin traces, health, metrics), middleware
  security/       JWT auth, authorization policy, injection/PII/secret guards, rate limiter
  storage/        asyncpg pool (password or Entra token) + migrations, sessions, customers, traces
  observability/  structured logging, metrics, per-execution recorder, Azure Monitor telemetry
  config/         environment settings with production guards, model pricing
frontend/         React + Vite + TypeScript support UI (nginx container)
infra/terraform/  bootstrap, modules (network, monitoring, keyvault, registry, postgres, ai, container_apps,
                  frontdoor, stack), environments/{dev,staging,prod}
data/             knowledge base, mock customers, web fixtures, evaluation dataset
tests/            unit, integration (agent, API, pgvector, live), evaluation
```

Full design, data model and decision log: [docs/architecture.md](docs/architecture.md).

## 5. Agent loop

```text
for step in 1..MAX_AGENT_STEPS:
    response = llm(static system prompt [cached], session context, conversation + observations, tools)
    if no tool calls → validate reply (citations, labels, redaction) → done
    run requested tools in parallel → append observations
safety boundary reached → one tools-disabled call: answer from evidence or say "cannot verify"
```

Two bounded guardrails: a one-time "cite your evidence or say you can't verify" notice when an answer has
no citations, and the forced finalization above. Details: [docs/agent-design.md](docs/agent-design.md).

## 6. Tool architecture

| Tool | Purpose | Safeguards |
|---|---|---|
| `search_knowledge_base(query, document_id?, document_type?, top_k?)` | internal docs; returns passages `K#` + metadata + `retrieval_evaluation` | untrusted-content labels, injection flags, authority/effective-date metadata |
| `get_customer_account(customer_id)` | account record `A1` | authorization in code (principal / bound session / user-typed ID in demo mode), masked PII |
| `web_search(query, max_results?)` | public web `W#` | rejects PII in queries, strips hidden HTML, flags injection, "not CloudBox policy" disclaimer |

All tools go through one registry: schema validation → tool-call budget → timeout → retries with
exponential backoff + jitter (transient errors only) → error-as-observation → metrics, traces, activity events.

## 7. Retrieval pipeline

Markdown with front matter → heading tree → structure-aware chunks (breadcrumbs, intact tables with header
rows, linearized table rows, one chunk per FAQ pair, parent rule carried into exceptions, cross-references)
→ embeddings → PostgreSQL **pgvector (HNSW)** + **full-text (GIN)** → **Reciprocal Rank Fusion** → 20
candidates → **LLM re-ranking** (inside the evaluator call, so no extra model call) → best 4.
Idempotent ingestion by content hash; embedding-model mismatch protection. Chunking, search mode, top-k
and re-ranking were chosen with a labelled retrieval benchmark rather than by judgment: re-ranking lifts
evidence recall in the top 4 from 78% to 90%. See [docs/retrieval.md](docs/retrieval.md#8-how-the-settings-were-chosen-retrieval-benchmark).

## 8. Self-correction mechanism

Every KB search is graded by an LLM evaluator (Claude Haiku 5.5, which also re-ranks) against the
**original** question: `{passage_scores, relevant, confidence, coverage, missing_information, reason}`. The verdict is part
of the observation; the agent decides whether to rewrite the query, follow a cross-reference with a
`document_id` filter, look up the account (the evaluator names account data as "missing" when policy
alone can't answer), use the web, or abstain. The number of retries is not fixed — only bounded.

## 9. Evaluation methodology

Baseline RAG and the agent run on the same 45-case dataset (FAQ, multi-document, policy exceptions,
customer-specific, memory, ambiguous, web-required, KB-missing, adversarial) with the same model, index,
reply protocol and validator. Deterministic grading (required facts, forbidden statements, behaviour,
citation validity, retrieval recall) is primary; an LLM judge is optional. Cost, tokens, latency and tool
use are measured per case. Methodology and **actual results**: [docs/evaluation.md](docs/evaluation.md).

**Results (2026-10-12, Claude Sonnet 5.5, one run):**

| | Baseline RAG | Agent |
|---|---|---|
| Resolved (correct, no hallucination) | 31/45 (68.9%) | **42/45 (93.3%)** |
| Hallucinations | 1 | 0 |
| Customer-specific / ambiguous / web questions resolved | 4/11 · 1/4 · 2/4 | 10/11 · 4/4 · 4/4 |
| Cost per question · p50 latency | $0.0049 · 3.6 s | $0.0116 · 8.7 s |

The agent's gain comes from account-specific, ambiguous and web-dependent questions. On plain FAQs both
are perfect, and plain RAG is 2.4× cheaper. Re-ranking with a Haiku grader cut the agent's cost per
question by 31% against the earlier configuration, with no measurable change in accuracy.

## 10. Local setup

Prerequisites: Python 3.12 via [uv](https://docs.astral.sh/uv/), Node 22+, Docker, and an Anthropic API key
(Claude) plus an OpenAI API key (embeddings) in `.env`. [Ollama](https://ollama.com) works for fully offline work.

```bash
cp .env.example .env            # choose LLM_PROVIDER / models; never commit .env
uv sync                         # Python deps
uv run cloudbox ingest          # build the index (in-memory store by default for local runs)
uv run uvicorn backend.api.app:create_app --factory --port 8000
cd frontend && npm ci && npm run dev    # UI on http://localhost:5173 (proxies /api to :8000)
uv run cloudbox chat --customer C1002   # or chat in the terminal
```

Full stack with PostgreSQL + pgvector (seeds mock customers and ingests the KB automatically):

```bash
docker compose up --build       # UI http://localhost:8080, API http://localhost:8000
# ports taken? API_PORT=18000 UI_PORT=18080 docker compose up
```

Demo identities (UI picker / `customer_id`): C1002 cancelled-then-charged, C1003 pending hold, C1012 true
duplicate, C1006 quota 429s, C1007 rate-limit 429s, C1005 locked, C1004 Enterprise, C1009 past due, C1008 trial.

## 11. Cloud architecture

Azure hosts the whole application, provisioned only by Terraform: **Front Door + WAF** → **Container Apps**
(API, UI and ingestion job — the app's containers; VNet-integrated, autoscaling, no VMs to patch) →
**PostgreSQL Flexible Server + pgvector** (private, Entra-only auth) · **Key Vault** (holds the Anthropic and
OpenAI API keys) · **Container Registry** · **Log Analytics + Application Insights**. The models themselves
are external APIs (Claude via Anthropic, embeddings via OpenAI) called over HTTPS. Why these services:
[docs/architecture.md](docs/architecture.md#2-key-decisions) · topology and environment differences:
[docs/deployment.md](docs/deployment.md).

## 12. Terraform deployment

```bash
# once, as a platform admin: remote state, env resource groups, GitHub OIDC identities
terraform -chdir=infra/terraform/bootstrap init && terraform -chdir=infra/terraform/bootstrap apply \
  -var subscription_id=<sub> -var github_repository=<owner>/<repo>

# per environment (normally done by .github/workflows/deploy.yml)
terraform -chdir=infra/terraform/environments/dev init -backend-config=backend.hcl
terraform -chdir=infra/terraform/environments/dev plan -var subscription_id=<sub> -out tfplan
terraform -chdir=infra/terraform/environments/dev apply tfplan
```

Quick path for the dev environment from a workstation: `./scripts/azure-dev.sh up` (and `down` to remove it).

Remote state in Azure Storage (Entra auth, blob-lease locking); dev/staging/prod are thin wrappers over one
`stack` module; secrets never pass through Terraform. CI promotes one image through dev → staging → prod
with a required-reviewer gate on prod and never destroys. Step-by-step: [docs/deployment.md](docs/deployment.md).

## 13. Environment variables

All configuration is environment-based (`backend/config/settings.py`, template in `.env.example`). The ones
that matter most:

| Variable | Purpose |
|---|---|
| `ENVIRONMENT` | `local/test/dev/staging/prod`; staging/prod refuse demo-grade settings |
| `LLM_PROVIDER`, `AGENT_MODEL`, `AGENT_EFFORT` | `anthropic` (default, `claude-sonnet-5-5`) or `openai`; `ollama` for offline local work (refused in staging/prod) |
| `EVALUATOR_PROVIDER`, `EVALUATOR_MODEL`, `RETRIEVAL_EVALUATOR_ENABLED` | retrieval evaluator / re-ranker (`claude-haiku-5-5`) |
| `RETRIEVAL_TOP_K`, `RETRIEVAL_RERANK_POOL`, `RETRIEVAL_LEXICAL_WEIGHT`, `CHUNK_MAX_CHARS` | retrieval tuning (measured defaults 4 / 20 / 1.0 / 1600) |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | Model API keys — `.env` locally, Key Vault references in Azure |
| `AZURE_CLIENT_ID` | Managed identity used for passwordless Postgres in Azure |
| `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DIM` | embeddings |
| `VECTOR_STORE`, `SESSION_STORE`, `CUSTOMER_STORE`, `TRACE_STORE`, `DATABASE_URL`, `DATABASE_AUTH` | storage (`DATABASE_AUTH=entra` = passwordless) |
| `MAX_AGENT_STEPS`, `MAX_TOOL_CALLS`, `AGENT_TIMEOUT_S`, `TOOL_TIMEOUT_S` | safety boundaries |
| `WEB_SEARCH_PROVIDER`, `TAVILY_API_KEY` | `tavily` / `fixture` / `disabled` |
| `AUTH_MODE`, `JWT_*`, `ALLOW_UNVERIFIED_CUSTOMER_LOOKUP`, `FRONT_DOOR_ID` | identity and edge protection |
| `RATE_LIMIT_PER_MINUTE`, `MAX_REQUEST_BYTES`, `CORS_ALLOWED_ORIGINS`, `ADMIN_API_KEY` | API protection |
| `APPLICATIONINSIGHTS_CONNECTION_STRING`, `LOG_JSON`, `EXPOSE_TRACE_IN_RESPONSE` | observability |

## 14. Testing

```bash
uv run pytest                                   # unit, agent, API, evaluation (hermetic; scripted model)
docker compose up -d postgres && \
  DATABASE_URL=postgresql://cloudbox:cloudbox-local-only@localhost:5432/cloudbox uv run pytest -m integration
LIVE_TESTS=1 uv run pytest -m live              # against the configured real model
uv run ruff check backend tests && uv run mypy backend
```

Covered scenarios include: relevant first retrieval; poor retrieval → rewritten queries; multiple attempts;
KB gap → web search with external label; account lookups; tool failure; web-search outage with retries;
conflicting documents; prompt injection in a document (blocked by authorization even if the model obeys);
`MAX_AGENT_STEPS` forced finalization; tool budget; missing customer ID → clarification; ambiguous request;
memory across turns; fabricated-citation removal; LLM outage; refusals; API auth, rate limiting, size limits,
security headers, SSE streaming, Front Door guard; pgvector parity, idempotent ingestion, migrations.

## 15. Observability

* **Structured JSON logs** with `request_id`, `session_id`, `execution_id` on every line (Container Apps →
  Log Analytics). Key events: `llm.call` (model, purpose, step, tokens, cost, latency, stop reason, requested
  tools), `tool.call` (tool, status, attempts, latency, error code), `agent.completed` (trajectory, steps,
  retrieval attempts, web use, tokens, cost, latency, grounded, warnings).
* **Application Insights** via OpenTelemetry (requests, dependencies, logs).
* **Prometheus** `/metrics` (agent runs/steps/latency, tool calls/latency, LLM calls/latency/tokens/cost,
  evaluator verdicts, retrieval attempts, guardrail events, rate-limit rejections).
* **Trajectories**: `GET /api/v1/admin/traces/{execution_id}` (admin key) returns actions, not reasoning.
* **Alerts** (Terraform): API 5xx, agent step-limit/timeout/LLM-error spikes, p95 agent latency, share of
  ungrounded answers, Postgres CPU, container restarts.

Example Log Analytics query — trajectories and cost per conversation turn:

```kusto
ContainerAppConsoleLogs_CL
| extend e = parse_json(Log_s) | where tostring(e.event) == "agent.completed"
| project TimeGenerated, session=tostring(e.session_id), trajectory=tostring(e.trajectory),
          latency_s=todouble(e.latency_ms)/1000, cost_usd=todouble(e.cost_usd), grounded=tobool(e.grounded)
```

## 16. Security

Model ≠ security boundary: authorization, validation, budgets and output checks are in code. Highlights:
tool-level authorization with user-provenance checks; untrusted-content handling; PII blocked from web
queries; credential redaction; no chain-of-thought exposure; JWT auth; per-replica + WAF rate limits;
Front Door-only ingress; passwordless Postgres; managed identities and OIDC (no stored cloud secrets);
pip-audit, npm audit, gitleaks, CodeQL, Trivy (images + IaC), TFLint in CI. See [SECURITY.md](SECURITY.md)
and [docs/security.md](docs/security.md).

## 17. Cost considerations

* **Model cost dominates.** Measured: $0.0116 per question for the agent (3.2 model calls, of which the
  Haiku evaluator costs $0.0006) against $0.0049 for plain RAG ([docs/evaluation.md](docs/evaluation.md)).
* **Levers**: the evaluator already runs on Haiku; disable it for low-risk routes; lower `AGENT_EFFORT`;
  cap `MAX_AGENT_STEPS`/`MAX_TOOL_CALLS`; prompt caching of the static system prompt + tools (built in);
  route trivially answerable FAQs to the single-shot path if the benchmark shows parity there.
* **Infrastructure**: dev scales to zero; staging/prod fixed cost is mostly Front Door Premium, the Postgres
  HA pair and warm API replicas ([docs/deployment.md](docs/deployment.md#6-cost-notes-indicative-before-model-usage)).

## 18. Future improvements

* Query decomposition inside the KB tool. A dedicated re-ranker (cross-encoder or a hosted rerank API)
  would only pay off if the evaluator were disabled; the evaluator already re-ranks.
* Front Door → Container Apps Private Link; private endpoint for ACR; NAT gateway / Azure Firewall egress allow-list for the model APIs.
* Human hand-off tool (create ticket) and action tools (initiate refund) behind explicit user confirmation.
* Online evaluation: sample production traces into the judge; drift alerts on groundedness and resolution.
* Redis-backed distributed rate limiting and session locks; streaming token output to the UI.
* Larger, adversarially generated benchmark with multiple annotators; confidence intervals across repeated runs.
* Terraform: azurerm 5.x upgrade, policy-as-code (Azure Policy) and cost budgets/alerts.

---

Built as a reference implementation. All company, customer and web data in this repository is fictional.
