targetScope = 'subscription'

param seedPrincipalId string
param applicationScope string

resource modelReader 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: guid(subscription().id, applicationScope, 'model-catalogue-reader')
  properties: {
    roleName: 'Model catalogue metadata reader ${uniqueString(applicationScope)}'
    description: 'Discover subscription regions and read model metadata; no deployment or inference permissions.'
    type: 'CustomRole'
    assignableScopes: [subscription().id]
    permissions: [{
      actions: [
        'Microsoft.CognitiveServices/locations/models/read'
        'Microsoft.Resources/subscriptions/locations/read'
        'Microsoft.Resources/subscriptions/providers/read'
      ]
      notActions: []
      dataActions: []
      notDataActions: []
    }]
  }
}

resource assignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, seedPrincipalId, modelReader.id)
  properties: {
    roleDefinitionId: modelReader.id
    principalId: seedPrincipalId
    principalType: 'ServicePrincipal'
  }
}
