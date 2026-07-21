#!/usr/bin/env bash
# ============================================================
#  Leafy Retention Demo - Environment Setup and Deploy
#  Copy this file to setup-env.local.sh and fill in values.
#  Then run: chmod +x setup-env.local.sh && ./setup-env.local.sh
# ============================================================

# == Required Variables ==
export MONGODB_URI="mongodb+srv://<username>:<password>@<cluster>.mongodb.net/?retryWrites=true&w=majority"
export AZURE_AI_PROJECT_ENDPOINT="https://<your-resource>.services.ai.azure.com/api/projects/<YourProject>"
export VOYAGE_API_KEY="pa-xxxxxxxxxxxxxxxxxxxx"
export FOUNDRY_RESOURCE_GROUP="<your-foundry-resource-group>"
export FOUNDRY_AI_SERVICES_ACCOUNT="<your-ai-services-account>"
export FOUNDRY_PROJECT_NAME="<your-foundry-project>"

# == Optional Variables (defaults shown) ==
export LEAFY_ENVIRONMENT_NAME="leafy-demo"
export LEAFY_LOCATION="westus"
export LEAFY_RESOURCE_GROUP="leafy-retention-demo-rg"
export AZURE_AI_MODEL_DEPLOYMENT_NAME="gpt-5.4-mini"
export LEAFY_DATABASE_NAME="leafy_popup_store"

# == Run Deployment ==
echo ""
echo "Starting deployment with:"
echo "  Environment:    $LEAFY_ENVIRONMENT_NAME"
echo "  Location:       $LEAFY_LOCATION"
echo "  Resource Group: $LEAFY_RESOURCE_GROUP"
echo "  MongoDB URI:    ${MONGODB_URI:0:30}..."
echo "  Foundry:        $AZURE_AI_PROJECT_ENDPOINT"
echo ""

pwsh -File "$(dirname "$0")/deploy.ps1"
