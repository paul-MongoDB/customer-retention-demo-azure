# Architecture: Atlas + Azure AI Foundry Retention Demo

This document describes the backend architecture for the Leafy customer retention demo, which uses MongoDB Atlas for real-time data, Azure AI Foundry for agent orchestration, the MongoDB MCP Server for bridging the two, and Microsoft Fabric for churn scoring (batch and real-time via a scoring gateway).

## System Flow

```
Browser (Next.js frontend)
    |
    | writes user behavior events
    v
MongoDB Atlas (events_ingest)
    |
    | Atlas Stream Processing (detects patterns)
    v
MongoDB Atlas (session_signals)
    |
    | Change Stream (backend watches for inserts)
    v
Python Backend (foundry_agents.py)
    |
    | OpenAI Responses API + agent_reference
    v
Azure AI Foundry (Prompt Agents + Workflow Agent)
    |
    | MCPTool (Streamable HTTP, server-side)
    v
MongoDB MCP Server (reads products, writes NBAs)
    |
    v
MongoDB Atlas (next_best_actions)
    |
    | Change Stream (frontend watches via SSE)
    v
Browser (notification popup)
```

### Enriched paths: exit-risk and cart-abandonment (Fabric real-time scoring)

When Fabric enrichment is on (`POST /enrichment/on`), exit-risk signals route to
`ShippingDiscountAgentEnriched` and cart-abandonment signals route to
`CartRescueAgentEnriched` instead of their baseline agents. One toggle gates both.
Each enriched agent first looks for a cached score in `churn_risk_scores` (via MCP);
if none exists it calls its `score_churn` OpenAPI tool:

```
ShippingDiscountAgentEnriched / CartRescueAgentEnriched
    |
    | score_churn (OpenAPI tool) -> POST /score
    v
Scoring Gateway (retail-customer-retention-scoring-main, own Container App)
    |
    | featurizes the user from Atlas (fresh, not the mirror)
    | calls Fabric's real-time ML model endpoint (leafy-churn-scorer)
    | writes the result to churn_risk_scores (storefront panel lights up)
    v
returns churn_probability + churn_risk_tier + top_risk_factor
    |
    v
agent escalates the offer when risk is High: both enriched agents escalate a
High-risk customer to FREE shipping + 25% off (free shipping is reserved for the
enriched High path; all baseline offers are order discounts)
```

The gateway never hosts the model; training and serving both live in Fabric. Enrichment
starts off (`FABRIC_ENRICHMENT_ENABLED=false`) and is toggled at runtime with no restart:
an in-UI toggle switch at the top of the retention drawer (Redux-backed, synced from the
backend `GET /enrichment` on mount) proxies to `POST /enrichment/on|off`.

## Backend Call Chain

```
main.py
  |-- foundry_agents.initialize()     -- creates AsyncOpenAI client + Azure credentials
  |-- change_stream.watch_customer_behavior()  -- daemon thread watching session_signals
  |     |-- agent.handle_signal(doc)
  |           |-- foundry_agents.process_signal(doc)
  |                 |-- _invoke_agent(agent_name, user_message)
  |                       |-- openai.conversations.create()
  |                       |-- openai.responses.create(agent_reference=..., stream=True)
  |-- uvicorn.run(app)                -- FastAPI server (health, debug, test endpoints)
```

All signal types use the same code path: `_invoke_agent()` creates a Foundry conversation, invokes the named agent via `agent_reference`, and streams the response to wait for completion. Foundry handles MCP tool execution server-side.

## Signal Types and Agents

| Signal | Foundry Agent | Type | What It Does |
|--------|--------------|------|-------------|
| `search-friction` | SearchFrictionWorkflow | Workflow | Chains ContextAnalyzer (reads search history, infers intent) then RecommendationWriter (Atlas Search for products, inserts NBA with product recommendation) |
| `high-intent` | SocialProofAgent | Prompt | Looks up the product, creates social-proof urgency message, inserts NBA |
| `exit-risk` (enrichment off) | ShippingDiscountAgent | Prompt | Maps severity to an order-discount tier (15%/20%/25%/30% off), inserts NBA |
| `exit-risk` (enrichment on) | ShippingDiscountAgentEnriched | Prompt | Checks `churn_risk_scores` for a cached score; if none, calls the scoring gateway via the `score_churn` OpenAPI tool (live Fabric score); High risk escalates to FREE shipping + 25% off, inserts NBA |
| `cart-abandonment` (enrichment off) | CartRescueAgent | Prompt | Maps severity (cart item count) to an order-discount rescue (10% / 15% / 20% off your order, no free shipping), inserts NBA |
| `cart-abandonment` (enrichment on) | CartRescueAgentEnriched | Prompt | Checks `churn_risk_scores`; if none, calls the scoring gateway via `score_churn` (live Fabric score), escalates to FREE shipping + 25% off for High risk, inserts NBA |

## File Inventory

### Active Runtime Files

| File | Purpose |
|------|---------|
| `main.py` | Entry point. FastAPI app, initializes agents, starts change stream thread |
| `foundry_agents.py` | Core agent orchestration. Agent instructions, `_invoke_agent()`, signal routing |
| `agent.py` | Thin dispatcher: `handle_signal(doc)` delegates to `foundry_agents.process_signal()` |
| `change_stream.py` | Watches `session_signals` for inserts, calls `agent.handle_signal()` |
| `config.py` | Environment variable config (MongoDB URI, Foundry endpoint, model name) |
| `mongo.py` | Singleton PyMongo client for change stream |

