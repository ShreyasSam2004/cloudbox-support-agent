# Deployment (Azure)

Azure hosts the whole application, and everything in Azure is created by Terraform (`infra/terraform`).
The AI models are not Azure resources: the app calls Claude through the Anthropic API and OpenAI's
embeddings API over HTTPS, with both API keys stored in the environment's Key Vault.

Nothing is provisioned by hand except two one-time admin actions that Terraform cannot do for itself:
running the bootstrap stack and writing secret *values* (the model API keys) into Key Vault.

## 1. Topology (per environment)

| Layer | Azure service | Notes |
|------|---------------|-------|
| Edge | **Front Door** (Standard in dev, Premium in staging/prod) + **WAF policy** | TLS, HTTPS redirect, security headers rule set, per-IP rate limit on `/api/*`, method allow-list, Microsoft DefaultRuleSet 2.1 + Bot Manager (Premium), access + WAF logs to Log Analytics. `/api/*` → API app, `/*` → UI app |
| Compute | **Container Apps** environment (workload profiles, VNet-integrated, zone-redundant in prod) | `api` (FastAPI agent), `ui` (nginx + React build), `ingest` job (migrations, optional demo seed, KB ingestion) |
| Identity | **User-assigned managed identity** | ACR pull, Key Vault references, Postgres (Entra). No passwords |
| Data | **PostgreSQL Flexible Server 16** + `vector` extension | Private access only (delegated subnet + private DNS), Entra-only auth (password auth disabled), TLS ≥ 1.2 enforced, HA zone-redundant + geo-redundant backups in prod |
| Models | *(external APIs, not Azure resources)* | Claude via the Anthropic API (agent + retrieval evaluator); OpenAI `text-embedding-3-small`. Called over HTTPS from Container Apps |
| Secrets | **Key Vault** (RBAC, soft delete, purge protection in staging/prod, private endpoint, network default Deny in staging/prod) | Holds the Anthropic and OpenAI API keys (required), plus optional web-search and admin keys. Values are written out of band, never by Terraform |
| Images | **Container Registry** (Basic → Premium) | Admin user disabled; Premium in prod: zone redundancy + untagged retention |
| Observability | **Log Analytics** + workspace-based **Application Insights**, action group, alerts | See `README.md#observability` |
| Network | VNet with `apps`, `postgres`, `private-endpoints` subnets; NSG on apps subnet admits HTTPS only from the `AzureFrontDoor.Backend` service tag | Plus `X-Azure-FDID` verification in the API |

### Without Front Door (`enable_front_door = false`)

