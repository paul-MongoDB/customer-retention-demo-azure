# Retail Customer Retention Backend

Real-time retention engine for the Leafy demo. It watches MongoDB Atlas for
behavioral signals, hands each one to an Azure AI Foundry agent, and writes the
agent's decision back to Atlas so the storefront can act on it in real time.

This service is the orchestration relay. The agents themselves live in Azure AI
Foundry and decide which tools to call. The Python here just watches the change
stream, invokes the right agent, and lets Foundry do the reasoning.

## Architecture

```
              MongoDB Atlas (session_signals)
                          │  new signal inserted
                          │  (written by Atlas Stream Processing)
                          ▼
        ┌─────────────────────────────────────────┐
        │  change_stream.py                        │
        │  watches session_signals for inserts     │
        └───────────────────┬─────────────────────┘
                            │
                            ▼
        ┌─────────────────────────────────────────┐
        │  foundry_agents.process_signal()         │
        │  routes the signal to the right agent    │
        └───────────────────┬─────────────────────┘
                            │  OpenAI Responses API (agent_reference)
                            ▼
        ┌─────────────────────────────────────────┐
        │  Azure AI Foundry agent                  │
        │  reasons over the signal, calls tools:   │
        │   - MongoDB MCP Server (queries/writes,  │
        │     Atlas Vector Search via VoyageAI)    │
        │   - score_churn OpenAPI tool ──► scoring │
        │     gateway ──► Microsoft Fabric model   │
        └───────────────────┬─────────────────────┘
                            │  writes result
                            ▼
              MongoDB Atlas (next_best_actions)
                            │
                            ▼
                 Storefront UI (SSE) shows the NBA
```

## Signal to agent mapping

| Signal | Agent | Next Best Action |
|--------|-------|------------------|
| `high-intent` | SocialProofAgent | social proof urgency message on the product |
| `search-friction` | SearchFrictionWorkflow | discounted product recommendation |
| `exit-risk` | ShippingDiscountAgent (or the enriched variant) | order discount, escalating to free shipping on the Fabric High-churn path |
| `cart-abandonment` | CartRescueAgent (or the enriched variant) | cart-rescue discount, escalating on the Fabric High-churn path |

The enriched exit-risk and cart-abandonment agents call the scoring gateway for
a live Microsoft Fabric churn score before deciding the offer tier. Enrichment
is toggled at runtime (`POST /enrichment/on|off`), starting off.

## Key files

- `main.py` - entry point; starts the change stream watcher thread and FastAPI on port 8080
- `foundry_agents.py` - agent instructions, signal routing, `_invoke_agent()`, the enrichment toggle
- `setup_agents.py` - one-time registration of the Foundry agents (run once per environment)
- `change_stream.py` - watches `session_signals` for inserts and triggers the agent
- `agent.py` - thin dispatcher into `foundry_agents.process_signal()`
- `config.py` - environment variable loading and database/collection/model constants
- `mongo.py` - MongoDB client singleton
- `generate_demo_data.py` - seeds demo data, including the high-risk persona
- `fabric_notebooks/` - Fabric notebooks: `train_churn_model.py`, `score_new_users.py`, `generate_burst.ipynb`
- `external/atlas-stream-processing/` - the Atlas Stream Processing pipeline definitions that produce the signals

## Local development

### Prerequisites

- Python 3.12+
- A MongoDB Atlas cluster with the demo collections
- An Azure AI Foundry project with the agents registered (`setup_agents.py`)
- A reachable MongoDB MCP Server
- A VoyageAI API key (consumed by the MCP Server for embeddings, not by this backend directly)
- `az login` for local Azure credentials (agents authenticate via `DefaultAzureCredential`, which picks up your `az login`)

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp EXAMPLE.env .env         # then fill in the values
```

### Environment variables

Required: `MONGODB_URI`, `AZURE_AI_PROJECT_ENDPOINT`, `MCP_SERVER_URL`.

Set `AZURE_AI_MODEL_DEPLOYMENT_NAME` to the name of the model deployment you
created in your Azure AI Foundry project (there is no safe default, it must match
your deployment).

Optional: `DATABASE_NAME` (default `leafy_popup_store`), `SCORING_SERVICE_URL`,
`FABRIC_ENRICHMENT_ENABLED` (default `false`), `MCP_CONNECTION_NAME`. See
`EXAMPLE.env` for the full list and notes. (`VOYAGE_API_KEY` appears in
`EXAMPLE.env` for reference but is used by the MCP Server, not this backend.)

### Seed demo data

The product catalog (with VoyageAI embeddings) ships as a MongoDB dump in the
storefront repo (`retail-store-v2-main/dump/`); restore it and create the search
indexes first (see the [Atlas setup guide](../docs/ATLAS_SETUP.md)). Then layer on
the behavioral sessions and the high-risk persona:

```bash
# Baseline sessions across the demo users (clears and regenerates demo data)
python generate_demo_data.py --mode baseline --clear

