variable "subscription_id" {
  type = string
}

variable "location" {
  type    = string
  default = "eastus2"
}

variable "environments" {
  type    = list(string)
  default = ["dev", "staging", "prod"]
}

variable "github_repository" {
  description = "owner/repo allowed to assume the CI identities via OIDC; empty = no CI identities (workstation deploys)."
  type        = string
  default     = ""

  validation {
    condition     = var.github_repository == "" || can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must be empty or look like owner/repo."
  }
}
