# Key Vault (RBAC, soft delete, optional purge protection) reachable from the VNet via a private
# endpoint. Terraform manages only the vault (control plane); secret values are written out of band by
# operators (`az keyvault secret set`), so no secret value ever passes through code, CI or state.

resource "azurerm_key_vault" "this" {
  name                          = var.name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  tenant_id                     = var.tenant_id
  sku_name                      = "standard"
  rbac_authorization_enabled    = true
  purge_protection_enabled      = var.purge_protection_enabled
  soft_delete_retention_days    = 90
  public_network_access_enabled = var.public_network_access_enabled
  tags                          = var.tags

  network_acls {
    default_action = var.network_default_action
    bypass         = "AzureServices"
    ip_rules       = var.allowed_ip_ranges
  }
}

resource "azurerm_private_dns_zone" "vault" {
  name                = "privatelink.vaultcore.azure.net"
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "vault" {
  name                  = "link-${var.name}"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.vault.name
  virtual_network_id    = var.vnet_id
  registration_enabled  = false
  tags                  = var.tags
}

resource "azurerm_private_endpoint" "vault" {
  name                = "pe-${var.name}"
  location            = var.location
  resource_group_name = var.resource_group_name
  subnet_id           = var.private_endpoint_subnet_id
  tags                = var.tags

  private_service_connection {
    name                           = "psc-${var.name}"
    private_connection_resource_id = azurerm_key_vault.this.id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "vault"
    private_dns_zone_ids = [azurerm_private_dns_zone.vault.id]
  }
}

# Operators who write secret values (e.g. the model API keys) out of band.
resource "azurerm_role_assignment" "secret_officers" {
  for_each             = toset(var.secret_officer_principal_ids)
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = each.value
}

resource "azurerm_monitor_diagnostic_setting" "vault" {
  name                       = "diag-${var.name}"
  target_resource_id         = azurerm_key_vault.this.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log {
    category_group = "audit"
  }

  enabled_metric {
    category = "AllMetrics"
  }
}
