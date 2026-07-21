// Retail Customer Retention Demo - Container Apps
// Deploys: MCP Server, Backend, and Frontend Container Apps
// Run AFTER main.bicep so the Container Apps Environment is fully provisioned.

targetScope = 'resourceGroup'

// ── Parameters ──

@description('Azure region for all resources')
param location string = resourceGroup().location

@description('Prefix used to name all resources (e.g. "leafy-demo")')
param environmentName string

@description('Container Apps Environment resource ID (output from main.bicep)')
param containerEnvId string

@description('ACR login server (output from main.bicep, e.g. "leafydemoacr.azurecr.io")')
param acrLoginServer string

@description('ACR name without domain (output from main.bicep)')
param acrName string

@description('Managed Identity resource ID (output from main.bicep)')
param managedIdentityId string

@description('Managed Identity client ID (output from main.bicep)')
param managedIdentityClientId string

@secure()
@description('MongoDB Atlas connection string')
param mongodbUri string

@description('Microsoft Foundry project endpoint')
param azureAiProjectEndpoint string

@description('Model deployment name in Microsoft Foundry')
param azureAiModelDeploymentName string

@description('Database name used by the backend and frontend')
param databaseName string

@secure()
@description('Voyage AI API key for embeddings (starts with pa-)')
param voyageApiKey string

@description('Enable MCP server read-only mode (set false if agents need to write NBAs)')
param mcpReadOnlyMode bool = false

@description('Microsoft Fabric REST API base URL')
param fabricApiBase string = 'https://api.fabric.microsoft.com'

@description('Microsoft Fabric workspace ID hosting the churn model (set after the model is registered in Fabric)')
param fabricWorkspaceId string = ''

@description('Microsoft Fabric ML model ID for the churn scorer (set after the model is registered in Fabric)')
param fabricModelId string = ''

// ── Naming ──

var prefix = environmentName
var mcpServerAppName = '${prefix}-mcp-server'
var backendAppName = '${prefix}-backend'
var frontendAppName = '${prefix}-frontend'
var scoringAppName = '${prefix}-scoring'

// ── ACR credentials (looked up by name) ──

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
}

// ── MongoDB MCP Server (Streamable HTTP + Voyage AI) ──
// Uses the official mongodb/mongodb-mcp-server image from Docker Hub.
// VoyageAI embeddings are handled natively by the MCP server -- no separate client needed.