### Scoring Gateway (separate service: `retail-customer-retention-scoring-main/`)

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app: `/score` (featurize + call Fabric + write back) and `/health` (reports `fabric_configured`) |
| `features.py` | Featurizes a user from live Atlas data (same 10 features the model trains on) |
| `fabric_client.py` | Entra-authenticated call to Fabric's real-time model endpoint |

### Setup/Tooling (not part of runtime)

| File | Purpose |
|------|---------|
| `setup_agents.py` | One-time CLI script to register agents in Foundry portal. Imports instructions from `foundry_agents.py` |
| `EXAMPLE.env` | Template for environment variables (never committed with real values) |
| `Dockerfile` | Container image definition (Python 3.12) |
| `requirements.txt` | Runtime dependencies |

### External

| Directory | Purpose |
|-----------|---------|
| `external/atlas-stream-processing/` | Atlas Stream Processing pipeline definitions that produce the behavioral signals |

## Agent Registration

Agents are registered in Azure AI Foundry via `setup_agents.py` using the `azure-ai-projects` SDK:

- **PromptAgentDefinition** for single-step agents (SocialProofAgent, ShippingDiscountAgent, ShippingDiscountAgentEnriched, CartRescueAgent, CartRescueAgentEnriched, ContextAnalyzer, RecommendationWriter). Each gets an `MCPTool` with `server_url` pointing to the MongoDB MCP Server.
- **WorkflowAgentDefinition** for the SearchFrictionWorkflow, defined in YAML. The workflow chains ContextAnalyzer then RecommendationWriter using `InvokeAzureAgent` steps.
- The enriched agents (ShippingDiscountAgentEnriched, CartRescueAgentEnriched) additionally get an **OpenApiTool** (`score_churn`) targeting the scoring gateway's `/score`. Requires `azure-ai-projects` 2.2.x and `SCORING_SERVICE_URL` at registration time. Registration is driven by the `SCORING_TOOL_AGENTS` set in `setup_agents.py`.

Agent instructions live in `foundry_agents.py` (the single source of truth) and are imported by `setup_agents.py` for registration.

## Key Services

- **MongoDB Atlas** -- operational data store, Change Streams for real-time event processing, Atlas Search for product discovery
- **Azure AI Foundry** -- agent hosting, LLM inference, workflow orchestration via Responses API
- **MongoDB MCP Server** -- bridges Foundry agents to Atlas collections via Model Context Protocol (Streamable HTTP). Runs on Azure Container Apps.
- **Scoring Gateway** -- thin REST service in front of Fabric's real-time churn model endpoint. Featurizes from Atlas, calls Fabric with its managed identity, writes `churn_risk_scores`. Runs on Azure Container Apps.
- **Microsoft Fabric** -- trains and serves the churn model (`leafy-churn-scorer`): batch scoring via notebooks, real-time scoring via the activated model endpoint.
- **VoyageAI** -- embedding generation, integrated into the MongoDB MCP Server (no separate client needed)

## Required Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MONGODB_URI` | Yes | Atlas connection string (for change stream watcher) |
| `MCP_SERVER_URL` | Yes | MongoDB MCP Server endpoint (e.g., `https://leafy-demo-mcp-server.<env>.azurecontainerapps.io/mcp`) |
| `AZURE_AI_PROJECT_ENDPOINT` | Yes | Foundry project endpoint |
| `VOYAGE_API_KEY` | Yes | VoyageAI API key (used by MCP Server) |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | No | Model deployment name (no default; must match a deployment in your Foundry project) |
| `AZURE_CLIENT_ID` | No | Managed identity client ID (set automatically in Container Apps) |
| `SCORING_SERVICE_URL` | For enrichment | Scoring gateway base URL. Used by `setup_agents.py` to target the `score_churn` tool |
| `FABRIC_ENRICHMENT_ENABLED` | No | Startup default for the enrichment toggle (default `false`; flip at runtime via `POST /enrichment/on\|off`) |

The scoring gateway has its own config: `MONGODB_URI`, `DATABASE_NAME`, `FABRIC_API_BASE`, `FABRIC_WORKSPACE_ID`, `FABRIC_MODEL_ID`, and `AZURE_CLIENT_ID` (managed identity used to call Fabric). Its `/health` reports `fabric_configured: true` once the two Fabric IDs are set.

## Runtime Dependencies

```
openai              # Responses API for agent invocation
azure-identity      # Azure credential support (ManagedIdentity, DefaultAzureCredential)
aiohttp             # HTTP client (required by azure-identity)
pymongo             # Direct MongoDB connection for change stream
fastapi             # Health check and test HTTP endpoints
uvicorn[standard]   # ASGI server
python-dotenv       # .env file loading
```

## Design Decisions

1. **All agents invoked via Foundry `agent_reference`**: The backend does not manage MCP connections or tool-call loops. Foundry handles MCP tool execution server-side, keeping the backend thin.

2. **Single `_invoke_agent()` helper**: All signal types use the same invocation pattern (conversation + agent_reference + streaming). Signal-to-agent mapping is a simple dictionary.

3. **Streaming required for workflows**: Non-streaming Responses API calls return immediately with `in_progress` status for workflow agents. Streaming consumes events until `response.completed` or `response.failed`.

4. **Remote MCP Server**: The MongoDB MCP Server runs as a separate container on Azure Container Apps. Foundry agents connect to it via `MCPTool(server_url=...)`. This decouples the MCP server lifecycle from the backend.

5. **VoyageAI stays via MCP**: MongoDB owns VoyageAI. The MCP Server handles embeddings internally for vector search, so no separate embedding client is needed in the backend.

6. **Persistent event loop**: The change stream runs in a daemon thread with `asyncio.new_event_loop()`. Agent invocations use `loop.run_until_complete()` to bridge sync/async boundaries without killing MCP client primitives.
