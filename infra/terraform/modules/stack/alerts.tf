# Alerts. Log-based alerts query the structured JSON logs the API writes (Container Apps → Log Analytics)
# and the request telemetry Application Insights collects; metric alerts cover the platform.

locals {
  agent_logs = <<-KQL
    ContainerAppConsoleLogs_CL
    | where ContainerAppName_s == "${module.container_apps.api_name}"
    | extend e = parse_json(Log_s)
  KQL
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "api_5xx" {
  name                 = "alert-${local.name}-api-5xx"
  resource_group_name  = var.resource_group_name
  location             = local.location
  description          = "API returned 5xx responses."
  severity             = 1
  evaluation_frequency = "PT5M"
  window_duration      = "PT5M"
  scopes               = [module.monitoring.application_insights_id]
  tags                 = local.tags

  criteria {
    query                   = "requests | where toint(resultCode) >= 500"
    time_aggregation_method = "Count"
    operator                = "GreaterThan"
    threshold               = 5

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [module.monitoring.action_group_id]
  }
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "agent_boundaries" {
  # ContainerAppConsoleLogs_CL is created when the app first logs, i.e. after this rule on a new workspace.
  skip_query_validation = true
  name                  = "alert-${local.name}-agent-boundaries"
  resource_group_name   = var.resource_group_name
  location              = local.location
  description           = "Agent runs hitting step/time limits or LLM errors (model outage, runaway loops)."
  severity              = 2
  evaluation_frequency  = "PT15M"
  window_duration       = "PT15M"
  scopes                = [module.monitoring.log_analytics_workspace_id]
  tags                  = local.tags

  criteria {
    query                   = <<-KQL
      ${local.agent_logs}
      | where tostring(e.event) == "agent.completed"
      | where tostring(e.stop_reason) in ("max_steps", "timeout", "llm_error")
    KQL
    time_aggregation_method = "Count"
    operator                = "GreaterThan"
    threshold               = 5

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [module.monitoring.action_group_id]
  }
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "agent_latency" {
  # ContainerAppConsoleLogs_CL is created when the app first logs, i.e. after this rule on a new workspace.
  skip_query_validation = true
  name                  = "alert-${local.name}-agent-latency-p95"
  resource_group_name   = var.resource_group_name
  location              = local.location
  description           = "p95 end-to-end agent latency above the SLO."
  severity              = 3
  evaluation_frequency  = "PT15M"
  window_duration       = "PT30M"
  scopes                = [module.monitoring.log_analytics_workspace_id]
  tags                  = local.tags

  criteria {
    query                   = <<-KQL
      ${local.agent_logs}
      | where tostring(e.event) == "agent.completed"
      | summarize p95 = percentile(todouble(e.latency_ms), 95)
    KQL
    time_aggregation_method = "Maximum"
    metric_measure_column   = "p95"
    operator                = "GreaterThan"
    threshold               = var.agent_latency_slo_ms

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [module.monitoring.action_group_id]
  }
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "ungrounded_answers" {
  # ContainerAppConsoleLogs_CL is created when the app first logs, i.e. after this rule on a new workspace.
  skip_query_validation = true
  name                  = "alert-${local.name}-ungrounded-answers"
  resource_group_name   = var.resource_group_name
  location              = local.location
  description           = "Share of answers without valid citations is unusually high (possible retrieval or model regression)."
  severity              = 3
  evaluation_frequency  = "PT1H"
  window_duration       = "PT1H"
  scopes                = [module.monitoring.log_analytics_workspace_id]
  tags                  = local.tags

  criteria {
    query                   = <<-KQL
      ${local.agent_logs}
      | where tostring(e.event) == "agent.completed" and tostring(e.response_type) == "answer"
      | summarize ungrounded_pct = 100.0 * countif(tobool(e.grounded) == false) / count()
    KQL
    time_aggregation_method = "Maximum"
    metric_measure_column   = "ungrounded_pct"
    operator                = "GreaterThan"
    threshold               = 10

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [module.monitoring.action_group_id]
  }
}

resource "azurerm_monitor_metric_alert" "postgres_cpu" {
  name                = "alert-${local.name}-postgres-cpu"
  resource_group_name = var.resource_group_name
  scopes              = [module.postgres.id]
  description         = "PostgreSQL CPU above 80%."
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT15M"
  tags                = local.tags

  criteria {
    metric_namespace = "Microsoft.DBforPostgreSQL/flexibleServers"
    metric_name      = "cpu_percent"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = 80
  }

  action {
    action_group_id = module.monitoring.action_group_id
  }
}

resource "azurerm_monitor_metric_alert" "api_restarts" {
  name                = "alert-${local.name}-api-restarts"
  resource_group_name = var.resource_group_name
  scopes              = [module.container_apps.api_id]
  description         = "API container restarts (crash loop or failing probes)."
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT15M"
  tags                = local.tags

  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "RestartCount"
    aggregation      = "Total"
    operator         = "GreaterThan"
    threshold        = 3
  }

  action {
    action_group_id = module.monitoring.action_group_id
  }
}
