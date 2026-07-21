<#
.SYNOPSIS
  Deploy the Leafy Retention Demo to Azure Container Apps.

.DESCRIPTION
  All configuration is read from environment variables.
  1. Creates the resource group (if needed)
  2. Deploys shared infrastructure via Bicep (ACR, Container Apps Environment)
  3. Deploys container apps via Bicep (MCP Server, Backend, Scoring Gateway, Frontend)
  4. Builds and pushes Docker images to ACR
  5. Updates the Container Apps with the new images
  6. Assigns RBAC roles to the managed identity
  7. Registers MCP Server as a Foundry project connection

.NOTES
  Required environment variables:
    MONGODB_URI                     - MongoDB Atlas connection string
    AZURE_AI_PROJECT_ENDPOINT       - Microsoft Foundry project endpoint
    VOYAGE_API_KEY                  - Voyage AI API key for embeddings (starts with pa-)
    FOUNDRY_RESOURCE_GROUP          - Resource group containing the Foundry AI Services account
    FOUNDRY_AI_SERVICES_ACCOUNT     - Name of the AI Services account in Foundry
    FOUNDRY_PROJECT_NAME            - Name of the Foundry project
    AZURE_AI_MODEL_DEPLOYMENT_NAME  - Foundry model deployment name (must match a deployment in your project; see Step 0)
  Optional environment variables:
    LEAFY_ENVIRONMENT_NAME          - Resource name prefix (default: leafy-demo)
    LEAFY_LOCATION                  - Azure region (default: westus)
    LEAFY_RESOURCE_GROUP            - Resource group name (default: leafy-retention-demo-rg)
    LEAFY_DATABASE_NAME             - MongoDB database name (default: leafy_popup_store)

.EXAMPLE
  # Set required vars, then run
  $env:MONGODB_URI = "mongodb+srv://..."
  $env:AZURE_AI_PROJECT_ENDPOINT = "https://..."
  $env:VOYAGE_API_KEY = "pa-..."
  $env:FOUNDRY_RESOURCE_GROUP = "my-foundry-rg"
  $env:FOUNDRY_AI_SERVICES_ACCOUNT = "my-ai-services"
  $env:FOUNDRY_PROJECT_NAME = "my-project"
  $env:AZURE_AI_MODEL_DEPLOYMENT_NAME = "my-model-deployment"
  .\deploy.ps1
#>

# Note: We do NOT set $ErrorActionPreference = "Stop" globally because
# Azure CLI writes warnings to stderr which PowerShell 5 treats as
# terminating errors under that setting. Instead, we check $LASTEXITCODE
# after each az command.

# ── Read config from environment ──
$EnvironmentName = if ($env:LEAFY_ENVIRONMENT_NAME) { $env:LEAFY_ENVIRONMENT_NAME } else { "leafy-demo" }
$Location = if ($env:LEAFY_LOCATION) { $env:LEAFY_LOCATION } else { "westus" }
$ResourceGroup = if ($env:LEAFY_RESOURCE_GROUP) { $env:LEAFY_RESOURCE_GROUP } else { "leafy-retention-demo-rg" }

$FoundryRg = $env:FOUNDRY_RESOURCE_GROUP
$AiServicesAccount = $env:FOUNDRY_AI_SERVICES_ACCOUNT
$FoundryProject = $env:FOUNDRY_PROJECT_NAME

$InfraDir = "$PSScriptRoot/infra"
$BackendDir = "$PSScriptRoot/retail-customer-retention-backend-main"
$FrontendDir = "$PSScriptRoot/retail-store-v2-main"
$ScoringDir = "$PSScriptRoot/retail-customer-retention-scoring-main"

# ── Pre-flight checks ──
Write-Host "`n=== Pre-flight checks ===" -ForegroundColor Cyan

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Azure CLI (az) is required. Install from https://aka.ms/installazurecli" -ForegroundColor Red; exit 1
}

$account = az account show 2>$null | ConvertFrom-Json
if (-not $account) {
    Write-Host "ERROR: Not logged in. Run 'az login' first." -ForegroundColor Red; exit 1
}
Write-Host "Logged in as: $($account.user.name) (subscription: $($account.name))"

