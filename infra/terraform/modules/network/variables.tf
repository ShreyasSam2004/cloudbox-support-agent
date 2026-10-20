variable "name" {
  description = "Name stem, e.g. cloudbox-dev."
  type        = string
}

variable "location" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "address_space" {
  description = "VNet CIDR (a /16 is carved into /24 subnets)."
  type        = string
  default     = "10.40.0.0/16"

  validation {
    condition     = can(cidrhost(var.address_space, 0)) && tonumber(split("/", var.address_space)[1]) <= 16
    error_message = "address_space must be a valid CIDR of /16 or larger."
  }
}

variable "ingress_source_prefix" {
  description = "Who may reach the Container Apps on 443: AzureFrontDoor.Backend (with Front Door) or Internet."
  type        = string
  default     = "AzureFrontDoor.Backend"
}

variable "tags" {
  type    = map(string)
  default = {}
}
