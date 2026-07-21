using 'apps.bicep'

param environmentName = readEnvironmentVariable('LEAFY_ENVIRONMENT_NAME', 'leafy-demo')
param mongodbUri = readEnvironmentVariable('MONGODB_URI', '')
param voyageApiKey = readEnvironmentVariable('VOYAGE_API_KEY', '')
param azureAiProjectEndpoint = readEnvironmentVariable('AZURE_AI_PROJECT_ENDPOINT', '')
param azureAiModelDeploymentName = readEnvironmentVariable('AZURE_AI_MODEL_DEPLOYMENT_NAME', '')
param databaseName = readEnvironmentVariable('LEAFY_DATABASE_NAME', 'leafy_popup_store')

// These are passed as --parameters overrides from deploy.ps1 (output of main.bicep)
param containerEnvId = ''
param acrLoginServer = ''
param acrName = ''
param managedIdentityId = ''
param managedIdentityClientId = ''