# Check required env vars
if (-not $env:MONGODB_URI) { Write-Host "ERROR: MONGODB_URI environment variable is required" -ForegroundColor Red; exit 1 }
if (-not $env:AZURE_AI_PROJECT_ENDPOINT) { Write-Host "ERROR: AZURE_AI_PROJECT_ENDPOINT environment variable is required" -ForegroundColor Red; exit 1 }
if (-not $env:VOYAGE_API_KEY) { Write-Host "ERROR: VOYAGE_API_KEY environment variable is required" -ForegroundColor Red; exit 1 }
if (-not $env:AZURE_AI_MODEL_DEPLOYMENT_NAME) { Write-Host "ERROR: AZURE_AI_MODEL_DEPLOYMENT_NAME is required and must match a model deployment in your Foundry project (see Step 0)" -ForegroundColor Red; exit 1 }
if (-not $FoundryRg) { Write-Host "ERROR: FOUNDRY_RESOURCE_GROUP environment variable is required" -ForegroundColor Red; exit 1 }
if (-not $AiServicesAccount) { Write-Host "ERROR: FOUNDRY_AI_SERVICES_ACCOUNT environment variable is required" -ForegroundColor Red; exit 1 }
if (-not $FoundryProject) { Write-Host "ERROR: FOUNDRY_PROJECT_NAME environment variable is required" -ForegroundColor Red; exit 1 }

Write-Host "Environment:  $EnvironmentName"
Write-Host "Location:     $Location"
Write-Host "RG:           $ResourceGroup"
Write-Host "Foundry RG:   $FoundryRg"
Write-Host "AI Services:  $AiServicesAccount"
Write-Host "Foundry Proj: $FoundryProject"

# ── Step 1: Resource Group ──
Write-Host "`n=== Step 1: Resource Group ===" -ForegroundColor Cyan

$rgExists = az group exists --name $ResourceGroup 2>$null
if ($rgExists -eq "false") {
    Write-Host "Creating resource group '$ResourceGroup' in '$Location'..."
    az group create --name $ResourceGroup --location $Location | Out-Null
} else {
    Write-Host "Resource group '$ResourceGroup' already exists."
}

# ── Step 2a: Deploy Shared Infrastructure (Bicep) ──
Write-Host "`n=== Step 2a: Deploy Shared Infrastructure (Bicep) ===" -ForegroundColor Cyan

$tempFile = [System.IO.Path]::GetTempFileName()

az deployment group create `
    --resource-group $ResourceGroup `
    --template-file "$InfraDir/main.bicep" `
    --parameters "$InfraDir/main.bicepparam" `
    --parameters location=$Location `
    --query "properties.outputs" `
    --output json > $tempFile 2>&1

if ($LASTEXITCODE -ne 0) {
    $errContent = Get-Content $tempFile -Raw
    Write-Host $errContent -ForegroundColor Red
    Remove-Item $tempFile -ErrorAction SilentlyContinue
    Write-Error "Infrastructure deployment failed."
    exit 1
}

# Read output and extract JSON
$rawOutput = Get-Content $tempFile -Raw
Remove-Item $tempFile -ErrorAction SilentlyContinue

$jsonStart = $rawOutput.IndexOf('{')
if ($jsonStart -lt 0) {
    Write-Error "No JSON output from infrastructure deployment. Raw output:`n$rawOutput"
    exit 1
}
$jsonText = $rawOutput.Substring($jsonStart)
$infraOutputs = $jsonText | ConvertFrom-Json

$acrLoginServer = $infraOutputs.acrLoginServer.value
$acrName = $infraOutputs.acrName.value
$containerEnvId = $infraOutputs.containerEnvId.value
$managedIdentityId = $infraOutputs.managedIdentityId.value
$identityClientId = $infraOutputs.managedIdentityClientId.value
$identityPrincipalId = $infraOutputs.managedIdentityPrincipalId.value

Write-Host "ACR:          $acrLoginServer"
Write-Host "Environment:  $containerEnvId"
Write-Host "Identity:     $identityClientId"

# ── Step 2a.5: Wait for the Container Apps environment to finish provisioning ──
# Re-applying the environment in Step 2a can briefly return it to 'Updating'.
# Deploying apps into it before it settles fails with ManagedEnvironmentNotProvisioned,
# so poll provisioningState until it is Succeeded before continuing.
Write-Host "`n=== Step 2a.5: Wait for environment to be ready ===" -ForegroundColor Cyan
$envName = ($containerEnvId -split '/')[-1]
$envReady = $false
for ($i = 1; $i -le 40; $i++) {
    $envState = az containerapp env show --name $envName --resource-group $ResourceGroup --query "properties.provisioningState" -o tsv 2>$null
    Write-Host "  [$i] $envName provisioningState = $envState"
    if ($envState -eq "Succeeded") { $envReady = $true; break }
    if ($envState -eq "Failed") { Write-Error "Container Apps environment '$envName' is in a Failed state."; exit 1 }
    Start-Sleep -Seconds 15
}
if (-not $envReady) {
    Write-Error "Container Apps environment '$envName' did not reach 'Succeeded' in time."
    exit 1
}
Write-Host "Environment is ready."

