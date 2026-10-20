# ------------------------------------------------------------------ placement
variable "environment" {
  type = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging or prod."
  }
}

variable "resource_group_name" {
  description = "Pre-created by the bootstrap stack (the CI identity is scoped to it)."
  type        = string
}

variable "location" {
  description = "Defaults to the resource group's location."
  type        = string
  default     = null
}

variable "tags" {
  type    = map(string)
  default = {}
}

# ------------------------------------------------------------------ network & resilience
variable "vnet_address_space" {
  type    = string
  default = "10.40.0.0/16"
}

variable "zone_redundancy_enabled" {
  type    = bool
  default = false
}

# ------------------------------------------------------------------ observability
variable "log_retention_days" {
  type    = number
  default = 30
}

variable "log_daily_quota_gb" {
  type    = number
  default = -1
}

variable "alert_emails" {
  type    = list(string)
  default = []
}

variable "agent_latency_slo_ms" {
  description = "p95 agent latency alert threshold."
  type        = number
  default     = 45000
}

# ------------------------------------------------------------------ data & secrets
variable "postgres_sku" {
  type    = string
  default = "B_Standard_B1ms"
}

variable "postgres_storage_mb" {
  type    = number
  default = 32768
}

variable "postgres_backup_retention_days" {
  type    = number
  default = 7
}

variable "postgres_geo_redundant_backup" {
  type    = bool
  default = false
}

variable "postgres_high_availability" {
  type    = bool
  default = false
}

variable "key_vault_purge_protection" {
  type    = bool
  default = true
}

variable "key_vault_network_default_action" {
  type    = string
  default = "Deny"
}

variable "key_vault_allowed_ip_ranges" {
  description = "Deployment runner egress CIDRs allowed to manage secrets (data plane)."
  type        = list(string)
  default     = []
}

variable "key_vault_secret_officers" {
  description = "Entra object IDs of people/groups who set secret values (model API keys) in Key Vault."
  type        = list(string)
  default     = []
}

variable "acr_sku" {
  type    = string
  default = "Standard"
}

# ------------------------------------------------------------------ edge
variable "enable_front_door" {
  description = "Front Door + WAF in front of the apps. Free Trial subscriptions cannot create Front Door."
  type        = bool
  default     = true
}

variable "front_door_sku" {
  type    = string
  default = "Standard_AzureFrontDoor"
}

variable "waf_mode" {
  type    = string
  default = "Prevention"
}

variable "waf_api_rate_limit_per_minute" {
  type    = number
  default = 120
}

# ------------------------------------------------------------------ application
variable "image_tag" {
  description = "Tag of the API and UI images in this environment's registry (CI passes the git SHA)."
  type        = string
  default     = "latest"
}

variable "api_image" {
  description = "Full API image reference override (first bootstrap apply, before CI has pushed images)."
  type        = string
  default     = ""
}

variable "ui_image" {
  description = "Full UI image reference override."
  type        = string
  default     = ""
}

variable "app_secrets" {
  description = "Extra opt-in Key Vault references for the API (model API keys are always referenced)."
  type        = map(string)
  default     = {}
}

variable "api_cpu" {
  type    = number
  default = 0.5
}

variable "api_memory" {
  type    = string
  default = "1Gi"
}

variable "api_min_replicas" {
  type    = number
  default = 1
}

variable "api_max_replicas" {
  type    = number
  default = 5
}

variable "seed_demo_customers" {
  type    = bool
  default = false
}

variable "llm_provider" {
  description = "Model API used by the agent and the retrieval evaluator."
  type        = string
  default     = "anthropic"

  validation {
    condition     = contains(["anthropic", "openai"], var.llm_provider)
    error_message = "llm_provider must be anthropic or openai."
  }
}

variable "agent_model" {
  type    = string
  default = "claude-sonnet-5-5"
}

variable "agent_effort" {
  type    = string
  default = "medium"
}

variable "evaluator_model" {
  description = "Model for the retrieval evaluator / re-ranker (Haiku: measured ~20x cheaper, same re-ranking quality)."
  type        = string
  default     = "claude-haiku-5-5"
}

variable "embedding_model" {
  type    = string
  default = "text-embedding-3-small"
}

variable "embedding_dim" {
  type    = number
  default = 1536
}

variable "web_search_provider" {
  type    = string
  default = "tavily"
}

variable "auth_mode" {
  type    = string
  default = "jwt"
}

variable "jwt_jwks_url" {
  type    = string
  default = ""
}

variable "jwt_issuer" {
  type    = string
  default = ""
}

variable "jwt_audience" {
  type    = string
  default = ""
}

variable "allow_unverified_customer_lookup" {
  type    = bool
  default = false
}

variable "expose_trace_in_response" {
  type    = bool
  default = false
}

variable "extra_app_settings" {
  description = "Additional non-secret environment variables for the API."
  type        = map(string)
  default     = {}
}
