# One-time bootstrap (run by a platform admin with local state, then keep the state file safe or
# migrate it). Creates:
#   * the Terraform remote-state storage account (Entra-only auth, versioning, soft delete)
#   * one resource group per environment
#   * per environment, two GitHub Actions OIDC identities (no client secrets anywhere):
#       ci-<env>-plan   Reader on the env RG + read access to state  (pull requests, plan)
#       ci-<env>-apply  Contributor + RBAC Administrator on the env RG + state write (apply; prod gated)

provider "azurerm" {
  subscription_id     = var.subscription_id
  storage_use_azuread = true
  features {}
}

data "azurerm_client_config" "current" {}

resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

locals {
  tags = { project = "cloudbox-support-agent", managed_by = "terraform", stack = "bootstrap" }
}

# ------------------------------------------------------------------ remote state

resource "azurerm_resource_group" "state" {
  name     = "rg-cloudbox-tfstate"
  location = var.location
  tags     = local.tags
}

resource "azurerm_storage_account" "state" {
  name                              = "stcbxtfstate${random_string.suffix.result}"
  resource_group_name               = azurerm_resource_group.state.name
  location                          = azurerm_resource_group.state.location
  account_tier                      = "Standard"
  account_replication_type          = "ZRS"
  account_kind                      = "StorageV2"
  min_tls_version                   = "TLS1_2"
  https_traffic_only_enabled        = true
  allow_nested_items_to_be_public   = false
  shared_access_key_enabled         = false
  default_to_oauth_authentication   = true
  infrastructure_encryption_enabled = true
  tags                              = local.tags

  blob_properties {
    versioning_enabled = true

    delete_retention_policy {
      days = 30
    }

    container_delete_retention_policy {
      days = 30
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

# The admin running bootstrap (and deploying from a workstation) needs data-plane access to the state,
# because the storage account accepts only Entra ID auth.
resource "azurerm_role_assignment" "admin_state" {
  scope                = azurerm_storage_account.state.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_storage_container" "state" {
  name                  = "tfstate"
  storage_account_id    = azurerm_storage_account.state.id
  container_access_type = "private"
}

# ------------------------------------------------------------------ environments

resource "azurerm_resource_group" "env" {
  for_each = toset(var.environments)
  name     = "rg-cloudbox-${each.key}"
  location = var.location
  tags     = merge(local.tags, { environment = each.key })
}

locals {
  # CI identities are only created when a GitHub repository is given; without one, deploy from a workstation.
  identities = var.github_repository == "" ? {} : merge([
    for env in var.environments : {
      "${env}-plan"  = { env = env, kind = "plan" }
      "${env}-apply" = { env = env, kind = "apply" }
    }
  ]...)

  # GitHub OIDC subjects: plans run in "<env>-plan" environments (no approval), applies in "<env>"
  # environments (prod has required reviewers configured in GitHub).
  github_subjects = {
    for key, id in local.identities :
    key => "repo:${var.github_repository}:environment:${id.kind == "plan" ? "${id.env}-plan" : id.env}"
  }

  role_assignments = merge(
    { for key, id in local.identities : "${key}-rg-reader" => { identity = key, scope = azurerm_resource_group.env[id.env].id, role = "Reader" } if id.kind == "plan" },
    { for key, id in local.identities : "${key}-rg-contributor" => { identity = key, scope = azurerm_resource_group.env[id.env].id, role = "Contributor" } if id.kind == "apply" },
    { for key, id in local.identities : "${key}-rg-rbac-admin" => { identity = key, scope = azurerm_resource_group.env[id.env].id, role = "Role Based Access Control Administrator" } if id.kind == "apply" },
    { for key, id in local.identities : "${key}-state" => { identity = key, scope = azurerm_storage_container.state.id, role = id.kind == "apply" ? "Storage Blob Data Contributor" : "Storage Blob Data Reader" } },
  )
}

# Reader cannot call listSecrets, which the provider needs to refresh Container Apps/Jobs during plan.
# This narrow custom role grants exactly that — nothing else beyond Reader.
resource "azurerm_role_definition" "plan_extras" {
  name        = "CloudBox Terraform Plan (list Container Apps secrets)"
  scope       = "/subscriptions/${var.subscription_id}"
  description = "Lets read-only CI plan jobs refresh Container Apps and Jobs."

  permissions {
    actions = [
      "Microsoft.App/containerApps/listSecrets/action",
      "Microsoft.App/jobs/listSecrets/action",
    ]
  }

  assignable_scopes = [for rg in azurerm_resource_group.env : rg.id]
}

resource "azurerm_role_assignment" "plan_extras" {
  for_each           = { for key, id in local.identities : key => id if id.kind == "plan" }
  scope              = azurerm_resource_group.env[each.value.env].id
  role_definition_id = azurerm_role_definition.plan_extras.role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.ci[each.key].principal_id
}

resource "azurerm_user_assigned_identity" "ci" {
  for_each            = local.identities
  name                = "id-cloudbox-ci-${each.key}"
  location            = azurerm_resource_group.state.location
  resource_group_name = azurerm_resource_group.state.name
  tags                = merge(local.tags, { environment = each.value.env, purpose = "ci-${each.value.kind}" })
}

resource "azurerm_federated_identity_credential" "github" {
  for_each            = local.identities
  name                = "github-${each.key}"
  resource_group_name = azurerm_resource_group.state.name
  parent_id           = azurerm_user_assigned_identity.ci[each.key].id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = "https://token.actions.githubusercontent.com"
  subject             = local.github_subjects[each.key]
}

resource "azurerm_role_assignment" "ci" {
  for_each             = local.role_assignments
  scope                = each.value.scope
  role_definition_name = each.value.role
  principal_id         = azurerm_user_assigned_identity.ci[each.value.identity].principal_id
}
