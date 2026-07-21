# Atlas Setup: the data layer

This is the first thing to set up. The storefront, backend, and scoring gateway
all read and write the same MongoDB Atlas database, so it has to exist and be
seeded before anything else works. This guide takes you from an empty Atlas
cluster to a seeded database with the search indexes and stream processors in
place.

The demo uses one database, `leafy_popup_store` by default. Whatever name you
choose, use the same value everywhere (`DATABASE_NAME` in all three services and
`--db` in the restore below).

## Step 1: Create a cluster and get the connection string

1. Create a cluster at https://cloud.mongodb.com. Use **M10 or higher**; the full demo relies on Change Streams and Atlas Stream Processing.
2. Add a database user and allow your IP under **Network Access**.
3. Copy the connection string (**Connect → Drivers**). It looks like `mongodb+srv://<user>:<pass>@<cluster>.mongodb.net/`.

## Step 2: Restore the seed data

The repo ships a MongoDB dump so you do not have to build the catalog yourself.
It lives at `retail-store-v2-main/dump/leafy_popup_store/` and contains the
`products` collection (760 products, already carrying VoyageAI `vai_text_embedding`
vectors) plus `users`, `orders`, `carts`, `locations`, `invoices`, and
`recommendations`.

From the `retail-store-v2-main` directory:

```bash
mongorestore --gzip --dir=dump/leafy_popup_store --db=leafy_popup_store \
  --uri "mongodb+srv://<user>:<pass>@<cluster>.mongodb.net/"
```

The `--db` value must match the `DATABASE_NAME` you use in the services.

The behavioral collections (`events_ingest`, `session_state`, `session_signals`,
`next_best_actions`, `churn_risk_scores`, `dlq`) are **not** in the dump. They are
created automatically at runtime: the storefront writes `events_ingest`, Atlas
Stream Processing writes `session_state`/`session_signals`/`dlq`, and the
backend/Fabric write `next_best_actions`/`churn_risk_scores`. You do not create
them by hand.

## Step 3: Create the search indexes on `products`

Semantic product search needs two Atlas Search indexes on the `products`
collection. Without them, search returns empty results with no error.

**Vector Search index** named `vs_index_vai_text_embeddings` (this is the default
the code expects; override with the `VECTOR_INDEX_NAME` env var if you rename it):

```json
{
  "fields": [
    {
      "type": "vector",
      "path": "vai_text_embedding",
      "numDimensions": 1024,
      "similarity": "cosine"
    }
  ]
}
```

The embeddings in the seed data are from VoyageAI `voyage-3-large` at 1024
dimensions, so `numDimensions` must be `1024`.

**Text Search index** named `search_index_products` (used by the backend's
recommendation agent for keyword lookups). A dynamic mapping is sufficient:

```json
{
  "mappings": { "dynamic": true }
}
```

Create both from **Atlas → your cluster → Atlas Search → Create Index** (JSON
editor), selecting the `products` collection, or with `mongosh`
(`db.products.createSearchIndex(...)`).

## Step 4: Set up Atlas Stream Processing

The storefront emits raw events; Atlas Stream Processing turns them into the
behavioral signals the backend reacts to. Create the Stream Processing workspace,
register the connection (named exactly `retail_customer_retention`), and create
and **start** all five processors, following
[external/atlas-stream-processing/README.md](../retail-customer-retention-backend-main/external/atlas-stream-processing/README.md).

## Step 5: Seed the behavioral data and the demo persona

With products in place, generate the session history and the high-risk persona.
Run these from the backend directory (`retail-customer-retention-backend-main`)
with its virtualenv set up and `MONGODB_URI` (and `DATABASE_NAME` if you changed
it) pointing at your cluster:

```bash
cd retail-customer-retention-backend-main
python3 -m venv .venv && source .venv/bin/activate   # first time only
pip install -r requirements.txt                       # first time only
export MONGODB_URI="mongodb+srv://<user>:<pass>@<cluster>.mongodb.net/"
export DATABASE_NAME=leafy_popup_store

# 1. Baseline session history across ~200 users
python generate_demo_data.py --mode baseline --clear

# 2. The high-risk demo persona. Use Grace Hopper, who ships in the seed dump:
python generate_demo_data.py --persona-uid 66fe219d625d93a100528224
```

**About the persona uid.** The demo persona is **Grace Hopper**, one of the four
shoppers in the seed dump. Her user `_id` is `66fe219d625d93a100528224`, which is
the value passed above. The seeder writes the persona under exactly that id, so it
only shows up in the storefront when you select **Grace** in the login picker.
If you re-seed with a different set of users, look up the id you want with:

```bash
mongosh "<your-uri>" leafy_popup_store --eval 'db.users.findOne({email:"grace.hopper@gmail.com"},{_id:1})'
```

The persona step seeds a genuinely high-risk history and writes **no** churn score,
so the Fabric-enriched agent scores Grace live during the demo.

> Note: `--clear` drops and recreates the behavioral collections **and empties the
> `carts` collection** from the dump. That is harmless (the storefront rewrites a
> cart the moment you add an item), but it is why the seeded carts disappear.

## Order of operations

1. Create the cluster, user, and network access (Step 1).
2. Restore the seed dump (Step 2).
3. Create the two search indexes on `products` (Step 3).
4. Create and start the five stream processors (Step 4).
5. Seed the behavioral data and persona (Step 5).

After this, the storefront search works, and once the backend and (optionally) the
scoring gateway are running, the signal-to-offer pipeline is live.
