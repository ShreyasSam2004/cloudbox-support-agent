output "state_storage_account" {
  description = "Put this in environments/*/backend.hcl."
  value       = azurerm_storage_account.state.name
}

output "tenant_id" {
  value = data.azurerm_client_config.current.tenant_id
}

output "ci_client_ids" {
  description = "Set as AZURE_CLIENT_ID variables on the matching GitHub environments (not secrets)."
  value       = { for k, v in azurerm_user_assigned_identity.ci : k => v.client_id }
}

output "resource_groups" {
  value = { for k, v in azurerm_resource_group.env : k => v.name }
}