# ── Step 2b: Deploy Container Apps (Bicep) ──
Write-Host "`n=== Step 2b: Deploy Container Apps (Bicep) ===" -ForegroundColor Cyan

$tempFile2 = [System.IO.Path]::GetTempFileName()

az deployment group create `
    --resource-group $ResourceGroup `
    --template-file "$InfraDir/apps.bicep" `
    --parameters "$InfraDir/apps.bicepparam" `
    --parameters location=$Location `
        containerEnvId=$containerEnvId `
        acrLoginServer=$acrLoginServer `
        acrName=$acrName `
        managedIdentityId=$managedIdentityId `
        managedIdentityClientId=$identityClientId `
    --query "properties.outputs" `
    --output json > $tempFile2 2>&1

if ($LASTEXITCODE -ne 0) {
    $errContent = Get-Content $tempFile2 -Raw
    Write-Host $errContent -ForegroundColor Red
    Remove-Item $tempFile2 -ErrorAction SilentlyContinue
    Write-Error "Container Apps deployment failed."
    exit 1
}

$rawOutput2 = Get-Content $tempFile2 -Raw
Remove-Item $tempFile2 -ErrorAction SilentlyContinue

$jsonStart2 = $rawOutput2.IndexOf('{')
if ($jsonStart2 -lt 0) {
    Write-Error "No JSON output from apps deployment. Raw output:`n$rawOutput2"
    exit 1
}
$jsonText2 = $rawOutput2.Substring($jsonStart2)
$appsOutputs = $jsonText2 | ConvertFrom-Json

$mcpServerFqdn = $appsOutputs.mcpServerFqdn.value
$backendFqdn = $appsOutputs.backendFqdn.value
$frontendFqdn = $appsOutputs.frontendFqdn.value
$scoringFqdn = $appsOutputs.scoringFqdn.value

Write-Host "MCP Server:  $mcpServerFqdn"
Write-Host "Backend:     $backendFqdn"
Write-Host "Frontend:    $frontendFqdn"
Write-Host "Scoring:     $scoringFqdn"

# ── Step 3: Build and Push Docker Images (using ACR Tasks -- no local Docker needed) ──
Write-Host "`n=== Step 3: Build and Push Docker Images ===" -ForegroundColor Cyan

# MCP Server uses the official mongodb/mongodb-mcp-server:latest image from Docker Hub -- no build needed.
$backendImage = "${EnvironmentName}-backend:latest"
$frontendImage = "${EnvironmentName}-frontend:latest"
$scoringImage = "${EnvironmentName}-scoring:latest"

Write-Host "Building backend image in ACR..."
az acr build --registry $acrName --image $backendImage $BackendDir --no-logs 2>&1 | Out-Null
Write-Host "Backend image built. Waiting for push..."
az acr repository show-tags --name $acrName --repository ($backendImage -replace ':.*','') --output tsv | Select-Object -Last 1 | Out-Null
Write-Host "Backend image ready."

Write-Host "Building frontend image in ACR..."
az acr build --registry $acrName --image $frontendImage $FrontendDir --no-logs 2>&1 | Out-Null
Write-Host "Frontend image built. Waiting for push..."
az acr repository show-tags --name $acrName --repository ($frontendImage -replace ':.*','') --output tsv | Select-Object -Last 1 | Out-Null
Write-Host "Frontend image ready."

# The scoring gateway calls Fabric's model endpoint; no model is baked here.
Write-Host "Building scoring image in ACR..."
az acr build --registry $acrName --image $scoringImage $ScoringDir --no-logs 2>&1 | Out-Null
Write-Host "Scoring image built. Waiting for push..."
az acr repository show-tags --name $acrName --repository ($scoringImage -replace ':.*','') --output tsv | Select-Object -Last 1 | Out-Null
Write-Host "Scoring image ready."

# ── Step 4: Update Container Apps with new images ──
Write-Host "`n=== Step 4: Update Container Apps ===" -ForegroundColor Cyan

