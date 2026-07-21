# Leafy Customer Retention Demo

A reference demo for real-time, AI-driven customer retention, built on
**MongoDB Atlas**, **Azure AI Foundry**, and **Microsoft Fabric**.

The scenario: a shopper on the Leafy storefront starts showing signs of leaving
(hesitating, searching without buying, dwelling on a full cart, moving toward the
exit). The system detects that behavior as it happens, reasons about the best
response with an AI agent, and delivers a personalized retention offer back into
the storefront in real time. When enrichment is on, the agent also pulls a live
churn score from a model trained and served in Microsoft Fabric before it decides
how far to go with the offer.

This is a "better together" story. Each platform does what it is best at:

- **MongoDB Atlas** is the operational backbone. It stores every event, detects
  behavioral signals with Atlas Stream Processing, powers product discovery with
  Atlas Vector Search, and streams changes to the UI with Change Streams.
- **Azure AI Foundry** hosts the agents. They reason over each signal and decide
  which tools to call and in what order.
- **Microsoft Fabric** owns the analytics. It trains and serves the churn model,
  scores users in real time, and drives the Power BI reporting.

> This repository is a demonstration and educational reference, not a
> production system. No support or warranty is provided.

## How it works

```
  Shopper on the storefront
          │  events (views, searches, cart adds, exit intent)
          ▼
  Atlas: events_ingest ──► Atlas Stream Processing ──► session_signals
          │                                                   │
          │                                                   │ new signal
          │                                                   ▼
          │                                     Backend change stream watcher
          │                                                   │
          │                                                   ▼
          │                                     Azure AI Foundry agent reasons,
          │                                     calls tools:
          │                                       - MongoDB MCP Server (queries,
          │                                         Vector Search, writes)
          │                                       - score_churn ──► scoring
          │                                         gateway ──► Fabric model
          │                                                   │
          │                                                   ▼
          │                                     Atlas: next_best_actions
          │                                                   │
          ▼                                                   ▼
  Storefront UI  ◄──────── Change Stream / SSE ──────── new retention offer
```

1. The storefront tracks user behavior and writes events to Atlas.
2. Atlas Stream Processing turns raw events into behavioral signals
   (high-intent, search-friction, exit-risk, cart-abandonment).
3. The backend watches the signals collection and hands each new signal to the
   matching Azure AI Foundry agent.
4. The agent reasons over the signal and calls tools autonomously: the MongoDB
   MCP Server for queries and writes, and (when enrichment is on) a scoring
   gateway that featurizes the user from live Atlas data and calls Microsoft
   Fabric's real-time churn model.
5. The agent writes a Next Best Action back to Atlas, and the UI picks it up over
   a Change Stream backed SSE connection and shows it to the shopper.

## Repository structure

| Path | What it is |
|------|-----------|
| `retail-store-v2-main/` | Next.js 15 storefront (App Router). Tracks events, shows retention offers, hosts the enrichment toggle. |
| `retail-customer-retention-backend-main/` | Python/FastAPI orchestration relay. Watches signals and invokes the Foundry agents. |
| `retail-customer-retention-scoring-main/` | Python/FastAPI scoring gateway. Featurizes users from Atlas and calls Fabric's churn model. |
| `infra/` | Bicep templates for the Azure Container Apps deployment. |
| `docs/` | Architecture and setup guides (see below). |
| `deploy.ps1` | End-to-end Azure deployment script. |

## MongoDB collections

The demo uses a single Atlas database (`leafy_popup_store` by default):

- `events_ingest` - raw user behavior events
- `session_signals` - behavioral signals from Atlas Stream Processing
- `session_state` - aggregated session data (search history, browsing patterns)
- `products` - product catalog with VoyageAI embeddings for Vector Search
- `next_best_actions` - generated retention actions shown in the UI
- `carts` - shopping cart state
- `churn_risk_scores` - churn predictions written back from Fabric

## What you'll need

Provision these before you start. The core retention demo needs the first four;
the last two are only for the Fabric-enriched churn scoring.

