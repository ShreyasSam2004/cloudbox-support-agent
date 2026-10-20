# Azure Front Door: single public entry point with TLS, WAF and security headers.
#   /api/*  → Container App (no caching; long timeout for agent responses and SSE)
#   /*      → UI Container App (static assets, cached)
# The app additionally verifies X-Azure-FDID == this profile's resource GUID, and the apps subnet NSG only
# admits the AzureFrontDoor.Backend service tag, so the WAF cannot be bypassed.

locals {
  premium = var.sku_name == "Premium_AzureFrontDoor"
}

resource "azurerm_cdn_frontdoor_profile" "this" {
  name                     = "afd-${var.name}"
  resource_group_name      = var.resource_group_name
  sku_name                 = var.sku_name
  response_timeout_seconds = 240
  tags                     = var.tags
}

resource "azurerm_cdn_frontdoor_endpoint" "this" {
  name                     = var.endpoint_name
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.this.id
  tags                     = var.tags
}

# ------------------------------------------------------------------ origins

resource "azurerm_cdn_frontdoor_origin_group" "api" {
  name                     = "og-api"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.this.id
  session_affinity_enabled = false

  load_balancing {
    sample_size                 = 4
    successful_samples_required = 3
  }

  health_probe {
    path                = "/healthz"
    protocol            = "Https"
    request_type        = "GET"
    interval_in_seconds = 60
  }
}

resource "azurerm_cdn_frontdoor_origin" "api" {
  name                           = "origin-api"
  cdn_frontdoor_origin_group_id  = azurerm_cdn_frontdoor_origin_group.api.id
  enabled                        = true
  host_name                      = var.api_host
  origin_host_header             = var.api_host
  https_port                     = 443
  http_port                      = 80
  certificate_name_check_enabled = true
  priority                       = 1
  weight                         = 1000
}

resource "azurerm_cdn_frontdoor_origin_group" "web" {
  name                     = "og-web"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.this.id
  session_affinity_enabled = false

  load_balancing {
    sample_size                 = 4
    successful_samples_required = 3
  }

  health_probe {
    path                = "/"
    protocol            = "Https"
    request_type        = "HEAD"
    interval_in_seconds = 120
  }
}

resource "azurerm_cdn_frontdoor_origin" "web" {
  name                           = "origin-web"
  cdn_frontdoor_origin_group_id  = azurerm_cdn_frontdoor_origin_group.web.id
  enabled                        = true
  host_name                      = var.web_host
  origin_host_header             = var.web_host
  https_port                     = 443
  http_port                      = 80
  certificate_name_check_enabled = true
  priority                       = 1
  weight                         = 1000
}

# ------------------------------------------------------------------ security headers

resource "azurerm_cdn_frontdoor_rule_set" "security" {
  name                     = "securityheaders"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.this.id
}

resource "azurerm_cdn_frontdoor_rule" "security_headers" {
  name                      = "addsecurityheaders"
  cdn_frontdoor_rule_set_id = azurerm_cdn_frontdoor_rule_set.security.id
  order                     = 1
  behavior_on_match         = "Continue"

  actions {
    response_header_action {
      header_action = "Overwrite"
      header_name   = "Strict-Transport-Security"
      value         = "max-age=31536000; includeSubDomains"
    }
    response_header_action {
      header_action = "Overwrite"
      header_name   = "X-Content-Type-Options"
      value         = "nosniff"
    }
    response_header_action {
      header_action = "Overwrite"
      header_name   = "X-Frame-Options"
      value         = "DENY"
    }
    response_header_action {
      header_action = "Overwrite"
      header_name   = "Referrer-Policy"
      value         = "no-referrer"
    }
    response_header_action {
      header_action = "Overwrite"
      header_name   = "Content-Security-Policy"
      value         = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    }
  }
}

# ------------------------------------------------------------------ routes

