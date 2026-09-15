param location string = resourceGroup().location
param environmentId string
param registryServer string
param uiIdentityId string
param apiIdentityId string
param postgresHost string
param readerSecretUrl string
param apiImage string
param uiImage string

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'mc-api'
  location: location
  tags: { project: 'model-catalogue', managedBy: 'model-catalogue' }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${apiIdentityId}': {} }
  }
  properties: {
    environmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: false, targetPort: 18421, transport: 'http', allowInsecure: false }
      registries: [{ server: registryServer, identity: apiIdentityId }]
      secrets: [{ name: 'postgres-reader', keyVaultUrl: readerSecretUrl, identity: apiIdentityId }]
    }
    template: {
      scale: { minReplicas: 1, maxReplicas: 1 }
      containers: [{
        name: 'api'
        image: apiImage
        resources: { cpu: json('0.25'), memory: '0.5Gi' }
        env: [
          { name: 'PGHOST', value: postgresHost }
          { name: 'PGDATABASE', value: 'catalogue' }
          { name: 'PGUSER', value: 'catalogue_reader' }
          { name: 'PGPASSWORD', secretRef: 'postgres-reader' }
          { name: 'PGSSLMODE', value: 'verify-full' }
          { name: 'PGSSLROOTCERT', value: '/etc/ssl/certs/ca-certificates.crt' }
          { name: 'CATALOGUE_INIT_SCHEMA', value: 'false' }
        ]
        probes: [
          { type: 'Startup', httpGet: { path: '/api/health/ready', port: 18421 }, periodSeconds: 2, failureThreshold: 60 }
          { type: 'Readiness', httpGet: { path: '/api/health/ready', port: 18421 }, periodSeconds: 10 }
          { type: 'Liveness', httpGet: { path: '/api/health/live', port: 18421 }, periodSeconds: 30 }
        ]
      }]
    }
  }
}

resource ui 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'mc-ui'
  location: location
  tags: { project: 'model-catalogue', managedBy: 'model-catalogue' }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${uiIdentityId}': {} }
  }
  properties: {
    environmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 18420
        transport: 'http'
        allowInsecure: false
        ipSecurityRestrictions: []
      }
      registries: [{ server: registryServer, identity: uiIdentityId }]
    }
    template: {
      scale: { minReplicas: 1, maxReplicas: 1 }
      containers: [{
        name: 'ui'
        image: uiImage
        resources: { cpu: json('0.25'), memory: '0.5Gi' }
        env: [{ name: 'API_UPSTREAM', value: 'https://${api.properties.configuration.ingress.fqdn}' }]
        probes: [
          { type: 'Startup', httpGet: { path: '/', port: 18420 }, periodSeconds: 2, failureThreshold: 30 }
          { type: 'Readiness', httpGet: { path: '/', port: 18420 }, periodSeconds: 10 }
        ]
      }]
    }
  }
}

output frontendUrl string = 'https://${ui.properties.configuration.ingress.fqdn}'
output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
output frontendName string = ui.name
output apiName string = api.name
