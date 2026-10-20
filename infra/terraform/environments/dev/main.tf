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

  environment         = "dev"
  resource_group_name = var.resource_group_name
  alert_emails        = var.alert_emails
  image_tag           = var.image_tag
  api_image           = var.api_image
  ui_image            = var.ui_image
  app_secrets         = var.app_secrets

  key_vault_secret_officers = var.key_vault_secret_officers

  # Dev: cheapest viable footprint, scale to zero, demo data and demo identity mode.
  log_retention_days               = 30
  log_daily_quota_gb               = 2
  postgres_sku                     = "B_Standard_B1ms"
  postgres_backup_retention_days   = 7
  key_vault_purge_protection       = false
  key_vault_network_default_action = "Allow"
  acr_sku                          = "Basic"
  enable_front_door                = false # Free Trial subscriptions cannot create Front Door
  front_door_sku                   = "Standard_AzureFrontDoor"
  waf_mode                         = "Detection"
  api_min_replicas                 = 0
  api_max_replicas                 = 2
  seed_demo_customers              = true
  auth_mode                        = "none"
  allow_unverified_customer_lookup = true
  expose_trace_in_response         = true
  web_search_provider              = "tavily"

  llm_provider    = var.llm_provider
  agent_model     = var.agent_model
  evaluator_model = var.evaluator_model

  tags = { cost_center = "support-ai" }
}
