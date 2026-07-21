import os

from dotenv import load_dotenv

# Load .env for local development before reading any environment variables.
load_dotenv()

# MongoDB -- the gateway reads behavioral data and writes churn_risk_scores back.
MONGODB_URI = os.environ["MONGODB_URI"]
DB_NAME = os.environ.get("DATABASE_NAME", "leafy_popup_store")

SESSION_SIGNALS_COLLECTION = "session_signals"
NEXT_BEST_ACTION_COLLECTION = "next_best_actions"
CHURN_RISK_SCORES_COLLECTION = "churn_risk_scores"

# Microsoft Fabric ML model endpoint. The churn model is trained AND served in
# Fabric; this gateway calls its real-time endpoint for the score.
FABRIC_API_BASE = os.environ.get("FABRIC_API_BASE", "https://api.fabric.microsoft.com")
FABRIC_WORKSPACE_ID = os.environ.get("FABRIC_WORKSPACE_ID", "")
FABRIC_MODEL_ID = os.environ.get("FABRIC_MODEL_ID", "")
# Optional managed-identity client id used to get the Fabric token in Azure.
# Empty locally -> DefaultAzureCredential (your `az login`).
AZURE_CLIENT_ID = os.environ.get("AZURE_CLIENT_ID", "")

# Container Apps expects 8080; use 8081 locally to avoid clashing with the backend.
PORT = int(os.environ.get("PORT", "8080"))
