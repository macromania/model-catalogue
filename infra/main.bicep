targetScope = 'subscription'

param resourceGroupName string
param location string
param operatorPrincipalId string
@secure()
param administratorPassword string
@secure()
param readerPassword string

resource group 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: { project: 'model-catalogue', managedBy: 'model-catalogue', environment: 'development' }
}

module core 'foundation.bicep' = {
  name: 'model-catalogue-foundation'
  scope: group
  params: {
    location: location
    operatorPrincipalId: operatorPrincipalId
    administratorPassword: administratorPassword
    readerPassword: readerPassword
  }
}

output foundation object = core.outputs.configuration
