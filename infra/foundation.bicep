param location string = resourceGroup().location
param operatorPrincipalId string
@secure()
param administratorPassword string
@secure()
param readerPassword string

var suffix = uniqueString(resourceGroup().id)
var tags = { project: 'model-catalogue', environment: 'development', managedBy: 'model-catalogue' }
var administratorName = 'catalogue_admin'

resource network 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-model-catalogue'
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: ['10.77.0.0/16'] }
    subnets: [
      {
        name: 'container-apps'
        properties: {
          addressPrefix: '10.77.0.0/24'
          delegations: [{
            name: 'container-apps'
            properties: { serviceName: 'Microsoft.App/environments' }
          }]
        }
      }
      {
        name: 'postgres'
        properties: {
          addressPrefix: '10.77.1.0/28'
          serviceEndpoints: [{ service: 'Microsoft.Storage' }]
          delegations: [{
            name: 'postgres'
            properties: { serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers' }
          }]
        }
      }
      {
        name: 'private-endpoints'
        properties: {
          addressPrefix: '10.77.2.0/27'
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
}

resource postgresDns 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'mc${suffix}.postgres.database.azure.com'
  location: 'global'
  tags: tags
}

resource dnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: postgresDns
  name: 'catalogue'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: network.id }
  }
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-model-catalogue'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: json('0.1') }
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-model-catalogue'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
  }
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-model-catalogue'
  location: location
  tags: tags
  properties: {
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
    vnetConfiguration: {
      infrastructureSubnetId: '${network.id}/subnets/container-apps'
      internal: false
    }
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'acrmc${suffix}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource uiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-model-catalogue-ui'
  location: location
  tags: tags
}
resource apiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-model-catalogue-api'
  location: location
  tags: tags
}
resource seedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-model-catalogue-seed'
  location: location
  tags: tags
}

var pullPrincipals = [
  uiIdentity.properties.principalId
  apiIdentity.properties.principalId
  seedIdentity.properties.principalId
]
var pullIdentityIds = [uiIdentity.id, apiIdentity.id, seedIdentity.id]
resource pullRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for index in range(0, 3): {
  name: guid(registry.id, pullIdentityIds[index], 'AcrPull')
  scope: registry
  properties: {
    principalId: pullPrincipals[index]
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  }
}]

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kvmc${suffix}'
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    enablePurgeProtection: true
    publicNetworkAccess: 'Disabled'
    enabledForTemplateDeployment: true
  }
}
module vaultNetwork 'vault-network.bicep' = {
  name: 'catalogue-vault-network'
  params: {
    location: location
    networkName: network.name
    vaultName: vault.name
  }
}
resource adminSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'postgres-admin'
  properties: { value: administratorPassword }
}
resource readerSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'postgres-reader'
  properties: { value: readerPassword }
}
resource operatorSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, operatorPrincipalId, 'Key Vault Secrets Officer')
  scope: vault
  properties: {
    principalId: operatorPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7')
  }
}
resource seedSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, seedIdentity.id, 'Key Vault Secrets User')
  scope: vault
  properties: {
    principalId: seedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
  }
}
resource apiSecretReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(readerSecret.id, apiIdentity.id, 'Key Vault Secrets User')
  scope: readerSecret
  properties: {
    principalId: apiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
  }
}

module modelReadRole 'model-reader.bicep' = {
  name: 'catalogue-model-read-role'
  scope: subscription()
  params: {
    seedPrincipalId: seedIdentity.properties.principalId
    applicationScope: resourceGroup().id
  }
}

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: 'pgmc${suffix}'
  location: location
  tags: tags
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: '17'
    administratorLogin: administratorName
    administratorLoginPassword: administratorPassword
    storage: { storageSizeGB: 32, autoGrow: 'Enabled' }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
    network: {
      delegatedSubnetResourceId: '${network.id}/subnets/postgres'
      privateDnsZoneArmResourceId: postgresDns.id
      publicNetworkAccess: 'Disabled'
    }
  }
  dependsOn: [dnsLink, adminSecret, readerSecret]
}
resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: 'catalogue'
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
}

output configuration object = {
  environmentName: environment.name
  environmentId: environment.id
  registryName: registry.name
  registryServer: registry.properties.loginServer
  postgresName: postgres.name
  postgresHost: postgres.properties.fullyQualifiedDomainName
  postgresAdmin: administratorName
  vaultName: vault.name
  adminSecretUrl: '${vault.properties.vaultUri}secrets/postgres-admin'
  readerSecretUrl: '${vault.properties.vaultUri}secrets/postgres-reader'
  uiIdentityId: uiIdentity.id
  apiIdentityId: apiIdentity.id
  seedIdentityId: seedIdentity.id
  seedIdentityClientId: seedIdentity.properties.clientId
  logsName: logs.name
}
