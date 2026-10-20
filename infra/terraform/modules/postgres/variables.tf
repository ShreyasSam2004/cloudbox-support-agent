variable "name" {
  description = "Globally unique server name."
  type        = string
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

variable "vnet_id" {
  type = string
}

variable "subnet_id" {
  description = "Subnet delegated to Microsoft.DBforPostgreSQL/flexibleServers."
  type        = string
}

variable "sku_name" {
  type    = string
  default = "B_Standard_B1ms"
}

variable "storage_mb" {
  type    = number
  default = 32768
}

variable "backup_retention_days" {
  type    = number
  default = 7

  validation {
    condition     = var.backup_retention_days >= 7 && var.backup_retention_days <= 35
    error_message = "backup_retention_days must be between 7 and 35."
  }
}

variable "geo_redundant_backup_enabled" {
  type    = bool
  default = false
}

variable "high_availability" {
  type    = bool
  default = false
}

variable "database_name" {
  type    = string
  default = "cloudbox"
}

variable "admin_principal_id" {
  description = "Object (principal) ID of the managed identity that administers the server."
  type        = string
}

variable "admin_principal_name" {
  description = "Display name of that identity (used as the Postgres role name)."
  type        = string
}

variable "log_analytics_workspace_id" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}
