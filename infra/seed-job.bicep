param location string = resourceGroup().location
param environmentId string
param registryServer string
param seedIdentityId string
param seedIdentityClientId string
param postgresHost string
param postgresAdmin string
param adminSecretUrl string
param readerSecretUrl string
param apiImage string
param modelSubscriptionId string
param modelRegions string

resource job 'Microsoft.App/jobs@2024-03-01' = {
  name: 'mc-seed'
  location: location
  tags: { project: 'model-catalogue', managedBy: 'model-catalogue' }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${seedIdentityId}': {} }
  }
  properties: {
    environmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 900
      replicaRetryLimit: 0
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: [{ server: registryServer, identity: seedIdentityId }]
      secrets: [
        { name: 'postgres-admin', keyVaultUrl: adminSecretUrl, identity: seedIdentityId }
        { name: 'postgres-reader', keyVaultUrl: readerSecretUrl, identity: seedIdentityId }
      ]
    }
    template: {
      containers: [{
        name: 'seed'
        image: apiImage
        command: ['python', '-m', 'app.features.ingestion.cloud']
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: [
          { name: 'PGHOST', value: postgresHost }
          { name: 'PGDATABASE', value: 'catalogue' }
          { name: 'PGUSER', value: postgresAdmin }
          { name: 'PGPASSWORD', secretRef: 'postgres-admin' }
          { name: 'PGSSLMODE', value: 'verify-full' }
          { name: 'PGSSLROOTCERT', value: '/etc/ssl/certs/ca-certificates.crt' }
          { name: 'CATALOGUE_READER_PASSWORD', secretRef: 'postgres-reader' }
          { name: 'AZURE_SUBSCRIPTION_ID', value: modelSubscriptionId }
          { name: 'AZURE_REGIONS', value: modelRegions }
          { name: 'AZURE_MANAGED_IDENTITY_CLIENT_ID', value: seedIdentityClientId }
        ]
      }]
    }
  }
}

output jobName string = job.name