resource mcpServerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: mcpServerAppName
  location: location
  properties: {
    managedEnvironmentId: containerEnvId
    configuration: {
      ingress: {
        external: true
        targetPort: 8080
        transport: 'auto'
      }
      secrets: [
        {
          name: 'mdb-connection-string'
          value: mongodbUri
        }
        {
          name: 'voyage-api-key'
          value: voyageApiKey
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'mcp-server'
          image: 'mongodb/mongodb-mcp-server:latest'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'MDB_MCP_CONNECTION_STRING'
              secretRef: 'mdb-connection-string'
            }
            {
              name: 'MDB_MCP_VOYAGE_API_KEY'
              secretRef: 'voyage-api-key'
            }
            {
              name: 'MDB_MCP_READ_ONLY'
              value: mcpReadOnlyMode ? 'true' : 'false'
            }
            {
              name: 'MDB_MCP_HTTP_PORT'
              value: '8080'
            }
            {
              name: 'MDB_MCP_HTTP_HOST'
              value: '::'
            }
            {
              name: 'MDB_MCP_TRANSPORT'
              value: 'http'
            }
            {
              name: 'MDB_MCP_HTTP_AUTH_MODE'
              value: 'none'
            }
            {
              name: 'MDB_MCP_PREVIEW_FEATURES'
              value: 'search'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
}

// ── Backend Container App (Python/FastAPI) ──

resource backendApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: backendAppName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerEnvId
    configuration: {
      ingress: {
        external: true
        targetPort: 8080
        transport: 'auto'
      }
      registries: [
        {
          server: acrLoginServer
          username: acr.listCredentials().username
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: [
        {
          name: 'acr-password'
          value: acr.listCredentials().passwords[0].value
        }
        {
          name: 'mongodb-uri'
          value: mongodbUri
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'backend'
          image: 'mcr.microsoft.com/k8se/quickstart:latest'  // Placeholder; updated by deploy.ps1 after image push
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'MONGODB_URI'
              secretRef: 'mongodb-uri'
            }
            {
              name: 'MCP_SERVER_URL'
              value: 'https://${mcpServerApp.properties.configuration.ingress.fqdn}/mcp'
            }
            {
              name: 'AZURE_AI_PROJECT_ENDPOINT'
              value: azureAiProjectEndpoint
            }
            {
              name: 'AZURE_AI_MODEL_DEPLOYMENT_NAME'
              value: azureAiModelDeploymentName
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: managedIdentityClientId
            }
            {
              name: 'DATABASE_NAME'
              value: databaseName
            }
            {
              name: 'SCORING_SERVICE_URL'
              value: 'https://${scoringApp.properties.configuration.ingress.fqdn}'
            }
            {
              name: 'FABRIC_ENRICHMENT_ENABLED'
              value: 'false'
            }
          ]
        }
      ]
      scale: {
        // Pinned to 1 so the in-memory Fabric enrichment toggle is global
        // (also correct: a single change-stream owner avoids duplicate processing).
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
}

// ── Frontend Container App (Next.js) ──

resource frontendApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: frontendAppName
  location: location
  properties: {
    managedEnvironmentId: containerEnvId
    configuration: {
      ingress: {
        external: true
        targetPort: 8080
        transport: 'auto'
      }
      registries: [
        {
          server: acrLoginServer
          username: acr.listCredentials().username
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: [
        {
          name: 'acr-password'
          value: acr.listCredentials().passwords[0].value
        }
        {
          name: 'mongodb-uri'
          value: mongodbUri
        }
        {
          name: 'voyage-api-key'
          value: voyageApiKey
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'frontend'
          image: 'mcr.microsoft.com/k8se/quickstart:latest'  // Placeholder; updated by deploy.ps1 after image push
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'MONGODB_URI'
              secretRef: 'mongodb-uri'
            }
            {
              name: 'DATABASE_NAME'
              value: databaseName
            }
            {
              name: 'NODE_ENV'
              value: 'production'
            }
            {
              // Used by product semantic search (Atlas Vector Search via VoyageAI)
              name: 'VOYAGE_API_KEY'
              secretRef: 'voyage-api-key'
            }
            {
              name: 'VECTOR_INDEX_NAME'
              value: 'vs_index_vai_text_embeddings'
            }
            // RETENTION_BACKEND_URL (the Fabric enrichment toggle target) is set by
            // deploy.ps1 after the backend FQDN is known.
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
      }
    }
  }
}

// ── Churn Scoring Service (Python/FastAPI) ──
// Real-time, Azure ML-shaped REST endpoint in front of the Fabric-trained churn
// model. The enriched exit-risk agent calls it via a Foundry OpenAPI tool, so it
// must be externally reachable. Pulls a custom image from ACR.

resource scoringApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: scoringAppName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerEnvId
    configuration: {
      ingress: {
        external: true
        targetPort: 8080
        transport: 'auto'
      }
      registries: [
        {
          server: acrLoginServer
          username: acr.listCredentials().username
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: [
        {
          name: 'acr-password'
          value: acr.listCredentials().passwords[0].value
        }
        {
          name: 'mongodb-uri'
          value: mongodbUri
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'scoring'
          image: 'mcr.microsoft.com/k8se/quickstart:latest'  // Placeholder; updated by deploy.ps1 after image push
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'MONGODB_URI'
              secretRef: 'mongodb-uri'
            }
            {
              name: 'DATABASE_NAME'
              value: databaseName
            }
            {
              name: 'FABRIC_API_BASE'
              value: fabricApiBase
            }
            {
              name: 'FABRIC_WORKSPACE_ID'
              value: fabricWorkspaceId
            }
            {
              name: 'FABRIC_MODEL_ID'
              value: fabricModelId
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: managedIdentityClientId
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
}

// ── Outputs ──

@description('MCP Server FQDN')
output mcpServerFqdn string = mcpServerApp.properties.configuration.ingress.?fqdn ?? ''

@description('Backend app FQDN')
output backendFqdn string = backendApp.properties.configuration.ingress.?fqdn ?? ''

@description('Frontend app FQDN')
output frontendFqdn string = frontendApp.properties.configuration.ingress.?fqdn ?? ''

@description('Scoring service FQDN')
output scoringFqdn string = scoringApp.properties.configuration.ingress.?fqdn ?? ''