| Requirement | For | Where |
|---|---|---|
| MongoDB Atlas cluster (M10+, Change Streams) | everything | https://cloud.mongodb.com |
| MongoDB Database Tools (`mongorestore`) + `mongosh` | restoring the seed dump, creating indexes | https://www.mongodb.com/docs/database-tools/ |
| Node.js 18+ and Python 3.12+ | storefront / backend + scoring | https://nodejs.org · https://python.org |
| VoyageAI API key (`pa-...`) | product semantic search | https://www.voyageai.com |
| Azure subscription + Azure CLI | backend, scoring, deploy | https://aka.ms/installazurecli |
| Azure AI Foundry project + a deployed chat model | the agents | https://ai.azure.com |
| Microsoft Fabric capacity (F2+) | churn model + analytics | Fabric (optional, enrichment only) |
| PowerShell / `pwsh` | the Azure deploy script | [install](https://learn.microsoft.com/powershell/scripting/install/installing-powershell) |

## Setup path

Do these in order. Each links to the detailed guide.

1. **Set up Atlas (data layer).** Create the cluster, restore the bundled seed
   data (760 products with embeddings, plus the catalog), create the two search
   indexes, and create and start the five stream processors.
   See [`docs/ATLAS_SETUP.md`](docs/ATLAS_SETUP.md).
2. **Seed the behavioral data and persona.** Run `generate_demo_data.py` from the
   backend to add session history and the high-risk demo persona.
   See the [backend README](retail-customer-retention-backend-main/README.md).
3. **Create your Azure AI Foundry project and deploy a chat model**, then register
   the agents (`setup_agents.py`).
   See [`docs/RETENTION_ENGINE_SETUP.md`](docs/RETENTION_ENGINE_SETUP.md) (Step 0)
   and the [backend README](retail-customer-retention-backend-main/README.md).
4. **Run the services.** Locally, give each a distinct port so they don't collide:
   the **storefront on 8080** (the launch URL below), the **backend on 8000**
   (`PORT=8000 python main.py`), and the **scoring gateway on 8081**
   (`PORT=8081 python main.py`). Point the storefront's `RETENTION_BACKEND_URL` at
   the backend (`http://localhost:8000`). For Azure, `deploy.ps1` stands up all four
   Container Apps (each on its own ingress, all internally 8080).
   See the per-service READMEs below and [`docs/RETENTION_ENGINE_SETUP.md`](docs/RETENTION_ENGINE_SETUP.md).
5. **Open the demo** at `http://localhost:8080/shop?feature=customerRetention`.
   The `?feature=customerRetention` flag is required, or you get the plain
   storefront with no retention panels.
6. **(Optional) Enable Fabric enrichment.** Set up the Fabric churn model and
   real-time endpoint, point the scoring gateway at it, and flip the enrichment
   toggle. See [`docs/FABRIC_SETUP.md`](docs/FABRIC_SETUP.md).

### Per-service setup

- **Frontend:** [`retail-store-v2-main/README.md`](retail-store-v2-main/README.md)
- **Backend:** [`retail-customer-retention-backend-main/README.md`](retail-customer-retention-backend-main/README.md)
- **Scoring gateway:** [`retail-customer-retention-scoring-main/README.md`](retail-customer-retention-scoring-main/README.md)

### Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) - system flow, backend call chain, agent design
- [`docs/ATLAS_SETUP.md`](docs/ATLAS_SETUP.md) - the data layer: seed restore, search indexes, stream processors
- [`docs/RETENTION_ENGINE_SETUP.md`](docs/RETENTION_ENGINE_SETUP.md) - deploy the Azure side (Container Apps, agents, Fabric wiring)
- [`docs/FABRIC_SETUP.md`](docs/FABRIC_SETUP.md) - one-time Microsoft Fabric setup (mirroring, Lakehouse, notebooks, real-time model, Power BI)

## Tech stack

- **MongoDB Atlas** - operational database, Stream Processing, Vector Search, Change Streams
- **VoyageAI** - embeddings for product search (run inside the MongoDB MCP Server)
- **Azure AI Foundry** - agent hosting and orchestration via the OpenAI Responses API
- **Azure Container Apps** - hosting for the backend and scoring services
- **Microsoft Fabric** - churn model training and serving, Power BI analytics
- **Next.js 15** - storefront

## Credits

- **Paul Leury** (MongoDB) - retention engine, Azure AI Foundry agents, Microsoft Fabric
  integration, and the end-to-end demo
- **Madhu Padmanabhan** (Microsoft) - Azure deployment scripting and Bicep infrastructure
- The Leafy storefront was originally built by MongoDB's Industry Solutions team - see the
  [storefront authors list](retail-store-v2-main/README.md#authors--contributors) for
  full credits

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
