# Log Analytics + workspace-based Application Insights + an action group for alerts.

resource "azurerm_log_analytics_workspace" "this" {
  name                = "log-${var.name}"
  location            = var.location
  resource_group_name = var.resource_group_name
  sku                 = "PerGB2018"
  retention_in_days   = var.retention_in_days
  daily_quota_gb      = var.daily_quota_gb
  tags                = var.tags
}

resource "azurerm_application_insights" "this" {
  name                = "appi-${var.name}"
  location            = var.location
  resource_group_name = var.resource_group_name
  workspace_id        = azurerm_log_analytics_workspace.this.id
  application_type    = "web"
  retention_in_days   = var.retention_in_days
  tags                = var.tags
}

resource "azurerm_monitor_action_group" "this" {
  name                = "ag-${var.name}"
  resource_group_name = var.resource_group_name
  short_name          = substr(replace("cbx${var.name}", "-", ""), 0, 12)
  tags                = var.tags

  dynamic "email_receiver" {
    for_each = toset(var.alert_emails)
    content {
      name                    = "email-${replace(email_receiver.value, "/[^a-zA-Z0-9]/", "-")}"
      email_address           = email_receiver.value
      use_common_alert_schema = true
    }
  }
}
