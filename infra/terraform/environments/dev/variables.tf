variable "subscription_id" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "alert_emails" {
  type    = list(string)
  default = []
}

variable "image_tag" {
  description = "API/UI image tag (CI sets TF_VAR_image_tag to the commit SHA)."
  type        = string
  default     = "latest"
}

variable "api_image" {
  description = "Full image reference override, e.g. a public placeholder for the very first apply."
  type        = string
  default     = ""
}

variable "ui_image" {
  type    = string
  default = ""
}

variable "app_secrets" {
  description = "Key Vault references for the API (env var → secret name); add after creating the secret."
  type        = map(string)
  default     = {}
}

variable "llm_provider" {
  type    = string
  default = "anthropic"
}

variable "agent_model" {
  type    = string
  default = "claude-sonnet-5-5"
}

variable "evaluator_model" {
  type    = string
  default = "claude-haiku-5-5"
}

variable "key_vault_secret_officers" {
  description = "Your Entra object ID (az ad signed-in-user show --query id -o tsv) so you can store the model API keys."
  type        = list(string)
  default     = []
}
