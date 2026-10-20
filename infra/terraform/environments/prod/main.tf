provider "azurerm" {
  subscription_id     = var.subscription_id
  storage_use_azuread = true

  features {
    key_vault {
      purge_soft_delete_on_destroy    = false
      recover_soft_deleted_key_vaults = true
    }
    resource_group {
      prevent_deletion_if_contains_resources = true
    }
  }
}

module "stack" {
  source = "../../modules/stack"

  environment         = "prod"
  resource_group_name = var.resource_group_name
  vnet_address_space  = "10.42.0.0/16"
  alert_emails        = var.alert_emails
  image_tag           = var.image_tag
  api_image           = var.api_image
  ui_image            = var.ui_image
  app_secrets         = var.app_secrets

  key_vault_secret_officers = var.key_vault_secret_officers

  # Production: zone redundancy, HA database with geo-redundant backups, Premium WAF with managed rule
  # sets, warm replicas, strict identity (JWT only, no unverified lookups), no demo data, no traces in
  # API responses (operators use the admin trace endpoint and Log Analytics instead).
  zone_redundancy_enabled          = true
  log_retention_days               = 90
  postgres_sku                     = "GP_Standard_D4ds_v5"
  postgres_storage_mb              = 131072
  postgres_backup_retention_days   = 35
  postgres_geo_redundant_backup    = true
  postgres_high_availability       = true
  key_vault_purge_protection       = true
  key_vault_network_default_action = "Deny"
  acr_sku                          = "Premium"
  front_door_sku                   = "Premium_AzureFrontDoor"
  waf_mode                         = "Prevention"
  waf_api_rate_limit_per_minute    = 60
  api_cpu                          = 1
  api_memory                       = "2Gi"
  api_min_replicas                 = 2
  api_max_replicas                 = 10
  seed_demo_customers              = false
  auth_mode                        = "jwt"
  jwt_jwks_url                     = var.jwt_jwks_url
  jwt_issuer                       = var.jwt_issuer
  jwt_audience                     = var.jwt_audience
  allow_unverified_customer_lookup = false
  expose_trace_in_response         = false
  web_search_provider              = "tavily"

  llm_provider    = var.llm_provider
  agent_model     = var.agent_model
  evaluator_model = var.evaluator_model

  tags = { cost_center = "support-ai", criticality = "high" }
}
