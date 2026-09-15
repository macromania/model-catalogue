param location string = resourceGroup().location
param networkName string = 'vnet-model-catalogue'
param vaultName string

resource network 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: networkName
}
resource vault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: vaultName
}
resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: network
  name: 'private-endpoints'
  properties: {
    addressPrefix: '10.77.2.0/27'
    privateEndpointNetworkPolicies: 'Disabled'
  }
}
resource zone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.vaultcore.azure.net'
  location: 'global'
  tags: { project: 'model-catalogue', managedBy: 'model-catalogue' }
}
resource link 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: zone
  name: 'catalogue'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: network.id }
  }
}
resource endpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-model-catalogue-vault'
  location: location
  tags: { project: 'model-catalogue', managedBy: 'model-catalogue' }
  properties: {
    subnet: { id: subnet.id }
    privateLinkServiceConnections: [{
      name: 'catalogue-vault'
      properties: {
        privateLinkServiceId: vault.id
        groupIds: ['vault']
      }
    }]
  }
}
resource dnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: endpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [{ name: 'vault', properties: { privateDnsZoneId: zone.id } }]
  }
}
