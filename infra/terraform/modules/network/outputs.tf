output "vnet_id" {
  value = azurerm_virtual_network.this.id
}

output "apps_subnet_id" {
  value = azurerm_subnet.apps.id
}

output "postgres_subnet_id" {
  value = azurerm_subnet.postgres.id
}

output "private_endpoints_subnet_id" {
  value = azurerm_subnet.private_endpoints.id
}
