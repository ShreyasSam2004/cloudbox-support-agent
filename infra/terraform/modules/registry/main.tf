# Azure Container Registry. Admin user disabled: pulls use the app's managed identity (AcrPull),
# pushes use the CI identity. Premium enables zone redundancy and untagged-manifest retention.

resource "azurerm_container_registry" "this" {
  name                          = var.name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  sku                           = var.sku
  admin_enabled                 = false
  anonymous_pull_enabled        = false
  public_network_access_enabled = true
  zone_redundancy_enabled       = var.sku == "Premium" ? var.zone_redundancy_enabled : false
  retention_policy_in_days      = var.sku == "Premium" ? 14 : null
  tags                          = var.tags
}

resource "azurerm_monitor_diagnostic_setting" "registry" {
  name                       = "diag-${var.name}"
  target_resource_id         = azurerm_container_registry.this.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log {
    category_group = "audit"
  }

  enabled_metric {
    category = "AllMetrics"
  }
}