resource "azurerm_cdn_frontdoor_route" "api" {
  name                          = "route-api"
  cdn_frontdoor_endpoint_id     = azurerm_cdn_frontdoor_endpoint.this.id
  cdn_frontdoor_origin_group_id = azurerm_cdn_frontdoor_origin_group.api.id
  cdn_frontdoor_origin_ids      = [azurerm_cdn_frontdoor_origin.api.id]
  cdn_frontdoor_rule_set_ids    = [azurerm_cdn_frontdoor_rule_set.security.id]
  enabled                       = true
  patterns_to_match             = ["/api/*"]
  supported_protocols           = ["Http", "Https"]
  https_redirect_enabled        = true
  forwarding_protocol           = "HttpsOnly"
  link_to_default_domain        = true
}

resource "azurerm_cdn_frontdoor_route" "web" {
  name                          = "route-web"
  cdn_frontdoor_endpoint_id     = azurerm_cdn_frontdoor_endpoint.this.id
  cdn_frontdoor_origin_group_id = azurerm_cdn_frontdoor_origin_group.web.id
  cdn_frontdoor_origin_ids      = [azurerm_cdn_frontdoor_origin.web.id]
  cdn_frontdoor_rule_set_ids    = [azurerm_cdn_frontdoor_rule_set.security.id]
  enabled                       = true
  patterns_to_match             = ["/*"]
  supported_protocols           = ["Http", "Https"]
  https_redirect_enabled        = true
  forwarding_protocol           = "HttpsOnly"
  link_to_default_domain        = true

  cache {
    query_string_caching_behavior = "IgnoreQueryString"
    compression_enabled           = true
    content_types_to_compress     = ["text/html", "text/css", "application/javascript", "image/svg+xml"]
  }
}

# ------------------------------------------------------------------ WAF

resource "azurerm_cdn_frontdoor_firewall_policy" "this" {
  name                              = var.waf_policy_name
  resource_group_name               = var.resource_group_name
  sku_name                          = var.sku_name
  enabled                           = true
  mode                              = var.waf_mode
  request_body_check_enabled        = true
  custom_block_response_status_code = 429
  tags                              = var.tags

  # Distributed rate limit per client IP for the API (the app's in-process limiter is per replica).
  custom_rule {
    name                           = "ApiRateLimit"
    enabled                        = true
    priority                       = 10
    type                           = "RateLimitRule"
    rate_limit_duration_in_minutes = 1
    rate_limit_threshold           = var.api_rate_limit_per_minute
    action                         = "Block"

    match_condition {
      match_variable = "RequestUri"
      operator       = "Contains"
      match_values   = ["/api/"]
    }
  }

  # Only POST/GET/OPTIONS are valid against the API.
  custom_rule {
    name     = "ApiMethodAllowList"
    enabled  = true
    priority = 20
    type     = "MatchRule"
    action   = "Block"

    match_condition {
      match_variable = "RequestUri"
      operator       = "Contains"
      match_values   = ["/api/"]
    }

    match_condition {
      match_variable     = "RequestMethod"
      operator           = "Equal"
      negation_condition = true
      match_values       = ["GET", "POST", "OPTIONS"]
    }
  }

  dynamic "managed_rule" {
    for_each = local.premium ? [1] : []
    content {
      type    = "Microsoft_DefaultRuleSet"
      version = "2.1"
      action  = "Block"
    }
  }

  dynamic "managed_rule" {
    for_each = local.premium ? [1] : []
    content {
      type    = "Microsoft_BotManagerRuleSet"
      version = "1.1"
      action  = "Block"
    }
  }
}

resource "azurerm_cdn_frontdoor_security_policy" "this" {
  name                     = "secpol-${var.name}"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.this.id

  security_policies {
    firewall {
      cdn_frontdoor_firewall_policy_id = azurerm_cdn_frontdoor_firewall_policy.this.id

      association {
        patterns_to_match = ["/*"]

        domain {
          cdn_frontdoor_domain_id = azurerm_cdn_frontdoor_endpoint.this.id
        }
      }
    }
  }
}

resource "azurerm_monitor_diagnostic_setting" "frontdoor" {
  name                       = "diag-afd-${var.name}"
  target_resource_id         = azurerm_cdn_frontdoor_profile.this.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log {
    category = "FrontDoorAccessLog"
  }

  enabled_log {
    category = "FrontDoorWebApplicationFirewallLog"
  }

  enabled_metric {
    category = "AllMetrics"
  }
}
