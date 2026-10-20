variable "name" {
  description = "Globally unique vault name (3-24 chars)."
  type        = string

  validation {
    condition     = can(regex("^[a-zA-Z][a-zA-Z0-9-]{1,22}[a-zA-Z0-9]$", var.name))
    error_message = "Key Vault names must be 3-24 alphanumerics/hyphens and start with a letter."
  }
}

variable "location" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "tenant_id" {
  type = string
}

variable "purge_protection_enabled" {
  type    = bool
  default = true
}

variable "public_network_access_enabled" {
  description = "Data-plane access from public networks (still subject to network_acls and RBAC)."
  type        = bool
  default     = true
}

variable "network_default_action" {
  description = "Deny in staging/prod (access via private endpoint + allowed_ip_ranges for the deploy runner)."
  type        = string
  default     = "Deny"

  validation {
    condition     = contains(["Allow", "Deny"], var.network_default_action)
    error_message = "network_default_action must be Allow or Deny."
  }
}

variable "allowed_ip_ranges" {
  description = "CIDRs allowed to reach the data plane (e.g. the deployment runner)."
  type        = list(string)
  default     = []
}

variable "vnet_id" {
  type = string
}

variable "private_endpoint_subnet_id" {
  type = string
}

variable "secret_officer_principal_ids" {
  description = "Entra object IDs of operators allowed to write secret values."
  type        = list(string)
  default     = []
}

variable "log_analytics_workspace_id" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}
