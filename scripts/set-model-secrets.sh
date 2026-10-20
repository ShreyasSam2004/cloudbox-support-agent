#!/usr/bin/env bash
# Store the model API keys from your local .env in an environment's Azure Key Vault.
#
#   ./scripts/set-model-secrets.sh <key-vault-name>
#
# Requirements: Azure CLI logged in (`az login`), your object ID listed in key_vault_secret_officers,
# and (staging/prod) your IP in key_vault_allowed_ip_ranges. Values are passed to `az` through
# owner-only temporary files, never on the command line, and are never printed.
set -euo pipefail

vault="${1:?usage: $0 <key-vault-name>}"
env_file="${ENV_FILE:-.env}"

read_key() {
  # Prefer an exported variable; otherwise read KEY=value from the .env file.
  local name="$1" value="${!1:-}"
  if [[ -z "$value" && -f "$env_file" ]]; then
    value="$(grep -E "^${name}=" "$env_file" | tail -n 1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^["'"'"']//' -e 's/["'"'"']$//')"
  fi
  [[ -n "$value" ]] || { echo "error: $name is not set (export it or add it to $env_file)" >&2; exit 1; }
  printf '%s' "$value"
}

tmp="$(mktemp -d)"
chmod 700 "$tmp"
trap 'rm -rf "$tmp"' EXIT

for pair in "ANTHROPIC_API_KEY:anthropic-api-key" "OPENAI_API_KEY:openai-api-key"; do
  env_name="${pair%%:*}"
  secret_name="${pair##*:}"
  read_key "$env_name" > "$tmp/$secret_name"
  chmod 600 "$tmp/$secret_name"
  az keyvault secret set --vault-name "$vault" --name "$secret_name" \
    --file "$tmp/$secret_name" --encoding utf-8 --content-type text/plain --output none
  echo "stored $secret_name in $vault"
done
