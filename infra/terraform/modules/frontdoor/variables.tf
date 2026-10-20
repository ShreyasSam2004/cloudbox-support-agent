variable "name" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "endpoint_name" {
  description = "Globally unique endpoint name (becomes <name>-<hash>.azurefd.net)."
  type        = string
}

variable "sku_name" {
  description = "Premium enables managed WAF rule sets (OWASP/DRS, bot protection)."
  type        = string
  default     = "Standard_AzureFrontDoor"

  validation {
    condition     = contains(["Standard_AzureFrontDoor", "Premium_AzureFrontDoor"], var.sku_name)
    error_message = "sku_name must be Standard_AzureFrontDoor or Premium_AzureFrontDoor."
  }
}

variable "waf_policy_name" {
  description = "Alphanumeric WAF policy name."
  type        = string
}

variable "waf_mode" {
  type    = string
  default = "Prevention"

  validation {
    condition     = contains(["Detection", "Prevention"], var.waf_mode)
    error_message = "waf_mode must be Detection or Prevention."
  }
}

variable "api_rate_limit_per_minute" {
  description = "Per-client-IP requests per minute to /api/* before WAF blocks."
  type        = number
  default     = 120
}

variable "api_host" {
  description = "Container App FQDN."
  type        = string
}

variable "web_host" {
  description = "UI Container App FQDN."
  type        = string
}

variable "log_analytics_workspace_id" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}
