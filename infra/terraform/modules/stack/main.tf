# One CloudBox environment on Azure. Environments (dev/staging/prod) call this module with different
# sizing and safety settings; nothing environment-specific is hard-coded here.
#
# Azure hosts the application (Container Apps, PostgreSQL + pgvector, Front Door + WAF, Key Vault, ACR,
# monitoring). The AI models are called over HTTPS: Claude via the Anthropic API and OpenAI embeddings,
# with their API keys stored in this environment's Key Vault.

data "azurerm_client_config" "current" {}

data "azurerm_resource_group" "this" {
  name = var.resource_group_name
}

resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

locals {
  name       = "cloudbox-${var.environment}"
  short      = "cbx${var.environment}"
  suffix     = random_string.suffix.result
  location   = coalesce(var.location, data.azurerm_resource_group.this.location)
  public_url = var.enable_front_door ? "https://${module.frontdoor[0].endpoint_host}" : "https://${module.container_apps.ui_fqdn}"
  tags = merge(var.tags, {
    project     = "cloudbox-support-agent"
    environment = var.environment
    managed_by  = "terraform"
  })
}

# ------------------------------------------------------------------ identity

resource "azurerm_user_assigned_identity" "app" {
  name                = "id-${local.name}-app"
  location            = local.location
  resource_group_name = var.resource_group_name
  tags                = local.tags
}

# ------------------------------------------------------------------ foundation

module "network" {
  source                = "../network"
  name                  = local.name
  location              = local.location
  resource_group_name   = var.resource_group_name
  address_space         = var.vnet_address_space
  ingress_source_prefix = var.enable_front_door ? "AzureFrontDoor.Backend" : "Internet"
  tags                  = local.tags
}

module "monitoring" {
  source              = "../monitoring"
  name                = local.name
  location            = local.location
  resource_group_name = var.resource_group_name
  retention_in_days   = var.log_retention_days
  daily_quota_gb      = var.log_daily_quota_gb
  alert_emails        = var.alert_emails
  tags                = local.tags
}

module "keyvault" {
  source                        = "../keyvault"
  name                          = "kv-${local.short}-${local.suffix}"
  location                      = local.location
  resource_group_name           = var.resource_group_name
  tenant_id                     = data.azurerm_client_config.current.tenant_id
  purge_protection_enabled      = var.key_vault_purge_protection
  public_network_access_enabled = true
  network_default_action        = var.key_vault_network_default_action
  allowed_ip_ranges             = var.key_vault_allowed_ip_ranges
  secret_officer_principal_ids  = var.key_vault_secret_officers
  vnet_id                       = module.network.vnet_id
  private_endpoint_subnet_id    = module.network.private_endpoints_subnet_id
  log_analytics_workspace_id    = module.monitoring.log_analytics_workspace_id
  tags                          = local.tags
}

module "registry" {
  source                     = "../registry"
  name                       = "acr${local.short}${local.suffix}"
  location                   = local.location
  resource_group_name        = var.resource_group_name
  sku                        = var.acr_sku
  zone_redundancy_enabled    = var.zone_redundancy_enabled
  log_analytics_workspace_id = module.monitoring.log_analytics_workspace_id
  tags                       = local.tags
}

module "postgres" {
  source                       = "../postgres"
  name                         = "psql-${local.short}-${local.suffix}"
  location                     = local.location
  resource_group_name          = var.resource_group_name
  tenant_id                    = data.azurerm_client_config.current.tenant_id
  vnet_id                      = module.network.vnet_id
  subnet_id                    = module.network.postgres_subnet_id
  sku_name                     = var.postgres_sku
  storage_mb                   = var.postgres_storage_mb
  backup_retention_days        = var.postgres_backup_retention_days
  geo_redundant_backup_enabled = var.postgres_geo_redundant_backup
  high_availability            = var.postgres_high_availability
  admin_principal_id           = azurerm_user_assigned_identity.app.principal_id
  admin_principal_name         = azurerm_user_assigned_identity.app.name
  log_analytics_workspace_id   = module.monitoring.log_analytics_workspace_id
  tags                         = local.tags
}

# ------------------------------------------------------------------ app identity permissions

