output "environment_id" {
  value = azurerm_container_app_environment.this.id
}

output "api_id" {
  value = azurerm_container_app.api.id
}

output "api_name" {
  value = azurerm_container_app.api.name
}

output "api_fqdn" {
  value = azurerm_container_app.api.ingress[0].fqdn
}

output "ingest_job_name" {
  value = azurerm_container_app_job.ingest.name
}

output "ui_fqdn" {
  value = azurerm_container_app.ui.ingress[0].fqdn
}
