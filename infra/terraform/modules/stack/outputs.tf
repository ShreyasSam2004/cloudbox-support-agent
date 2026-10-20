output "frontend_url" {
  value = local.public_url
}

output "api_url" {
  value = "${local.public_url}/api/v1"
}

output "container_app_name" {
  value = module.container_apps.api_name
}

output "ingest_job_name" {
  value = module.container_apps.ingest_job_name
}

output "acr_login_server" {
  value = module.registry.login_server
}

output "acr_name" {
  value = module.registry.name
}

output "key_vault_name" {
  value = module.keyvault.name
}

output "postgres_fqdn" {
  value = module.postgres.fqdn
}

output "app_identity_client_id" {
  value = azurerm_user_assigned_identity.app.client_id
}