Azure **Free Trial** subscriptions cannot create Front Door ("Free Trial & Student Account is forbidden for
Azure front door resources"), so dev runs without it: the UI and API Container Apps are reached directly over
their managed HTTPS endpoints (`*.azurecontainerapps.io`), the apps-subnet NSG admits HTTPS from the internet,
and the UI container reverse-proxies `/api/*` to the API so the browser still talks to a single origin.
There is no WAF in this mode — the app's own rate limiting, validation and authorization still apply. Turn
Front Door on (pay-as-you-go subscription) before exposing an environment publicly.

### Environment differences

| Setting | dev | staging | prod |
|---------|-----|---------|------|
| API replicas | 0–2 (scale to zero) | 1–3 | 2–10, 1 vCPU / 2 GiB |
| Postgres | B1ms, 7-day backups | D2ds_v5, 14 days | D4ds_v5, 128 GB, HA, geo-redundant, 35 days |
| Front Door / WAF | off (`enable_front_door = false`, see above) | Premium / Prevention | Premium / Prevention, 60 req/min/IP |
| Key Vault network | Allow | Deny (+ private endpoint) | Deny (+ private endpoint) |
| Auth | `none` (demo) | JWT | JWT |
| Unverified customer lookups | allowed (demo) | no | no |
| Demo customer data | seeded | seeded | none |
| Traces in API responses | yes | yes | no |
| Log retention | 30 days, 2 GB/day cap | 30 days | 90 days |

## 2. One-time bootstrap (platform admin)

```bash
cd infra/terraform/bootstrap
az login
terraform init
terraform apply -var subscription_id=<sub-id> -var github_repository=<owner>/<repo>
```

Creates: the remote-state storage account (Entra-only, versioned, soft delete, ZRS), `rg-cloudbox-{dev,staging,prod}`,
and per environment two OIDC identities federated with GitHub environments:

| Identity | GitHub environment | Roles (scoped to that env's RG) |
|----------|-------------------|--------------------------------|
| `ci-<env>-plan` | `<env>-plan` | Reader, custom "list Container Apps secrets" (needed to refresh during plan), Storage Blob Data **Reader** on state |
| `ci-<env>-apply` | `<env>` (prod: required reviewers) | Contributor, Role Based Access Control Administrator, Storage Blob Data **Contributor** on state |

Then:

1. Put `state_storage_account` into each `environments/*/backend.hcl` (or pass `-backend-config`).
2. In GitHub, create environments `dev-plan`, `dev`, `staging-plan`, `staging`, `prod-plan`, `prod`;
   set variable `AZURE_CLIENT_ID` on each from `ci_client_ids`; set repository variables
   `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `TF_STATE_STORAGE_ACCOUNT`. Add required reviewers to `prod`.
3. Add your Entra object ID (`az ad signed-in-user show --query id -o tsv`) to `key_vault_secret_officers`
   in each environment's `terraform.tfvars`, so you are allowed to store the model API keys.

## 3. First deployment of an environment

The Container Apps read the model API keys from Key Vault at start-up, so on the very first deployment the
vault (and its secrets) must exist before the apps. Run once per environment:

```bash
cd infra/terraform/environments/dev
terraform init -backend-config=backend.hcl

# 1. Create the network and Key Vault (with your secrets-officer role) first
terraform apply -var subscription_id=<sub> -target=module.stack.module.keyvault

# 2. Copy ANTHROPIC_API_KEY and OPENAI_API_KEY from your local .env into the vault
#    (values are never printed or put on a command line)
(cd ../../../.. && ./scripts/set-model-secrets.sh <key_vault_name>)

# 3. Create everything else. Before CI has pushed images, use a public placeholder image:
terraform apply -var subscription_id=<sub> \
  -var api_image=mcr.microsoft.com/k8se/quickstart:latest \
  -var ui_image=mcr.microsoft.com/k8se/quickstart:latest
```

…then push the real images (the deploy workflow does this) and apply again without the overrides. Later
deployments are a single plan/apply from CI. To rotate a model key, run the script again and restart the
API revision so it picks up the new secret version.

### Optional secrets

```bash
az keyvault secret set --vault-name <key_vault_name> --name tavily-api-key --file <file-containing-key>
az keyvault secret set --vault-name <key_vault_name> --name admin-api-key --value "$(openssl rand -hex 32)"
```

Then opt the API into them (tfvars):

```hcl
app_secrets = {
  TAVILY_API_KEY = "tavily-api-key"
  ADMIN_API_KEY  = "admin-api-key"
}
```

Until a secret is referenced the app runs without it (web search disabled, admin trace endpoint off).
In staging/prod the vault denies public network access; run these commands from a machine whose egress IP
is in `key_vault_allowed_ip_ranges`, from inside the VNet, or through a just-in-time firewall exception.

### One-command dev deploy / teardown (workstation)

`scripts/azure-dev.sh` automates sections 2–3 for the dev environment, exactly as it was first deployed:

```bash
az login                         # once
./scripts/azure-dev.sh up        # bootstrap if needed → Key Vault + ACR → store model keys → build, verify
                                 # and push images → full apply → ingestion job → prints the app URL
./scripts/azure-dev.sh down      # asks for confirmation, then deletes the dev environment
```

`down` keeps the empty `rg-cloudbox-dev` resource group and the Terraform state storage (a few cents a
month at most), so the next `up` skips the bootstrap. Key Vault and Log Analytics remain soft-deleted for a
while after `down`; that costs nothing, and the next `up` gets new random-suffixed names.

## 4. Continuous deployment (`.github/workflows/deploy.yml`)

```text
push to main
  └─ CI (lint, types, tests, pgvector tests, frontend, pip-audit, npm audit, gitleaks, CodeQL,
         Docker build + Trivy, Terraform fmt/validate/tflint/Trivy)
       └─ build API + UI images once (tag = commit SHA)
            └─ dev:     plan (read-only identity) → apply saved plan → push images → ingest job → smoke test
                 └─ staging: same
                      └─ prod:    plan → ⏸ required reviewers → apply → ingest → smoke test
```

* The apply job applies **exactly** the saved plan artifact from its plan job.
* Images are built once and promoted by tag; each environment has its own registry.
* No workflow runs `terraform destroy`. Postgres databases have `prevent_destroy`; resource groups have
  `prevent_deletion_if_contains_resources`; Key Vaults have purge protection in staging/prod.
* `eval.yml` runs the benchmark on demand / weekly (Anthropic + OpenAI keys from the `eval` GitHub environment's secrets) and uploads the report.

## 5. Operations

* **Roll back**: re-run the deploy workflow for a previous commit (images are immutable by SHA).
* **Re-ingest knowledge base**: `az containerapp job start -n <ingest_job_name> -g rg-cloudbox-<env>`.
* **Inspect a conversation**: take `execution_id` from the response/log, then
  `GET /api/v1/admin/traces/<id>` with `X-Admin-Key`, or query Log Analytics (see README).
* **Retention**: `cloudbox prune --days 30` (run as a scheduled job) removes old sessions and traces.

## 6. Cost notes (indicative; model API usage is billed separately by Anthropic/OpenAI)

dev scales to zero and uses Basic/Standard SKUs, so its fixed cost is dominated by Front Door Standard,
the B1ms Postgres server and Log Analytics ingestion (capped at 2 GB/day). prod's fixed cost is dominated
by Front Door Premium + WAF, the HA D4ds_v5 Postgres pair and two warm API replicas. Model usage is
variable and measured per question by the benchmark (`docs/evaluation.md`); the levers are the evaluator
model, `AGENT_EFFORT`, `MAX_AGENT_STEPS`, and prompt caching (the static prompt + tools are cached).