resource "azurerm_role_assignment" "app_acr_pull" {
  scope                = module.registry.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

resource "azurerm_role_assignment" "app_kv_secrets_user" {
  scope                = module.keyvault.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

# ------------------------------------------------------------------ application

module "frontdoor" {
  count                      = var.enable_front_door ? 1 : 0
  source                     = "../frontdoor"
  name                       = local.name
  resource_group_name        = var.resource_group_name
  endpoint_name              = "${local.name}-${local.suffix}"
  sku_name                   = var.front_door_sku
  waf_policy_name            = "waf${local.short}${local.suffix}"
  waf_mode                   = var.waf_mode
  api_rate_limit_per_minute  = var.waf_api_rate_limit_per_minute
  api_host                   = module.container_apps.api_fqdn
  web_host                   = module.container_apps.ui_fqdn
  log_analytics_workspace_id = module.monitoring.log_analytics_workspace_id
  tags                       = local.tags
}

module "container_apps" {
  source                     = "../container_apps"
  name                       = local.name
  location                   = local.location
  resource_group_name        = var.resource_group_name
  subnet_id                  = module.network.apps_subnet_id
  log_analytics_workspace_id = module.monitoring.log_analytics_workspace_id
  zone_redundancy_enabled    = var.zone_redundancy_enabled
  identity_id                = azurerm_user_assigned_identity.app.id
  registry_login_server      = module.registry.login_server
  api_image                  = var.api_image != "" ? var.api_image : "${module.registry.login_server}/cloudbox-support-api:${var.image_tag}"
  ui_image                   = var.ui_image != "" ? var.ui_image : "${module.registry.login_server}/cloudbox-support-ui:${var.image_tag}"
  cpu                        = var.api_cpu
  memory                     = var.api_memory
  min_replicas               = var.api_min_replicas
  max_replicas               = var.api_max_replicas
  key_vault_uri              = module.keyvault.vault_uri
  # Model API keys are always Key Vault references; extra opt-in secrets (web search, admin) are merged in.
  app_secrets = merge({
    ANTHROPIC_API_KEY = "anthropic-api-key"
    OPENAI_API_KEY    = "openai-api-key"
  }, var.app_secrets)
  job_secrets                     = { OPENAI_API_KEY = "openai-api-key" } # ingestion only needs the embedding API
  appinsights_connection_string   = module.monitoring.application_insights_connection_string
  seed_demo_customers             = var.seed_demo_customers
  ui_proxies_api                  = !var.enable_front_door
  concurrent_requests_per_replica = 20
  tags                            = local.tags

  # Empty values (e.g. unset JWT settings) are omitted rather than passed as "".
  environment_variables = { for k, v in merge({
    ENVIRONMENT                      = var.environment
    LOG_LEVEL                        = "INFO"
    LOG_JSON                         = "true"
    AZURE_CLIENT_ID                  = azurerm_user_assigned_identity.app.client_id # Postgres Entra token
    LLM_PROVIDER                     = var.llm_provider
    AGENT_MODEL                      = var.agent_model
    AGENT_EFFORT                     = var.agent_effort
    EVALUATOR_PROVIDER               = var.llm_provider
    EVALUATOR_MODEL                  = var.evaluator_model
    EMBEDDING_PROVIDER               = "openai"
    EMBEDDING_MODEL                  = var.embedding_model
    EMBEDDING_DIM                    = tostring(var.embedding_dim)
    VECTOR_STORE                     = "pgvector"
    SESSION_STORE                    = "postgres"
    CUSTOMER_STORE                   = "postgres"
    TRACE_STORE                      = "postgres"
    DATABASE_URL                     = "postgresql://${azurerm_user_assigned_identity.app.name}@${module.postgres.fqdn}:5432/${module.postgres.database_name}?sslmode=require"
    DATABASE_AUTH                    = "entra"
    WEB_SEARCH_PROVIDER              = var.web_search_provider
    AUTH_MODE                        = var.auth_mode
    JWT_JWKS_URL                     = var.jwt_jwks_url
    JWT_ISSUER                       = var.jwt_issuer
    JWT_AUDIENCE                     = var.jwt_audience
    ALLOW_UNVERIFIED_CUSTOMER_LOOKUP = tostring(var.allow_unverified_customer_lookup)
    RATE_LIMIT_PER_MINUTE            = "30"
    TRUST_FORWARDED_FOR              = "true"
    FRONT_DOOR_ID                    = var.enable_front_door ? module.frontdoor[0].front_door_id : ""
    CORS_ALLOWED_ORIGINS             = "[]" # browser traffic is same-origin (Front Door or the UI's /api proxy)
    MAX_AGENT_STEPS                  = "8"
    MAX_TOOL_CALLS                   = "12"
    EXPOSE_TRACE_IN_RESPONSE         = tostring(var.expose_trace_in_response)
  }, var.extra_app_settings) : k => v if v != null && v != "" }

  depends_on = [
    azurerm_role_assignment.app_acr_pull,
    azurerm_role_assignment.app_kv_secrets_user,
  ]
}
