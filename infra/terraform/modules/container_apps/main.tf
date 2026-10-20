# Container Apps environment (VNet-integrated) with:
#   * api    — FastAPI agent service
#   * ui     — nginx serving the static React build
#   * ingest — on-demand job: migrations, optional demo seed, knowledge-base ingestion
# All three run under one user-assigned managed identity (ACR pull, Key Vault references, Postgres via
# Entra ID). Secrets — including the model API keys — are Key Vault references resolved by the platform.

locals {
  secret_refs = { for env_name, secret_name in var.app_secrets : env_name => {
    name = replace(lower(secret_name), "_", "-")
    id   = "${var.key_vault_uri}secrets/${secret_name}"
  } }
  job_secret_refs = { for env_name, secret_name in var.job_secrets : env_name => {
    name = replace(lower(secret_name), "_", "-")
    id   = "${var.key_vault_uri}secrets/${secret_name}"
  } }
}

resource "azurerm_container_app_environment" "this" {
  name                       = "cae-${var.name}"
  location                   = var.location
  resource_group_name        = var.resource_group_name
  log_analytics_workspace_id = var.log_analytics_workspace_id
  infrastructure_subnet_id   = var.subnet_id
  zone_redundancy_enabled    = var.zone_redundancy_enabled
  tags                       = var.tags

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
}

# ------------------------------------------------------------------ API

resource "azurerm_container_app" "api" {
  name                         = "ca-${var.name}-api"
  container_app_environment_id = azurerm_container_app_environment.this.id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }

  registry {
    server   = var.registry_login_server
    identity = var.identity_id
  }

  dynamic "secret" {
    for_each = local.secret_refs
    content {
      name                = secret.value.name
      key_vault_secret_id = secret.value.id
      identity            = var.identity_id
    }
  }

  secret {
    name  = "appinsights-connection-string"
    value = var.appinsights_connection_string
  }

  ingress {
    external_enabled           = true
    target_port                = 8000
    transport                  = "auto"
    allow_insecure_connections = false

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    container {
      name   = "api"
      image  = var.api_image
      cpu    = var.cpu
      memory = var.memory

      dynamic "env" {
        for_each = var.environment_variables
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.secret_refs
        content {
          name        = env.key
          secret_name = env.value.name
        }
      }

      env {
        name        = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        secret_name = "appinsights-connection-string"
      }

      startup_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/healthz"
        interval_seconds        = 5
        failure_count_threshold = 30
      }

      liveness_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/healthz"
        interval_seconds        = 15
        failure_count_threshold = 3
      }

      readiness_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/readyz"
        interval_seconds        = 15
        failure_count_threshold = 3
      }
    }

    http_scale_rule {
      name                = "concurrent-requests"
      concurrent_requests = tostring(var.concurrent_requests_per_replica)
    }
  }
}

# ------------------------------------------------------------------ UI

resource "azurerm_container_app" "ui" {
  name                         = "ca-${var.name}-ui"
  container_app_environment_id = azurerm_container_app_environment.this.id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }

  registry {
    server   = var.registry_login_server
    identity = var.identity_id
  }

  ingress {
    external_enabled           = true
    target_port                = 8080
    transport                  = "auto"
    allow_insecure_connections = false

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = 3

    container {
      name   = "ui"
      image  = var.ui_image
      cpu    = 0.25
      memory = "0.5Gi"

      dynamic "env" {
        for_each = var.ui_proxies_api ? [1] : []
        content {
          name  = "API_UPSTREAM"
          value = "https://${azurerm_container_app.api.ingress[0].fqdn}"
        }
      }

      liveness_probe {
        transport = "HTTP"
        port      = 8080
        path      = "/"
      }
    }

    http_scale_rule {
      name                = "concurrent-requests"
      concurrent_requests = "100"
    }
  }
}

# ------------------------------------------------------------------ ingestion job

# Triggered by CI after each deployment (`az containerapp job start`). Idempotent: only changed
# documents are re-embedded.
resource "azurerm_container_app_job" "ingest" {
  name                         = "caj-${var.name}-ingest"
  location                     = var.location
  resource_group_name          = var.resource_group_name
  container_app_environment_id = azurerm_container_app_environment.this.id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 1800
  replica_retry_limit          = 1
  tags                         = var.tags

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }

  registry {
    server   = var.registry_login_server
    identity = var.identity_id
  }

  dynamic "secret" {
    for_each = local.job_secret_refs
    content {
      name                = secret.value.name
      key_vault_secret_id = secret.value.id
      identity            = var.identity_id
    }
  }

  template {
    container {
      name    = "ingest"
      image   = var.api_image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["/bin/sh", "-c"]
      args    = [var.seed_demo_customers ? "cloudbox seed-customers && cloudbox ingest" : "cloudbox ingest"]

      dynamic "env" {
        for_each = var.environment_variables
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.job_secret_refs
        content {
          name        = env.key
          secret_name = env.value.name
        }
      }
    }
  }
}