# MCP Server uses Docker Hub image -- already configured in Bicep, no update needed.
Write-Host "MCP Server uses official image (mongodb/mongodb-mcp-server:latest) -- deployed via Bicep."

az containerapp update `
    --name "${EnvironmentName}-backend" `
    --resource-group $ResourceGroup `
    --image "$acrLoginServer/$backendImage" `
    --set-env-vars "MCP_SERVER_URL=https://${mcpServerFqdn}/mcp" "SCORING_SERVICE_URL=https://${scoringFqdn}" | Out-Null
Write-Host "Backend updated."

az containerapp update `
    --name "${EnvironmentName}-frontend" `
    --resource-group $ResourceGroup `
    --image "$acrLoginServer/$frontendImage" `
    --set-env-vars "RETENTION_BACKEND_URL=https://${backendFqdn}" | Out-Null
Write-Host "Frontend updated."

az containerapp update `
    --name "${EnvironmentName}-scoring" `
    --resource-group $ResourceGroup `
    --image "$acrLoginServer/$scoringImage" | Out-Null
Write-Host "Scoring service updated."

# ── Step 5: Role assignments for Managed Identity ──
Write-Host "`n=== Step 5: Role Assignments ===" -ForegroundColor Cyan

$subscriptionId = $account.id

# Use az rest to avoid the MissingSubscription error that az role assignment create hits.
# Write JSON bodies to temp files to avoid PowerShell 5 argument escaping issues with az rest.

# Role 1: Cognitive Services User (subscription scope) - for model inference
Write-Host "Assigning 'Cognitive Services User' role..."
$roleDefId = "a97b65f3-24c7-4388-baec-2e87135dc908"
$assignmentId = [guid]::NewGuid().ToString()
$scope = "/subscriptions/$subscriptionId"
$assignmentUrl = "https://management.azure.com${scope}/providers/Microsoft.Authorization/roleAssignments/${assignmentId}?api-version=2022-04-01"

$bodyFile = [System.IO.Path]::GetTempFileName()
@{
    properties = @{
        roleDefinitionId = "${scope}/providers/Microsoft.Authorization/roleDefinitions/${roleDefId}"
        principalId = "$identityPrincipalId"
        principalType = "ServicePrincipal"
    }
} | ConvertTo-Json -Depth 3 | Set-Content -Path $bodyFile -Encoding UTF8

az rest --method put --url $assignmentUrl --body "@$bodyFile" --headers "Content-Type=application/json" 2>$null | Out-Null
Remove-Item $bodyFile -ErrorAction SilentlyContinue
if ($LASTEXITCODE -eq 0) {
    Write-Host "Cognitive Services User assigned (subscription scope)."
} else {
    Write-Host "Cognitive Services User role may already exist (this is OK)." -ForegroundColor Yellow
}

# Role 2: Azure AI User (Foundry AI Services account) - for agent invocation
# Includes Microsoft.CognitiveServices/* data actions (agents/write, OpenAI/*, etc.)
# Scoped to the AI Services account, not the whole resource group.
Write-Host "Assigning 'Azure AI User' role on '$AiServicesAccount'..."
$aiUserRoleDefId = "53ca6127-db72-4b80-b1b0-d745d6d5456d"
$assignmentId2 = [guid]::NewGuid().ToString()
$aiScope = "/subscriptions/$subscriptionId/resourceGroups/$FoundryRg/providers/Microsoft.CognitiveServices/accounts/$AiServicesAccount"
$assignmentUrl2 = "https://management.azure.com${aiScope}/providers/Microsoft.Authorization/roleAssignments/${assignmentId2}?api-version=2022-04-01"

$bodyFile2 = [System.IO.Path]::GetTempFileName()
@{
    properties = @{
        roleDefinitionId = "/subscriptions/$subscriptionId/providers/Microsoft.Authorization/roleDefinitions/${aiUserRoleDefId}"
        principalId = "$identityPrincipalId"
        principalType = "ServicePrincipal"
    }
} | ConvertTo-Json -Depth 3 | Set-Content -Path $bodyFile2 -Encoding UTF8

az rest --method put --url $assignmentUrl2 --body "@$bodyFile2" --headers "Content-Type=application/json" 2>$null | Out-Null
Remove-Item $bodyFile2 -ErrorAction SilentlyContinue
if ($LASTEXITCODE -eq 0) {
    Write-Host "Azure AI User assigned on '$AiServicesAccount'."
} else {
    Write-Host "WARNING: Azure AI User role assignment may have failed. Check manually." -ForegroundColor Yellow
    Write-Host "  Run: az rest --method put --url '$assignmentUrl2' --body '<body>' --headers 'Content-Type=application/json'" -ForegroundColor Yellow
}

