#!/usr/bin/env bash
# Deploy or remove the CloudBox *dev* environment on Azure from a workstation.
#
#   ./scripts/azure-dev.sh up      # create/refresh everything and print the app URL (~20-30 min first time)
#   ./scripts/azure-dev.sh down    # delete the dev environment (keeps the tiny Terraform state storage)
#
# Requirements: Azure CLI logged in (`az login`), Terraform >= 1.10, Docker running, and ANTHROPIC_API_KEY /
# OPENAI_API_KEY in .env. The one-time bootstrap (Terraform state storage + resource groups) is created
# automatically on the first `up`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_BOOT="$ROOT/infra/terraform/bootstrap"
TF_DEV="$ROOT/infra/terraform/environments/dev"
RG="rg-cloudbox-dev"
LOCATION="${LOCATION:-centralindia}" # Free Trial: PostgreSQL is blocked in several US regions

# Azure CLI on Windows is often installed but not on the Git Bash PATH.
if ! command -v az >/dev/null 2>&1 && [ -d "/c/Program Files/Microsoft SDKs/Azure/CLI2/wbin" ]; then
  export PATH="/c/Program Files/Microsoft SDKs/Azure/CLI2/wbin:$PATH"
fi

log() { printf '\n==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

retry() { # retry <attempts> <sleep-seconds> <command...>  (for Azure RBAC propagation delays)
  local attempts="$1" pause="$2" i
  shift 2
  for ((i = 1; i <= attempts; i++)); do
    if "$@"; then return 0; fi
    [ "$i" -lt "$attempts" ] && { echo "  …not ready yet (attempt $i/$attempts), retrying in ${pause}s"; sleep "$pause"; }
  done
  return 1
}

preflight() {
  command -v az >/dev/null || die "Azure CLI not found"
  command -v terraform >/dev/null || die "terraform not found"
  az account show >/dev/null 2>&1 || die "run 'az login' first"
  SUB="$(az account show --query id -o tsv)"
  export TF_VAR_subscription_id="$SUB"
  echo "subscription: $(az account show --query name -o tsv) ($SUB)"
}

tf_init_dev() {
  retry 12 20 terraform -chdir="$TF_DEV" init -input=false -reconfigure -backend-config=backend.hcl \
    -backend-config="use_oidc=false" -backend-config="use_cli=true" >/dev/null
}

bootstrap() {
  local account
  account="$(az storage account list -g rg-cloudbox-tfstate --query "[0].name" -o tsv 2>/dev/null || true)"
  if [ -z "$account" ]; then
    log "Bootstrap: Terraform state storage + resource group ($LOCATION)"
    terraform -chdir="$TF_BOOT" init -input=false >/dev/null
    terraform -chdir="$TF_BOOT" apply -input=false -auto-approve \
      -var location="$LOCATION" -var 'environments=["dev"]'
    account="$(terraform -chdir="$TF_BOOT" output -raw state_storage_account)"
  fi
  sed -i "s/^storage_account_name = .*/storage_account_name = \"$account\"/" "$TF_DEV/backend.hcl"
  echo "state storage: $account"

  # Let this user store the model API keys in Key Vault (git-ignored, workstation-specific).
  local oid
  oid="$(az ad signed-in-user show --query id -o tsv)"
  printf '# Workstation deploy settings (git-ignored)\nkey_vault_secret_officers = ["%s"]\n' "$oid" \
    > "$TF_DEV/local.auto.tfvars"
}

up() {
  preflight
  command -v docker >/dev/null && docker info >/dev/null 2>&1 || die "start Docker first"
  for key in ANTHROPIC_API_KEY OPENAI_API_KEY; do
    grep -qE "^${key}=.{8,}" "$ROOT/.env" || die "$key is not set in .env"
  done

  bootstrap
  tf_init_dev

  log "Phase 1: network, Key Vault and Container Registry"
  retry 6 20 terraform -chdir="$TF_DEV" apply -input=false -auto-approve \
    -target=module.stack.module.keyvault -target=module.stack.module.registry
  local vault registry server
  vault="$(az keyvault list -g "$RG" --query "[0].name" -o tsv)"
  registry="$(az acr list -g "$RG" --query "[0].name" -o tsv)"
  server="$(az acr show -n "$registry" --query loginServer -o tsv)"

  log "Storing the model API keys in $vault"
  (cd "$ROOT" && retry 12 20 bash scripts/set-model-secrets.sh "$vault")

  local tag
  tag="dev-$(date +%Y%m%d-%H%M%S)"
  log "Building and pushing images ($tag)"
  docker build -q -t "cloudbox-support-api:$tag" "$ROOT" >/dev/null
  docker build -q -t "cloudbox-support-ui:$tag" "$ROOT/frontend" >/dev/null
  # Guard against stale code in the image (the project wheel must be rebuilt from the current sources).
  local probe=backend/agent/loop.py image_hash local_hash
  image_hash="$(MSYS_NO_PATHCONV=1 docker run --rm --entrypoint python "cloudbox-support-api:$tag" -c \
    "import hashlib,backend,pathlib;print(hashlib.sha256((pathlib.Path(backend.__file__).parent.parent/'$probe').read_bytes()).hexdigest())")"
  local_hash="$(sha256sum "$ROOT/$probe" | cut -d' ' -f1)"
  [ "$image_hash" = "$local_hash" ] || die "image does not contain the current $probe"
  retry 6 10 az acr login -n "$registry" >/dev/null
  for image in cloudbox-support-api cloudbox-support-ui; do
    docker tag "$image:$tag" "$server/$image:$tag"
    docker push -q "$server/$image:$tag"
  done

  log "Phase 2: everything else (Container Apps, PostgreSQL, monitoring)"
  retry 3 30 terraform -chdir="$TF_DEV" apply -input=false -auto-approve -var "image_tag=$tag"

  log "Ingestion (migrations, demo customers, knowledge base)"
  local job execution status=""
  job="$(terraform -chdir="$TF_DEV" output -raw ingest_job_name)"
  execution="$(az containerapp job start -n "$job" -g "$RG" --query name -o tsv)"
  for _ in $(seq 1 90); do
    status="$(az containerapp job execution show -n "$job" -g "$RG" --job-execution-name "$execution" \
      --query properties.status -o tsv 2>/dev/null || true)"
    [ "$status" = "Succeeded" ] || [ "$status" = "Failed" ] && break
    sleep 10
  done
  [ "$status" = "Succeeded" ] || die "ingestion job ended with status '$status' (see: az containerapp job logs show -n $job -g $RG --execution $execution --container ingest)"

  log "Done"
  echo "App URL: $(terraform -chdir="$TF_DEV" output -raw frontend_url)"
  echo "(the API scales to zero when idle; the first request after a pause can take ~30-60 s)"
}

down() {
  preflight
  printf 'This deletes the CloudBox dev environment in %s (data included). Type "dev" to continue: ' "$RG"
  read -r answer
  [ "$answer" = "dev" ] || die "aborted"
  tf_init_dev
  # The database resource is protected with prevent_destroy; deleting the server removes it anyway.
  terraform -chdir="$TF_DEV" state rm module.stack.module.postgres.azurerm_postgresql_flexible_server_database.app \
    >/dev/null 2>&1 || true
  terraform -chdir="$TF_DEV" apply -destroy -input=false -auto-approve -var "image_tag=unused"
  log "Dev environment removed. Kept: $RG (empty) and the Terraform state storage in rg-cloudbox-tfstate."
}

case "${1:-}" in
  up) up ;;
  down) down ;;
  *) echo "usage: $0 up|down" >&2; exit 2 ;;
esac
