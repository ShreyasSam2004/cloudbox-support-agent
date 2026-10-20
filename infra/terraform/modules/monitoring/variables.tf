variable "name" {
  type = string
}

variable "location" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "retention_in_days" {
  type    = number
  default = 30

  validation {
    condition     = var.retention_in_days >= 30 && var.retention_in_days <= 730
    error_message = "retention_in_days must be between 30 and 730."
  }
}

variable "daily_quota_gb" {
  description = "Log ingestion cap per day (-1 = unlimited). A cap protects dev budgets."
  type        = number
  default     = -1
}

variable "alert_emails" {
  type    = list(string)
  default = []
}

variable "tags" {
  type    = map(string)
  default = {}
}
