# ⚡  MongoDB Atlas Stream Processing Setup for Retail Retention Demo

This guide describes how to configure the **MongoDB Atlas Stream Processing** environment used in the Retail Customer Retention demo.  
The setup includes creating a Stream Processing workspace and registering the Atlas database connection used by the processors.

---

## 1. Create a Stream Processing Workspace

In **MongoDB Atlas**:

`Streaming Data → Stream Processing → Create Workspace`

### Recommended Settings

| Setting | Value | Reason |
|------|------|------|
| **Workspace Name** | `retail-retention-demo` | Clear ownership and purpose; easy to identify later. |
| **Tier** | `SP10` | Sufficient for demo-scale pipelines (~2k sessions) while keeping costs low. |
| **Provider / Region** | `Azure / <your Atlas cluster region>` (this demo runs on Azure, e.g. West US) | Match your Atlas cluster's provider and region to reduce latency and avoid cross-region traffic. Atlas Stream Processing supports Azure (and AWS/GCP); pick the provider your cluster runs on. |
| **Maximum Tier Size (optional)** | Leave default or set to `SP30` | Allows quick scale-up if needed without enabling autoscaling. |

---

## 2. Register the Atlas Database Connection (Connection Registry)

Navigate to your **Stream Processing workspace**:

`Workspace → Connection Registry → Add Connection`

### Connection Configuration

| Setting | Value |
|------|------|
| **Connection Type** | `Atlas Database` |
| **Connection Name** | `retail_customer_retention` |
| **Atlas Cluster** | Select the cluster containing the `leafy_popup_store` database |
| **Execute As** | `Read and write to any database` |

> **The connection name must be exactly `retail_customer_retention`.** All five
> processor definitions hardcode this name (`connectionName`), so any other value
> silently breaks every processor.

### Why These Permissions?

Across the processors, the connection must:

- **Read from:** `events_ingest`
- **Write to:** `session_state`, `session_signals`, and `dlq` (dead-letter queue)

Granting **read and write access to any database** keeps the configuration simple and is the standard permission model for demos.

---

## 3. Create the Stream Processors (ASPs)

You need to create **5 Atlas Stream Processors** in your workspace. Follow the detailed steps below for the first processor, then replicate the same process for the remaining four.

Each `.json` file in this directory is a full processor payload with `name`,
`options` (asp1 also has a `dlq` block), and `pipeline` keys. Create each
processor with `mongosh` connected to your Stream Processing workspace:

```javascript
// asp1 needs its options (dlq) block; pass all three parts
sp.createStreamProcessor("asp1_session_state_builder", <pipeline array>, <options object>)

// the asp2 processors have no options block
sp.createStreamProcessor("asp2_exit_risk", <pipeline array>)
```

If you use the Atlas UI **Processor Definition** editor instead, paste the
`pipeline` array (and, for asp1, set the DLQ under the processor options).

### Create ASP 1: Session State Builder

1. Navigate to your **Stream Processing workspace**
2. Click **Create Processor** (or use `sp.createStreamProcessor` in `mongosh`)
3. Enter the processor name: `asp1_session_state_builder`
4. Open [asp1_session_state_builder.json](./asp1_session_state_builder.json) from this repository
5. Use its `pipeline` and `options` (the `dlq` block) to define the processor
6. Create the processor
7. Click **Start** to begin processing (a created-but-not-started processor produces nothing)

### Create the Remaining ASPs

Replicate the same steps for these four processors:

| Processor Name | Source File |
|----------------|-------------|
| `asp2_exit_risk` | [asp2_exit_risk.json](./asp2_exit_risk.json) |
| `asp2_high_intent` | [asp2_high_intent.json](./asp2_high_intent.json) |
| `asp2_search_friction` | [asp2_search_friction.json](./asp2_search_friction.json) |
| `asp2_cart_abandonment` | [asp2_cart_abandonment.json](./asp2_cart_abandonment.json) |

**Start every processor.** Creating a processor does not run it; each one must be
Started before it will read events and write signals.

### Important

This connection will be reused by the stream processor as both:

- **Source** (reading incoming events)
- **Sink** (writing session state updates)

---