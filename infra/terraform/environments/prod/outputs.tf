output "frontend_url" {
  value = module.stack.frontend_url
}

output "api_url" {
  value = module.stack.api_url
}

output "container_app_name" {
  value = module.stack.container_app_name
}

output "ingest_job_name" {
  value = module.stack.ingest_job_name
}

output "acr_login_server" {
  value = module.stack.acr_login_server
}

output "acr_name" {
  value = module.stack.acr_name
}

output "key_vault_name" {
  value = module.stack.key_vault_name
}
