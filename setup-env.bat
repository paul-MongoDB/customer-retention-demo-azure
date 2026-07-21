@echo off
REM ============================================================
REM  Leafy Retention Demo - Environment Setup and Deploy
REM  Copy this file to setup-env.local.bat and fill in values.
REM  Then run: setup-env.local.bat
REM ============================================================

REM == Required Variables ==
set MONGODB_URI=mongodb+srv://<username>:<password>@<cluster>.mongodb.net/?retryWrites=true^&w=majority
set AZURE_AI_PROJECT_ENDPOINT=https://<your-resource>.services.ai.azure.com/api/projects/<YourProject>
set VOYAGE_API_KEY=pa-xxxxxxxxxxxxxxxxxxxx
set FOUNDRY_RESOURCE_GROUP=<your-foundry-resource-group>
set FOUNDRY_AI_SERVICES_ACCOUNT=<your-ai-services-account>
set FOUNDRY_PROJECT_NAME=<your-foundry-project>

REM == Optional Variables (defaults shown) ==
set LEAFY_ENVIRONMENT_NAME=leafy-demo
set LEAFY_LOCATION=westus
set LEAFY_RESOURCE_GROUP=leafy-retention-demo-rg
set AZURE_AI_MODEL_DEPLOYMENT_NAME=gpt-5.4-mini
set LEAFY_DATABASE_NAME=leafy_popup_store

REM == Run Deployment ==
echo.
echo Starting deployment with:
echo   Environment:    %LEAFY_ENVIRONMENT_NAME%
echo   Location:       %LEAFY_LOCATION%
echo   Resource Group: %LEAFY_RESOURCE_GROUP%
echo   MongoDB URI:    %MONGODB_URI:~0,30%...
echo   Foundry:        %AZURE_AI_PROJECT_ENDPOINT%
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0deploy.ps1"
