import os

# Mongo — direct connection is still needed for the change-stream watcher.
MONGODB_URI = os.environ["MONGODB_URI"]
DB_NAME = os.environ.get("DATABASE_NAME", "leafy_popup_store")

SESSION_SIGNALS_COLLECTION = "session_signals"
SESSION_STATE_COLLECTION = "session_state"
PRODUCTS_COLLECTION = "products"
NEXT_BEST_ACTION_COLLECTION = "next_best_actions"
CHURN_RISK_SCORES_COLLECTION = "churn_risk_scores"

# Vector search (used by the remote MongoDB MCP Server)
VECTOR_INDEX_NAME = "vs_index_vai_text_embeddings"
SEARCH_INDEX_NAME = "search_index_products"
EMBEDDING_FIELD = "vai_text_embedding"

# MongoDB MCP Server (Azure Container Apps -- Streamable HTTP)
MCP_SERVER_URL = os.environ["MCP_SERVER_URL"]

# Foundry project connection name for the MCP server (registered via deploy.ps1)
MCP_CONNECTION_NAME = os.environ.get("MCP_CONNECTION_NAME", "mongodb-mcp-server")

# Microsoft Foundry (Agent Framework -- any deployed model)
AZURE_AI_PROJECT_ENDPOINT = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
MODEL_DEPLOYMENT_NAME = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-5.4-mini")

# Real-time churn scoring service (Azure Container App; localhost for dev).
# The Fabric-enriched exit-risk agent calls this to score a customer on a miss.
SCORING_SERVICE_URL = os.environ.get("SCORING_SERVICE_URL", "http://localhost:8081")

# Whether exit-risk uses the Fabric-enriched agent. This is only the startup
# default; the live value is a runtime toggle flipped via the backend.
FABRIC_ENRICHMENT_ENABLED = os.environ.get("FABRIC_ENRICHMENT_ENABLED", "false").lower() == "true"
