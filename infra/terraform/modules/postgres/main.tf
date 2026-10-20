# PostgreSQL Flexible Server 16 with pgvector:
#   * private access only (delegated subnet + private DNS zone, no public endpoint)
#   * Entra ID authentication only — password auth is disabled, so no DB password exists anywhere
#   * TLS enforced, zone-redundant HA and geo-redundant backups where configured

resource "azurerm_private_dns_zone" "postgres" {
  name                = "${var.name}.private.postgres.database.azure.com"
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "link-${var.name}"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  virtual_network_id    = var.vnet_id
  registration_enabled  = false
  tags                  = var.tags
}

resource "azurerm_postgresql_flexible_server" "this" {
  name                          = var.name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  version                       = "16"
  delegated_subnet_id           = var.subnet_id
  private_dns_zone_id           = azurerm_private_dns_zone.postgres.id
  public_network_access_enabled = false
  sku_name                      = var.sku_name
  storage_mb                    = var.storage_mb
  auto_grow_enabled             = true
  backup_retention_days         = var.backup_retention_days
  geo_redundant_backup_enabled  = var.geo_redundant_backup_enabled
  zone                          = var.high_availability ? "1" : null
  tags                          = var.tags

  authentication {
    active_directory_auth_enabled = true
    password_auth_enabled         = false
    tenant_id                     = var.tenant_id
  }

  dynamic "high_availability" {
    for_each = var.high_availability ? [1] : []
    content {
      mode                      = "ZoneRedundant"
      standby_availability_zone = "2"
    }
  }

  lifecycle {
    ignore_changes = [zone, high_availability[0].standby_availability_zone]
  }

  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgres]
}

# The application's managed identity is the Entra administrator: it runs migrations and owns the
# schema. (A stricter split — a DBA group as admin and a least-privilege app role — is documented
# in docs/security.md.)
resource "azurerm_postgresql_flexible_server_active_directory_administrator" "app" {
  server_name         = azurerm_postgresql_flexible_server.this.name
  resource_group_name = var.resource_group_name
  tenant_id           = var.tenant_id
  object_id           = var.admin_principal_id
  principal_name      = var.admin_principal_name
  principal_type      = "ServicePrincipal"
}

resource "azurerm_postgresql_flexible_server_configuration" "extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.this.id
  value     = "VECTOR"
}

resource "azurerm_postgresql_flexible_server_configuration" "require_tls" {
  name      = "require_secure_transport"
  server_id = azurerm_postgresql_flexible_server.this.id
  value     = "on"
}

resource "azurerm_postgresql_flexible_server_configuration" "min_tls" {
  name      = "ssl_min_protocol_version"
  server_id = azurerm_postgresql_flexible_server.this.id
  value     = "TLSv1.2"
}

resource "azurerm_postgresql_flexible_server_database" "app" {
  name      = var.database_name
  server_id = azurerm_postgresql_flexible_server.this.id
  charset   = "UTF8"
  collation = "en_US.utf8"

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_monitor_diagnostic_setting" "postgres" {
  name                       = "diag-${var.name}"
  target_resource_id         = azurerm_postgresql_flexible_server.this.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log {
    category_group = "allLogs"
  }

  enabled_metric {
    category = "AllMetrics"
  }
}
