output "profile_id" {
  value = azurerm_cdn_frontdoor_profile.this.id
}

output "front_door_id" {
  description = "Value Front Door sends in X-Azure-FDID; the API rejects requests without it."
  value       = azurerm_cdn_frontdoor_profile.this.resource_guid
}

output "endpoint_host" {
  value = azurerm_cdn_frontdoor_endpoint.this.host_name
}
