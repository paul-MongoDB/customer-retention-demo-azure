// Retail Customer Retention Demo - Shared Infrastructure
// Deploys: Managed Identity, ACR, Log Analytics, Container Apps Environment
// Container Apps are deployed separately by apps.bicep (avoids race condition
// where the environment is not fully provisioned before apps try to deploy).

targetScope = 'resourceGroup'

// ── Parameters ──

@description('Azure region for all resources')
param location string = resourceGroup().location

@description('Prefix used to name all resources (e.g. "leafy-demo")')
param environmentName string

// ── Naming ──

var prefix = environmentName
var acrName = replace('${prefix}acr', '-', '')
var logAnalyticsName = '${prefix}-logs'
var containerEnvName = '${prefix}-env'
var managedIdentityName = '${prefix}-identity'

// ── User-Assigned Managed Identity ──
// Backend uses this to authenticate with Microsoft Foundry

resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: managedIdentityName
  location: location
}

// ── Container Registry ──

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
  }
}

// ── Log Analytics (required by Container Apps) ──

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// ── Container Apps Environment ──

resource containerEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: containerEnvName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// ── Outputs ──

@description('ACR login server for docker push')
output acrLoginServer string = acr.properties.loginServer

@description('ACR name (without .azurecr.io)')
output acrName string = acr.name

@description('Container Apps Environment resource ID')
output containerEnvId string = containerEnv.id

@description('Managed Identity resource ID')
output managedIdentityId string = managedIdentity.id

@description('Managed Identity client ID (assign Cognitive Services User role to this)')
output managedIdentityClientId string = managedIdentity.properties.clientId

@description('Managed Identity principal ID (for role assignments)')
output managedIdentityPrincipalId string = managedIdentity.properties.principalId