# ── Step 6: Register MCP Server as Foundry Project Connection ──
Write-Host "`n=== Step 6: Register MCP Connection in Foundry ===" -ForegroundColor Cyan

# The MCP server connection lives on the Foundry project workspace (different resource group).
# This makes the MongoDB MCP tool visible in the Foundry portal under Connected Resources.
# Agents reference it via project_connection_id="mongodb-mcp-server".
$connectionName = "mongodb-mcp-server"
$mcpConnectionUrl = "https://${mcpServerFqdn}/mcp"
$connectionApiUrl = "https://management.azure.com/subscriptions/$subscriptionId/resourceGroups/$FoundryRg/providers/Microsoft.CognitiveServices/accounts/$AiServicesAccount/projects/$FoundryProject/connections/${connectionName}?api-version=2025-04-01-preview"

Write-Host "Registering MCP connection '$connectionName' -> $mcpConnectionUrl"

$connectionBodyFile = [System.IO.Path]::GetTempFileName()
@{
    properties = @{
        category = "RemoteTool"
        target = $mcpConnectionUrl
        authType = "None"
        isSharedToAll = $true
        metadata = @{
            "mcp.transport" = "streamable-http"
        }
    }
} | ConvertTo-Json -Depth 5 | Set-Content -Path $connectionBodyFile -Encoding UTF8

az rest --method PUT --url $connectionApiUrl --body "@$connectionBodyFile" --headers "Content-Type=application/json" 2>$null | Out-Null
Remove-Item $connectionBodyFile -ErrorAction SilentlyContinue
if ($LASTEXITCODE -eq 0) {
    Write-Host "MCP connection registered in Foundry project '$FoundryProject'."
} else {
    Write-Host "MCP connection registration may have failed. Check Foundry portal manually." -ForegroundColor Yellow
}

# ── Done ──
Write-Host "`n=== Deployment Complete ===" -ForegroundColor Green
Write-Host "Frontend:   https://$frontendFqdn"
Write-Host "Backend:    https://$backendFqdn"
Write-Host "MCP Server: https://$mcpServerFqdn"
Write-Host "Scoring:    https://$scoringFqdn"
Write-Host "Health:     https://$backendFqdn/health"

Write-Host "`n=== IMPORTANT: MongoDB Atlas Network Access ===" -ForegroundColor Yellow
Write-Host "Whitelist the MCP Server's AND scoring service's outbound IPs in MongoDB Atlas Network Access:"
Write-Host "  az containerapp show --name '${EnvironmentName}-mcp-server' --resource-group '$ResourceGroup' --query 'properties.outboundIpAddresses' -o tsv"
Write-Host "  az containerapp show --name '${EnvironmentName}-scoring' --resource-group '$ResourceGroup' --query 'properties.outboundIpAddresses' -o tsv"
Write-Host "Or use 0.0.0.0/0 for testing."

Write-Host "`n=== NEXT: Register Foundry agents ===" -ForegroundColor Yellow
Write-Host "Run setup_agents.py with the scoring URL exported so the enriched exit-risk"
Write-Host "agent's OpenAPI tool registers against the live endpoint:"
Write-Host "  `$env:SCORING_SERVICE_URL = 'https://$scoringFqdn'"
Write-Host "  cd retail-customer-retention-backend-main; python setup_agents.py"

Write-Host "`n=== NEXT: Fabric churn model (real-time scoring) ===" -ForegroundColor Yellow
Write-Host "The scoring gateway calls Fabric's ML model endpoint. After deploy:"
Write-Host "  1. In Fabric, run the train_churn_model notebook to register 'leafy-churn-scorer'."
Write-Host "  2. Activate the model version's real-time endpoint (turn auto-sleep off for demos)."
Write-Host "  3. Grant the gateway's managed identity write access to the model in Fabric."
Write-Host "     Identity client id: $identityClientId"
Write-Host "  4. Point the gateway at the model (workspace + model IDs from the endpoint details):"
Write-Host "     az containerapp update --name '${EnvironmentName}-scoring' --resource-group '$ResourceGroup' --set-env-vars FABRIC_WORKSPACE_ID=<id> FABRIC_MODEL_ID=<id>"