# Seed a genuinely high-risk history for the demo persona (Grace Hopper, who
# ships in the seed dump) and clear her churn score so the enriched agent scores
# her live. 66fe219d625d93a100528224 is Grace's user _id.
python generate_demo_data.py --persona-uid 66fe219d625d93a100528224
```

The `--persona-uid` value must be a real storefront user `_id`, and you have to
select that same user in the login picker for the persona to appear. The seed dump
ships four shoppers; the demo uses **Grace Hopper** (`66fe219d625d93a100528224`).
See [ATLAS_SETUP.md](../docs/ATLAS_SETUP.md) for how to look up other ids. `--clear`
also empties the dump's `carts` collection (harmless; carts are rewritten at runtime).

Run the persona step before demoing the Fabric enrichment path. Other flags:
`--mode burst` (a burst of activity) and `--clean-burst` (remove prior burst data
and churn scores for a clean re-run).

### Register the Foundry agents

Run this once per environment to create the agents in your Azure AI Foundry
project. It requires `AZURE_AI_PROJECT_ENDPOINT`, `AZURE_AI_MODEL_DEPLOYMENT_NAME`,
and `MCP_SERVER_URL`. To attach the `score_churn` tool to the enriched agents, also
set `SCORING_SERVICE_URL` to a URL that Foundry can reach (a public/deployed FQDN,
not `localhost`); without it the enriched agents register but cannot call the churn
model.

```bash
az login
python setup_agents.py
```

### Run

```bash
# Locally, use port 8000 so it doesn't clash with the storefront (8080)
PORT=8000 python main.py
```

The server binds `PORT` if set, otherwise 8080 (what Azure Container Apps expects).
This starts the change stream watcher thread and the FastAPI server. Endpoints
include `/health`, `/debug`, `/test-signal/{type}`, `GET /enrichment`,
`POST /enrichment/{state}`, and `DELETE /churn-score/{uid}`.

If `ADMIN_API_KEY` is set, every endpoint above except `/health` and
`GET /enrichment` requires a matching `X-Admin-Key` header. Leave it unset for
local development; set it (and the same variable in the storefront's env, for
the enrichment proxy) on any deployment reachable from the internet:

```bash
curl -X POST -H "X-Admin-Key: $ADMIN_API_KEY" "$BACKEND/enrichment/on"
```

**Local ports (keep them distinct):** storefront 8080, this backend 8000
(`PORT=8000`), scoring gateway 8081 (`PORT=8081`). Set the storefront's
`RETENTION_BACKEND_URL=http://localhost:8000` to reach this backend.

**Start order for the full local flow:** (1) seed data + persona, (2) start the
scoring gateway on 8081, (3) register the agents (`setup_agents.py`),
(4) start this backend on 8000, (5) toggle enrichment on with `POST /enrichment/on`.

### Docker

```bash
docker build -t retention-backend .
docker run -p 8080:8080 retention-backend
```

## Tests

```bash
# Contract test: the generator's session_state shape must match asp1 output
python -m tests.test_session_state_shape
```

## Authors and contributors

### Lead authors

- [Rodrigo Leal](https://www.mongodb.com/blog/authors/rodrigo-leal) - Principal
- [Genevieve Broadhead](https://www.mongodb.com/blog/authors/genevieve-broadhead) - Global lead, retail solutions
- [Angie Guemes](https://www.mongodb.com/developer/author/angie-guemes-estrada/) - Developer and maintainer
- [Florencia Arin](https://www.mongodb.com/blog/authors/florencia-arin) - Developer and maintainer

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).

This repository is intended for demonstration and educational purposes. No
support or warranty is provided. Use at your own risk.
