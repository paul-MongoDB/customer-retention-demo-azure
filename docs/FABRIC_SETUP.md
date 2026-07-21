# Fabric Setup: Analytics Layer for the Retention Demo

This guide covers the one-time Microsoft Fabric infrastructure for the demo:
a Mirrored Database that replicates MongoDB Atlas to OneLake, a mirror
connector App Service that does the replication, a Lakehouse that exposes
the data to notebooks and Power BI, and the Power BI report itself.

Run this once per environment.

## Environment Values

This guide uses `<placeholder>` syntax for names that differ per tenant. Pick your names as you go and substitute consistently. The "Example" column shows the values used by the author.

| Placeholder | What it is | Example |
|---|---|---|
| `<atlas-database>` | MongoDB Atlas database for this demo | `leafy_retail_demo` |
| `<resource-group>` | Azure resource group for the mirror connector App Service | `leafy-retail-demo-rg` |
| `<mirror-app-service>` | Azure App Service running the Fabric mirror connector | `leafy-retail-mirror-app` |
| `<fabric-workspace>` | Microsoft Fabric workspace | `Leafy Retail Demo` |
| `<mirrored-db>` | Fabric Mirrored Database (MongoDB source) | `RetailDemoMirror` |
| `<lakehouse>` | Fabric Lakehouse containing mirrored data and ML outputs | `RetentionAnalytics` |
| `<powerbi-report>` | Power BI report name | `Leafy Retail - Customer Retention Analytics` |

## Prerequisites

- A Fabric capacity (F2 or higher) in a workspace you own. Create or pick a workspace and refer to it as `<fabric-workspace>` for the rest of this guide.
- MongoDB Atlas cluster already provisioned with database
  `<atlas-database>` and the demo collections (see [`ATLAS_SETUP.md`](ATLAS_SETUP.md)
  and `ARCHITECTURE.md`). `<atlas-database>` **must be the same database** you used
  for the retention engine (`LEAFY_DATABASE_NAME` in `RETENTION_ENGINE_SETUP.md`),
  or the mirror replicates a different database than the demo writes to. Atlas
  should also have the App Service outbound IPs whitelisted (you will circle back
  to this after Step 2).
- The retention backend + containers already deployed per `RETENTION_ENGINE_SETUP.md`. Not
  strictly required for Fabric to work, but the full demo assumes both.
