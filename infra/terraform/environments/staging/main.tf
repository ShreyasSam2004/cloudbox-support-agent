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

  environment         = "staging"
  resource_group_name = var.resource_group_name
  vnet_address_space  = "10.41.0.0/16"
  alert_emails        = var.alert_emails
  image_tag           = var.image_tag
  api_image           = var.api_image
  ui_image            = var.ui_image
  app_secrets         = var.app_secrets

  key_vault_secret_officers = var.key_vault_secret_officers

  # Staging mirrors production security (JWT auth, private data plane, WAF in Prevention) on smaller,
  # non-redundant SKUs, and runs against the mock customer dataset for end-to-end tests.
  log_retention_days               = 30
  postgres_sku                     = "GP_Standard_D2ds_v5"
  postgres_backup_retention_days   = 14
  key_vault_purge_protection       = true
  key_vault_network_default_action = "Deny"
  acr_sku                          = "Standard"
  front_door_sku                   = "Premium_AzureFrontDoor"
  waf_mode                         = "Prevention"
  api_min_replicas                 = 1
  api_max_replicas                 = 3
  seed_demo_customers              = true
  auth_mode                        = "jwt"
  jwt_jwks_url                     = var.jwt_jwks_url
  jwt_issuer                       = var.jwt_issuer
  jwt_audience                     = var.jwt_audience
  allow_unverified_customer_lookup = false
  expose_trace_in_response         = true
  web_search_provider              = "tavily"

  llm_provider    = var.llm_provider
  agent_model     = var.agent_model
  evaluator_model = var.evaluator_model

  tags = { cost_center = "support-ai" }
}
