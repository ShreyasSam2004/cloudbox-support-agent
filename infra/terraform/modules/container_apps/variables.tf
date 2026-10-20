variable "name" {
  type = string
}

variable "location" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "subnet_id" {
  type = string
}

variable "log_analytics_workspace_id" {
  type = string
}

variable "zone_redundancy_enabled" {
  type    = bool
  default = false
}

variable "identity_id" {
  description = "User-assigned managed identity used for image pulls, Key Vault references, Postgres and model access."
  type        = string
}

variable "registry_login_server" {
  type = string
}

variable "api_image" {
  description = "Fully qualified API image reference (CI passes an immutable tag)."
  type        = string
}

variable "ui_image" {
  description = "Fully qualified UI image reference."
  type        = string
}

variable "cpu" {
  type    = number
  default = 0.5
}

variable "memory" {
  type    = string
  default = "1Gi"
}

variable "min_replicas" {
  description = "0 allows scale-to-zero (dev); production keeps warm replicas."
  type        = number
  default     = 1
}

variable "max_replicas" {
  type    = number
  default = 5
}

variable "concurrent_requests_per_replica" {
  type    = number
  default = 20
}

variable "environment_variables" {
  description = "Non-secret configuration."
  type        = map(string)
}

variable "key_vault_uri" {
  type = string
}

variable "app_secrets" {
  description = <<-EOT
    Opt-in Key Vault references: environment variable name → Key Vault secret name. A secret must
    exist in the vault before it is listed here (operators create it with `az keyvault secret set`);
    until then the app runs without it (web search disabled, admin endpoint off).
  EOT
  type        = map(string)
  default     = {}
}

variable "job_secrets" {
  description = "Key Vault references for the ingestion job: env var name → secret name."
  type        = map(string)
  default     = {}
}

variable "appinsights_connection_string" {
  type      = string
  sensitive = true
}

variable "ui_proxies_api" {
  description = "Without Front Door, the UI container reverse-proxies /api/* to the API app (same-origin UI)."
  type        = bool
  default     = false
}

variable "seed_demo_customers" {
  description = "Load mock customer accounts (dev/staging demo data only)."
  type        = bool
  default     = false
}

variable "tags" {
  type    = map(string)
  default = {}
}
