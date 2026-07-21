# Setup Guide: Atlas + Azure Retention Demo

Step-by-step instructions to deploy the Leafy customer retention demo from scratch.

---

## Prerequisites

Before you begin, make sure you have:

1. **Azure subscription** with permissions to create resource groups, container apps, and role assignments. The deploy also writes a role assignment and an MCP connection into your **Foundry** resource group, so you need Owner or User Access Administrator on that resource group specifically.
2. **Azure CLI** installed ([https://aka.ms/installazurecli](https://aka.ms/installazurecli))
3. **PowerShell** for the deploy script. On macOS/Linux install PowerShell Core (`pwsh`): [install guide](https://learn.microsoft.com/powershell/scripting/install/installing-powershell) (macOS: `brew install --cask powershell`).
4. **Python 3.12+** for running the agent registration script
5. **A seeded MongoDB Atlas cluster** (M10 or higher, required for Change Streams). Set this up first with [`ATLAS_SETUP.md`](ATLAS_SETUP.md): it creates the database, restores the seed data, and builds the `search_index_products` and `vs_index_vai_text_embeddings` indexes.
6. **An Azure AI Foundry project with a deployed model.** If you do not have one yet, create it in Step 0 below. You will need its resource group, AI Services account name, project name, and the model deployment name.
7. **VoyageAI API key** (starts with `pa-`) for embeddings. Sign up at https://www.voyageai.com.

> The Microsoft Fabric side (mirroring, churn model, real-time ML endpoint) is a
> separate one-time setup covered in `FABRIC_SETUP.md`. The retention engine deploys
> and runs without it; only the Fabric-enriched beats (Step 9) require it. Enrichment
> gates both exit-risk and cart-abandonment; cart abandonment is the hero enriched scenario.

---

## Step 0: Create your Azure AI Foundry project and model deployment

Skip this if you already have a Foundry project with a deployed chat model. The
deploy script assumes these exist and will fail preflight without them.

You can create these in the [Azure AI Foundry portal](https://ai.azure.com)
(create a project, which provisions an AI Services account and a resource group,
then deploy a chat model into it), or with the CLI:

```bash
# 1. Create the AI Services (Foundry) account
az cognitiveservices account create \
  --name <ai-services-account> --resource-group <foundry-rg> \
  --kind AIServices --sku S0 --location <region> --yes

# 2. Deploy a chat model into it (pick a chat model available in your region)
az cognitiveservices account deployment create \
  --name <ai-services-account> --resource-group <foundry-rg> \
  --deployment-name <model-deployment-name> \
  --model-name <model> --model-version <version> \
  --model-format OpenAI --sku-capacity 20 --sku-name Standard
```

Then create a **project** under that account in the Foundry portal. From this you
get the four values the deploy needs:

- `FOUNDRY_RESOURCE_GROUP` = `<foundry-rg>`
- `FOUNDRY_AI_SERVICES_ACCOUNT` = `<ai-services-account>`
- `FOUNDRY_PROJECT_NAME` = your project name
- `AZURE_AI_MODEL_DEPLOYMENT_NAME` = `<model-deployment-name>`
- `AZURE_AI_PROJECT_ENDPOINT` = the project endpoint shown in the portal

---

## Step 1: Clone and Configure

```bash
git clone <repo-url>
cd customer-retention-demo-azure
```

### Set environment variables

**Windows:**
```batch
copy setup-env.bat setup-env.local.bat
```

**macOS/Linux:**
```bash
cp setup-env.sh setup-env.local.sh
chmod +x setup-env.local.sh
```

Edit your local copy and fill in the required values:

| Variable | Description | Example |
|---|---|---|
| `MONGODB_URI` | Atlas connection string | `mongodb+srv://user:pass@cluster.mongodb.net/` |
| `AZURE_AI_PROJECT_ENDPOINT` | Foundry project endpoint | `https://your-resource.services.ai.azure.com/api/projects/YourProject` |
| `VOYAGE_API_KEY` | VoyageAI API key | `pa-xxxxxxxxxxxxxxxxxxxx` |
| `FOUNDRY_RESOURCE_GROUP` | Resource group containing the Foundry AI Services account | `my-foundry-rg` |
| `FOUNDRY_AI_SERVICES_ACCOUNT` | Name of the AI Services account in Foundry | `my-ai-services` |
| `FOUNDRY_PROJECT_NAME` | Name of the Foundry project | `my-foundry-project` |

You must also set the model deployment name (no safe default, it has to match the
deployment you created in Step 0):

| Variable | Description |
|---|---|
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | The exact name of the model deployment in your Foundry project (from Step 0) |

Optional variables (the defaults work for most setups):

| Variable | Default | Description |
|---|---|---|
| `LEAFY_ENVIRONMENT_NAME` | `leafy-demo` | Prefix for all Azure resource names |
| `LEAFY_LOCATION` | `westus` | Azure region |
| `LEAFY_RESOURCE_GROUP` | `leafy-retention-demo-rg` | Resource group name |
| `LEAFY_DATABASE_NAME` | `leafy_popup_store` | MongoDB database name. Set this at deploy time; the code's `DATABASE_NAME` is derived from it, so setting `DATABASE_NAME` alone at deploy time has no effect. |

> **Important:** Never commit `setup-env.local.bat` or `setup-env.local.sh` to source control. They contain secrets.

---

## Step 2: Login to Azure

```bash
az login
```

Verify you are on the correct subscription:

```bash
az account show --query "{name:name, id:id}" -o table
```

---

## Step 3: Deploy Infrastructure

Run the setup script which sets environment variables and calls `deploy.ps1`:

**Windows:**
```batch
setup-env.local.bat
```

**macOS/Linux:**
```bash
./setup-env.local.sh
```

This runs 8 steps automatically:

1. **Resource Group** -- creates `leafy-retention-demo-rg` (or your custom name)
2. **Shared Infrastructure (Bicep stage 1)** -- provisions Managed Identity, Azure Container Registry, Log Analytics, and Container Apps Environment
3. **Environment readiness wait** -- polls the Container Apps Environment until `provisioningState` is `Succeeded` (background tag policies can briefly knock it back into `Updating`; deploying apps during that window fails)
4. **Container Apps (Bicep stage 2)** -- provisions four Container Apps (MCP Server, Backend, Frontend, Scoring Gateway)
5. **Docker Image Build** -- builds backend, frontend, and scoring images remotely in ACR (no local Docker needed)
6. **Container Update** -- deploys the built images to the Container Apps and sets `MCP_SERVER_URL` and `SCORING_SERVICE_URL` on the backend
7. **RBAC** -- assigns "Cognitive Services User" and "Azure AI User" roles to the managed identity (the latter now displays as "Foundry User" in the portal)
8. **MCP Connection** -- registers the MongoDB MCP Server as a Foundry project connection

The script outputs the URLs for all four services when complete.

> **Note:** RBAC role assignments can take up to 5 minutes to propagate. If you see 401/PermissionDenied errors immediately after deploy, wait a few minutes and retry.

---

## Step 4: Whitelist IPs in MongoDB Atlas

The MCP Server container needs to connect to your Atlas cluster. Get its outbound IP:

```bash
az containerapp show \
  --name leafy-demo-mcp-server \
  --resource-group leafy-retention-demo-rg \
  --query 'properties.outboundIpAddresses' -o tsv
```

Add that IP (or `0.0.0.0/0` for testing) to **MongoDB Atlas > Network Access > IP Access List**.

> All container apps in the same environment share the same outbound IP(s), so this one
> entry also covers the backend and the scoring gateway. No separate entries are needed.

---

## Step 5: Register Agents in Foundry

Agents must be registered before the backend can invoke them. This is a one-time step (re-run to update instructions).

```bash
cd retail-customer-retention-backend-main
pip install -r requirements.txt
```

> **Note:** install from `requirements.txt`, not ad hoc. It pins `azure-ai-projects==2.2.0`;
> older 2.0.x versions lack `OpenApiTool` and the enriched agent silently registers
> without its churn scoring tool.

The easiest way is to create a `.env` file in the `retail-customer-retention-backend-main` directory. Copy `EXAMPLE.env` and fill in values:

```bash
cp EXAMPLE.env .env
```

Edit `.env` with the required values:

```env
MONGODB_URI=mongodb+srv://user:pass@cluster.mongodb.net/
DATABASE_NAME=leafy_popup_store
MCP_SERVER_URL=https://leafy-demo-mcp-server.<your-env-id>.westus.azurecontainerapps.io/mcp
SCORING_SERVICE_URL=https://leafy-demo-scoring.<your-env-id>.westus.azurecontainerapps.io
AZURE_AI_PROJECT_ENDPOINT=https://<your-resource>.services.ai.azure.com/api/projects/<YourProject>
AZURE_AI_MODEL_DEPLOYMENT_NAME=<your-model-deployment-name>
```

> **Note:** `SCORING_SERVICE_URL` is the scoring gateway URL from Step 3. It tells the
> enriched agent's `score_churn` tool where to call. If it is missing, the enriched
> agent registers without the scoring tool.

> **Note:** `MONGODB_URI` is required because `setup_agents.py` imports `config.py` which requires it, but it is not actually used during agent registration. A dummy value works.

> **Note:** `DATABASE_NAME` is used to template the agent instructions. Make sure it matches the database your Atlas cluster uses.

Run the setup script:

```bash
python setup_agents.py
```

This deletes any existing agents with matching names and recreates them with the current instructions (including the configured database name). It registers 8 agents in your Foundry project:

| Agent | Type | Signal |
|---|---|---|
| ContextAnalyzer | Prompt | search-friction (step 1) |
| RecommendationWriter | Prompt | search-friction (step 2) |
| SocialProofAgent | Prompt | high-intent |
| ShippingDiscountAgent | Prompt | exit-risk (enrichment off) |
| ShippingDiscountAgentEnriched | Prompt | exit-risk (enrichment on; has the `score_churn` tool) |
| CartRescueAgent | Prompt | cart-abandonment (enrichment off) |
| CartRescueAgentEnriched | Prompt | cart-abandonment (enrichment on; has the `score_churn` tool) |
| SearchFrictionWorkflow | Workflow | search-friction (orchestration) |

In the script output, confirm BOTH enriched agent lines read
`(+ churn scoring tool)`: `[created] ShippingDiscountAgentEnriched  (+ churn scoring tool)`
and `[created] CartRescueAgentEnriched  (+ churn scoring tool)` (the two are driven by the
`SCORING_TOOL_AGENTS` set in `setup_agents.py`). If it warns the tool was dropped, check the
`azure-ai-projects` version and `SCORING_SERVICE_URL` (notes above).

Verify in the Foundry portal: go to [https://ai.azure.com](https://ai.azure.com), open your project, and check the **Agents** section.

---

## Step 6: Assign RBAC for Agent Creation (if needed)

If `setup_agents.py` fails with a 403 error, the managed identity or your user account may need the **Azure AI Developer** role on the Foundry project's resource group:

```bash
az role assignment create \
  --assignee-object-id <your-user-or-identity-oid> \
  --assignee-principal-type User \
  --role "Azure AI Developer" \
  --scope "/subscriptions/<sub-id>/resourceGroups/<foundry-rg>"
```

---

## Step 7: Verify Deployment

### Check container health

```bash
# Backend
curl https://leafy-demo-backend.<env-id>.westus.azurecontainerapps.io/health

# Frontend
curl https://leafy-demo-frontend.<env-id>.westus.azurecontainerapps.io
```

### Check backend logs

```bash
az containerapp logs show \
  --name leafy-demo-backend \
  --resource-group leafy-retention-demo-rg \
  --type console --tail 20
```

You should see:
```
Foundry agents initialized. Model: <your-model-deployment-name>, Agents: ['SearchFrictionWorkflow', 'SocialProofAgent', 'ShippingDiscountAgent', 'CartRescueAgent']
Change stream opened, waiting for changes...
Uvicorn running on http://0.0.0.0:8080
```

(The log lists the four default signal routes: high-intent, search-friction, exit-risk,
cart-abandonment. The enriched variants `ShippingDiscountAgentEnriched` and
`CartRescueAgentEnriched` are swapped in at runtime when Fabric enrichment is on; they do
not appear in this line.)

### Check the change stream watcher

The change stream thread can die while the container stays healthy. Verify it directly:

```bash
curl https://leafy-demo-backend.<env-id>.westus.azurecontainerapps.io/debug
```

Expect `"change_stream_thread_alive": true`. If false, restart the revision:
`az containerapp revision restart`.

### Check Foundry agents

Go to [https://ai.azure.com](https://ai.azure.com) and verify all 8 agents appear in your project.

---

## Step 8: Test End-to-End

### Option A: Use the UI

1. Open the frontend URL in your browser
2. Browse products, search for items, show exit intent (move mouse to top of page)
3. Watch for notification popups (NBA actions generated by the agents)

### Option B: Use the test endpoint

The backend has a built-in test endpoint that fires a signal through the agent pipeline without needing to insert into MongoDB:

```bash
# Test exit-risk
curl -X POST https://leafy-demo-backend.<env-id>.westus.azurecontainerapps.io/test-signal/exit-risk

# Test high-intent
curl -X POST https://leafy-demo-backend.<env-id>.westus.azurecontainerapps.io/test-signal/high-intent

# Test search-friction (workflow agent)
curl -X POST https://leafy-demo-backend.<env-id>.westus.azurecontainerapps.io/test-signal/search-friction
```

Each call invokes the corresponding Foundry agent and returns the result. Check `next_best_actions` in Atlas for the new NBA documents.

### Option C: Insert a test signal directly

Insert a test document into `session_signals` in MongoDB Atlas:

```json
{
  "signal": "exit-risk",
  "uid": "test-user-123",
  "sid": "test-session-456",
  "severity": "medium",
  "evidence": "mouse moved toward close button"
}
```

Check `next_best_actions` for a new document with `type: "shipping-discount"`.

### Option D: Test via Foundry playground

In the Foundry portal, open any agent (e.g., ShippingDiscountAgent), click the playground, and send:

```
Process this customer behavioral signal.

Signal Type: exit-risk
User ID: test-user-123
Session ID: test-session-456
Severity: high
Evidence: rapid scroll and tab switching
Product ID: N/A
```

---

## Step 9: Enable Fabric Real-Time Enrichment

This wires the scoring gateway to Fabric's real-time churn model so the enriched agents
(both exit-risk and cart-abandonment) can escalate based on a live score. **Prerequisite:** the Fabric side must exist first,
including the activated `leafy-churn-scorer` model endpoint. Follow `FABRIC_SETUP.md`
(Step 4, "Activate the real-time model endpoint") and copy the **workspace ID** and
**model ID** from the endpoint details.

### 9.1 Grant the gateway access to the model

In Fabric, open the workspace, click **Manage access**, add the deploy's managed identity
(`<env-prefix>-identity`, client ID printed by the deploy) as **Contributor**.

**This is necessary but not sufficient, and it is the single most likely thing to block
the demo.** Workspace Contributor lets the identity be *authorized* on the model, but
Fabric will still reject its API calls with **`401 Unauthorized`** unless the tenant
allows service principals and managed identities to call Fabric public APIs. That is a
**tenant-level Fabric Admin setting**, not something a workspace admin can flip:

> Fabric Admin portal > Tenant settings > Developer settings >
> **"Service principals and managed identities can call Fabric public APIs"** > Enabled
> (and, if it is scoped to a security group, add `<env-prefix>-identity` to that group).

In many orgs this is an IT ticket and can take time. How to tell which problem you have:
a **401** on `/score` means this tenant setting (principal not allowed); a **404** means
the model endpoint has no default version (see `FABRIC_SETUP.md`). Do not "fix" a 401 by
raising the workspace role to Admin, that changes the wrong axis (a role problem would be
403, not 401).

**Workaround when the tenant setting cannot be enabled in time.** Only a *user* identity
can call Fabric until the tenant setting is on, so run the scoring gateway locally under
your own `az login` and expose it to Foundry with a tunnel. This keeps everything else
(backend, agents, mirror, Fabric model) in the cloud and is invisible in the demo UI,
which never shows the gateway.

1. Run the gateway locally as your user (no `AZURE_CLIENT_ID`, so `DefaultAzureCredential`
   falls through to your `az` login, which is a real user and is allowed to call Fabric):
   ```bash
   cd retail-customer-retention-scoring-main
   # .env: MONGODB_URI, DATABASE_NAME, FABRIC_API_BASE, FABRIC_WORKSPACE_ID, FABRIC_MODEL_ID, PORT=8081
   python main.py
   curl -s -X POST localhost:8081/score -H 'Content-Type: application/json' -d '{"uid":"<persona-uid>"}'
   ```
2. Expose it (QUIC is often blocked, so force http2):
   ```bash
   cloudflared tunnel --protocol http2 --url http://localhost:8081
   ```
3. Point the Foundry `score_churn` tool at the tunnel URL and re-register (this registers
   the tool on BOTH enriched agents, `ShippingDiscountAgentEnriched` and `CartRescueAgentEnriched`):
   ```bash
   cd ../retail-customer-retention-backend-main
   SCORING_SERVICE_URL="https://<your-tunnel>.trycloudflare.com" python setup_agents.py
   ```
4. Run the demo. After recording, flip it back by re-running `setup_agents.py` with
   `SCORING_SERVICE_URL` set to the deployed gateway FQDN.

> **Quick-tunnels die silently.** A `cloudflared` quick-tunnel's public URL can stop
> resolving while the `cloudflared` process keeps running (the local gateway stays healthy).
> The symptom is the enriched agents producing no NBA and the backend logging an
> `openai.APIError` "Client error while sending request" on `score_churn`. Recovery: kill
> and restart `cloudflared tunnel --protocol http2 --url http://localhost:8081`, grab the
> NEW URL (it changes every restart) from the startup banner or
> `curl 127.0.0.1:<metrics-port>/quicktunnel` (find the port with
> `lsof -nP -iTCP -sTCP:LISTEN -a -p <cloudflared-pid>`), then re-run step 3 with the new URL.
> The deployed backend does not need the tunnel directly; only Foundry (executing
> `score_churn`) calls it, so the deployed backend + tunnel work together.

### 9.2 Set the Fabric IDs on the scoring gateway

Use a unique `--revision-suffix` so the change reliably produces a new revision:

```bash
az containerapp update --name leafy-demo-scoring --resource-group leafy-retention-demo-rg \
  --revision-suffix fabricfix1 \
  --set-env-vars FABRIC_WORKSPACE_ID=<workspaceId> FABRIC_MODEL_ID=<modelId>
```

### 9.3 Verify against the live gateway

```bash
curl https://leafy-demo-scoring.<env-id>.westus.azurecontainerapps.io/health
```

Expect `{"status":"ok","fabric_configured":true}`. Trust this health check, not
`az containerapp show` template output (see Deployment Gotchas below).

### 9.4 Test the enrichment toggle

Enrichment starts **off** (`FABRIC_ENRICHMENT_ENABLED=false`). During the demo you flip it
with the in-UI **Fabric real-time enrichment** toggle at the top of the retention drawer
(it proxies to the backend and its state persists across the shop and cart pages). The
two-run demo flow runs baseline first (enrichment off), then the Fabric-escalated decision
(enrichment on); the hero gesture is cart abandonment (add to cart, open the cart, dwell).
Quick backend smoke test without the UI:

```bash
# read state, flip on, clear the persona's cached score, then trigger a gesture in the UI
curl https://<backend-fqdn>/enrichment
curl -X POST https://<backend-fqdn>/enrichment/on
curl -X DELETE https://<backend-fqdn>/churn-score/<uid>
```

---

## Architecture Overview

See `ARCHITECTURE.md` for the system flow, backend call chain, agent design, and key
services. Summary: four Container Apps (MCP Server, Backend, Frontend, Scoring Gateway)
in front of MongoDB Atlas, Azure AI Foundry agents, and Fabric's real-time churn model.

---

## Updating Agents

Agent instructions are defined in `foundry_agents.py` (the single source of truth). The database name is read from the `DATABASE_NAME` environment variable (via `config.py`). To modify instructions:

1. Edit the instruction constants in `foundry_agents.py`
2. Re-run `python setup_agents.py` (it deletes existing agents and recreates them with the current instructions)
3. Rebuild and redeploy the backend container (the instructions are also used for logging context)

The backend invokes agents by name via `agent_reference`. As long as the agent names stay the same, no other code changes are needed.

---

## Deployment Gotchas

Hard-won operational knowledge. Read this when a deploy misbehaves.

### The Container Apps environment can churn

Subscription-level automation (tag policies and similar governance tooling, common
in corporate subscriptions) can fire "Create or Update Managed Environment" every few minutes,
knocking the environment into `provisioningState: Updating`. While it is `Updating`,
operations fail with `ManagedEnvironmentNotProvisioned`, `az` commands run slowly or time
out, and env-var updates can "succeed" (exit 0) without taking effect.

You cannot disable such policies. Confirm the cause in the environment's **Activity log**
(the "Event initiated by" column). Workarounds:

1. **Wait for `Succeeded`, then act, and retry.** `deploy.ps1` does this between its two
   Bicep stages. For standalone commands, poll
   `az containerapp env show ... --query properties.provisioningState` first.
2. **Force a new revision for env-var changes.** Plain `--set-env-vars` can silently fail
   to persist during churn. Add `--revision-suffix <unique-name>` (as in Step 9.2).
3. **Verify against the running app, not the template.** `az containerapp show` can
   report values that are not live. Trust the app's own `/health` endpoint.

### Redeploying a single container image after a code change

`deploy.ps1` builds and pushes everything. To rebuild just one app (e.g. the backend after
changing agent code) without a full deploy, build the image in ACR and roll a new revision:

```bash
az acr build --registry <acr-name> --image <backend-container-app>:latest \
  retail-customer-retention-backend-main
az containerapp update -n <backend-container-app> -g <resource-group> \
  --image <acr-name>.azurecr.io/<backend-container-app>:latest \
  --revision-suffix <unique-name>
```

`az acr build` builds in the cloud (no local Docker needed). The `--revision-suffix` is
required because the image tag (`:latest`) does not change, so Container Apps would
otherwise not pull the new image. Each container dir has a `.dockerignore` (it keeps the
local `.venv` and `external` out of the build context, which otherwise
uploads hundreds of MB). Verify with the app's `/health` and `/debug`, not the template.

### OpenApiTool API is SDK-version-specific

`setup_agents.py` builds the `score_churn` tool with `azure-ai-projects` 2.2.x, where
`OpenApiTool` is a wrapper: `name`/`description`/`spec`/`auth` go on a nested
`OpenApiFunctionDefinition`, not as direct kwargs. Version 2.0.x lacks `OpenApiTool`
entirely and the enriched agent silently registers without the tool. Keep the
`requirements.txt` pin and confirm the `(+ churn scoring tool)` line in the output.

### Role names have been renamed

The "Azure AI User" role now displays as **"Foundry User"** in the portal. If `deploy.ps1`
warns the assignment may have failed, verify with `az role assignment list` before
re-assigning; seeing "Foundry User" means it worked.

### Post-deploy sanity checklist

- Scoring `/health` returns `fabric_configured: true` (after Step 9).
- Agent registration output shows BOTH `ShippingDiscountAgentEnriched  (+ churn scoring tool)` and `CartRescueAgentEnriched  (+ churn scoring tool)`.
- Scoring app image is `<acr>/<env-prefix>-scoring:latest`, not the
  `mcr.microsoft.com/k8se/quickstart` placeholder.
- Managed identity has "Foundry User" on the AI Services account.
- Backend `/debug` shows `change_stream_thread_alive: true`.

---

## Troubleshooting

| Issue | Fix |
|---|---|
| Backend crashes with "aiohttp not installed" | Ensure `aiohttp` is in `requirements.txt` and rebuild the image |
| Agent invocation returns 404 | Agents not registered. Run `setup_agents.py` |
| Workflow agent fails at InvokeAzureAgent | MCPTool missing `server_url`. Re-register agents with `setup_agents.py` |
| MCP Server connection refused | Check Atlas IP whitelist (Step 4) |
| "Unauthorized" from Foundry API | Managed identity needs both "Cognitive Services User" (subscription scope) and "Azure AI User" / "Foundry User" (AI Services account scope). RBAC can take up to 5 minutes to propagate after assignment |
| Change stream not firing | Atlas cluster must be M10+ for Change Streams. Check `MONGODB_URI` is correct. Check `/debug` for `change_stream_thread_alive` |
| Frontend shows no notifications | Verify `next_best_actions` collection has documents. Check SSE endpoint in browser dev tools |
| Scoring gateway `fabric_configured: false` | `FABRIC_WORKSPACE_ID`/`FABRIC_MODEL_ID` not live on the serving revision. Re-apply with `--revision-suffix` (Step 9.2) |
| Scoring `/score` returns 403 from Fabric | The managed identity lacks access to the model. Grant it in the Fabric workspace (Step 9.1) |
| Container restart doesn't pick up new image | Same image tag (`latest`) doesn't create a new revision. Use `az containerapp revision restart` |

---

## Cleanup

To remove all Azure resources:

```bash
az group delete --name leafy-retention-demo-rg --yes
```

To remove Foundry agents, delete them in the portal or via the API.
