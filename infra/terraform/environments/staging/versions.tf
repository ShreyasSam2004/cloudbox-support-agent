terraform {
  required_version = ">= 1.10.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.10"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }

  # Remote state in Azure Storage (created by ../../bootstrap) with Entra ID auth and blob-lease locking.
  # Values are supplied with: terraform init -backend-config=backend.hcl
  backend "azurerm" {}
}