- The mirror connector source checked out locally: clone the MongoDB Fabric Mirroring repo (https://github.com/mongodb-partners/MongoDB_Fabric_Mirroring) to any working directory.
- An Azure subscription and resource group (`<resource-group>`) to deploy the mirror connector
  App Service into. You can reuse the same resource group as the retention backend.

## Step 1: Create the Mirrored Database in Fabric

In the `<fabric-workspace>` workspace:

1. Click **New item** and pick **Mirrored Database (preview)**.
2. Name it `<mirrored-db>`.
3. When it opens, note two values from the **Mirrored database ID** and
   **Landing zone** cards at the top. You need the full Landing zone URL
   (the `https://onelake.dfs.fabric.microsoft.com/<workspace>/<db>/...`
   path) for Step 2.
4. Leave replication in the **Running** state. The mirror connector you
   deploy in Step 2 is what actually pushes data into the Landing Zone;
   Fabric is just waiting for files to arrive.

Nothing else to configure here. The Mirrored Database is a passive sink.

## Step 2: Deploy the Mirror Connector App Service

The connector is a Python/Flask service that reads MongoDB change streams,
converts documents to Parquet, and uploads them to the Landing Zone. It
runs on an Azure App Service. Source is in the
[MongoDB_Fabric_Mirroring](https://github.com/mongodb-partners/MongoDB_Fabric_Mirroring)
repo.

You have two deployment paths. Pick one.

### Option A: Deploy to Azure button (easiest)

The repo's `README.md` includes a **Deploy to Azure** button that wraps
`ARM_template.json`. Click it, fill in:

- Resource group: `<resource-group>`
- App name: `<mirror-app-service>`
- App settings:
  - `MONGO_CONN_STR` = your Atlas connection string
  - `MONGO_DB_NAME` = `<atlas-database>`
  - `MONGO_COLLECTION` = `all`
  - `LZ_URL` = the Landing zone URL you copied in Step 1
  - `APP_ID`, `SECRET`, `TENANT_ID` = Azure Service Principal credentials
    that have access to the Fabric workspace Landing Zone

Accept the rest of the defaults and deploy.

### Option B: Terraform

The repo's `terraform/` folder provisions the App Service, sets all app
settings, and optionally creates a private Atlas / App Service connection.
See the Terraform module's README for variable wiring. Use this if you
need the private link path or are managing infrastructure as code.

### Post-deployment checks

- In Azure Portal, go to the new App Service. Under **Configuration**
  confirm that all the environment variables above are present and that
  `LZ_URL` matches the Landing zone in Fabric.
- Go to **Properties** and note the outbound IPs. Whitelist them in
  MongoDB Atlas **Network Access**. Without this, the connector will fail
  to connect to Atlas.
- Two App Service settings matter for reliable mirroring:
  **Always On** must be enabled and **ARR Affinity** (Session Affinity)
  must be off. Check both under **Configuration > General settings**.
- Tail the log stream. On first start you should see `begin init sync for
  <collection>` messages and `push_file_to_lz` uploads with 404 responses
  on the existence check (404 means "file is not there yet", which is
  normal for a fresh deploy).

Return to Fabric and watch the **Monitor replication** panel on
`<mirrored-db>`. Each collection should transition to **Running**
with a non-zero **Rows replicated** count within a few minutes. If any
collection stays at zero, check the mirror connector App Service logs and
confirm the Atlas IP allowlist includes the App Service outbound IPs.

## Step 3: Create the Lakehouse and shortcuts

Notebooks and Power BI read from a Lakehouse, not directly from the
Mirrored Database. Create a Lakehouse that shortcuts into the mirror so
that one copy of the data lives in OneLake.

1. In the same workspace, **New item > Lakehouse**. Name it
   `<lakehouse>`.
2. Open the Lakehouse. In the Explorer, right-click **Tables** and pick
   **New shortcut**.
3. Choose **Microsoft OneLake** as the source.
4. Navigate to `<mirrored-db>`. Under `Tables > dbo`, check the
   individual table boxes (not the `dbo` parent): `events_ingest`,
   `next_best_actions`, `products`, `session_signals`. Click **Create**.
5. Confirm the shortcuts appear under `Tables` and that you can preview
   rows.

`session_state` is intentionally not mirrored. It has a high update
frequency and is noise for the analytics layer.

## Step 4: Import the notebooks

Two notebooks power the churn propensity story. Their source lives in the
main repo at `retail-customer-retention-backend-main/fabric_notebooks/`.
They are Python files with `# ===== Cell N =====` markers; copy each cell
block into a Fabric notebook cell.

### Train Churn Model

1. In the workspace, **New item > Notebook**. Name it `Train Churn Model`.
2. Attach it to the `<lakehouse>` Lakehouse.
3. Copy each cell block from `fabric_notebooks/train_churn_model.py` into
   its own Fabric cell in order.
4. Run all cells once to produce a saved model in the Lakehouse under
   `Files/models/`. This takes a few minutes on F2.
5. After it completes, **stop the Spark session**. F2 only allows one
   active Spark session at a time, so leaving this one alive will block
   the scoring notebook later.

### Activate the real-time model endpoint

The training notebook also registers the model as `leafy-churn-scorer` (an
MLflow model) so Fabric can serve it in real time. This powers the enriched
agents (both exit-risk and cart-abandonment, the hero enriched scenario), which
score a customer live when no batch score exists yet.

1. In the workspace, open the `leafy-churn-scorer` ML model and select the
   latest version.
2. Click **Activate version endpoint**.
3. **Set this version as the default version.** This step is easy to miss and
   it is the one that actually makes real-time scoring work. The gateway calls
   the model-level endpoint (`.../mlModels/{modelId}/endpoint/score`), which
   routes to whichever version is marked **default**. In the endpoint details,
   confirm **Default version** shows **Yes**. If it says **No**, the score URL
   returns `404 EndpointOrResourceNotFound` even for a fully authorized caller,
   because there is no version to route to. "Active" alone is not enough; you
   need Active **and** Default.
4. Turn **auto-sleep Off** (or warm it with one call right before a demo) so
   the first request does not eat a cold start.
5. Copy the **workspace ID** and **model ID** from the endpoint details. You
   set these on the scoring gateway (`FABRIC_WORKSPACE_ID` / `FABRIC_MODEL_ID`)
   during the Azure deploy (see `RETENTION_ENGINE_SETUP.md`), and you grant the
   gateway's managed identity access to this model in Fabric (Manage access on
   the workspace, add the identity as Contributor). Note that Contributor access
   is necessary but not sufficient: the calling identity also has to be allowed
   to call Fabric public APIs at the tenant level. See
   `RETENTION_ENGINE_SETUP.md` Step 9.1 for that requirement and the workaround.

Quick check that the endpoint is really live (run as any Fabric-authorized
user, substituting your IDs):

```bash
TOK=$(az account get-access-token --resource https://api.fabric.microsoft.com --query accessToken -o tsv)
curl -s -X POST "https://api.fabric.microsoft.com/v1/workspaces/<workspaceId>/mlModels/<modelId>/endpoint/score" \
  -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{"formatType":"dataframe","orientation":"values","inputs":[[20,18,1,1,8,27,0,0.9,0.0,2.5]]}'
```

A healthy endpoint returns `{"predictions":[[<prob>,"High","total_signals"]]}`. A
`404 EndpointOrResourceNotFound` means no default version. A `401` means the
caller is not allowed to call Fabric APIs (tenant setting, see below).

### Score New Users

1. **New item > Notebook**. Name it `Score New Users`.
2. Attach it to the `<lakehouse>` Lakehouse.
3. Copy each cell from `fabric_notebooks/score_new_users.py`. The first
   cell is a parameter cell.
4. Mark Cell 1 as a **parameter cell** (right-click the cell, Toggle
   parameter cell). Edit the parameter values:
   - `MONGODB_URI` = your Atlas connection string
   - `DB_NAME` = `<atlas-database>`
   - `COLLECTION_NAME` = `churn_risk_scores` (default, leave as-is)
5. Do not run it yet. Run the notebooks in order: train the model first,
   then batch-score (see the steps below).

## Step 5: Build the Power BI report

The report surfaces churn propensity and NBA effectiveness. Create it
once, then it auto-refreshes when the Lakehouse shortcuts get new data.

1. From the `<lakehouse>` Lakehouse, click **New semantic model**.
   Select all four tables plus the `churn_predictions` table (created by
   the training notebook). Give it a name like `<lakehouse> model`.
2. From the semantic model, click **Create report**.
3. Build the visuals you want. At a minimum the demo uses:
   - Churn risk distribution (count of users bucketed by
     `churn_predictions.risk_score`)
   - Recent NBAs by type (bar chart on `next_best_actions.type`)
   - Signal mix over time (line chart on `session_signals.signal` grouped
     by day)
   - NBA redemption rate (count of `next_best_actions` where `redeemed =
     true` divided by total)
4. Save as `<powerbi-report>`.

If you have an existing `.pbip` or `.pbix` you want to import instead, use
**File > Import** in the workspace.

## Verify end-to-end

1. Confirm Atlas row counts match Fabric:
   ```sql
   -- In the SQL analytics endpoint of <mirrored-db>:
   SELECT 'session_signals'   AS coll, COUNT(*) AS total FROM dbo.session_signals
   UNION ALL SELECT 'next_best_actions', COUNT(*) FROM dbo.next_best_actions
   UNION ALL SELECT 'products',          COUNT(*) FROM dbo.products
   UNION ALL SELECT 'events_ingest',     COUNT(*) FROM dbo.events_ingest;
   ```
2. Confirm the training step from Step 4 wrote a `churn_predictions` table into
   the Lakehouse (no need to re-run the notebook).
3. Refresh the Power BI report. Visuals should populate.

Once all three succeed, Fabric is ready.
