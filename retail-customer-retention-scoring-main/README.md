# Leafy Churn Scoring Gateway

A thin FastAPI gateway that lets the exit-risk retention agent get a **real-time
churn score from Microsoft Fabric** when a customer has no cached score yet.

The churn model is trained **and served in Fabric**: the training notebook
registers it as an MLflow model, and Fabric exposes a managed real-time ML model
endpoint for it. This gateway does **not** host the model. It only:

1. computes the customer's 10 fresh behavioral features from Atlas (the
   Atlas to Fabric mirror has lag, so freshness must come from Atlas),
2. calls **Fabric's model endpoint** for the prediction,
3. writes the result back to the `churn_risk_scores` collection (which lights up
   the storefront churn panel), and returns it.

So the model and the inference are Fabric's; this service gathers fresh features
and relays the call. The feature engineering in `features.py` is identical to the
Fabric notebooks, so real-time scores match Fabric's batch scores.

## Configuration

Set these (see `EXAMPLE.env`):
- `MONGODB_URI`, `DATABASE_NAME` -- Atlas (featurization + write-back).
- `FABRIC_WORKSPACE_ID`, `FABRIC_MODEL_ID` -- the Fabric workspace and registered
  model (from the model's endpoint details). `FABRIC_API_BASE` defaults to
  `https://api.fabric.microsoft.com`.
- Auth: locally, `az login` (DefaultAzureCredential). In Azure, set
  `AZURE_CLIENT_ID` to the gateway's user-assigned managed identity. The identity
  needs write permission on the Fabric model (`MLModel.ReadWrite.All` /
  `Item.ReadWrite.All`, or workspace Contributor).

## Prerequisites in Fabric

1. Run the `train_churn_model` notebook (it lives in the backend repo under
   `retail-customer-retention-backend-main/fabric_notebooks/`) -- it trains the
   RandomForest and registers it as an MLflow model with a real-time endpoint.
2. Activate the model version's endpoint (UI "Activate version endpoint" or the
   REST Activate operation). Turn auto-sleep off, or warm it before a demo, to
   avoid the idle cold start.

## Running locally

Requires Python 3.12.

```bash
pip install -r requirements.txt
cp EXAMPLE.env .env   # fill in MONGODB_URI, DATABASE_NAME, FABRIC_WORKSPACE_ID, FABRIC_MODEL_ID
az login              # for the Fabric token via DefaultAzureCredential
PORT=8081 python main.py
curl -X POST localhost:8081/score -H 'content-type: application/json' -d '{"uid":"<a-uid>"}'
```

## Request / response

```jsonc
// request (AML-style, or the flat {"uid": "..."} form)
{ "input_data": { "columns": ["uid"], "data": [["<uid>"]] } }

// response
{ "predictions": [ {
  "uid": "<uid>", "churn_probability": 0.82, "churn_risk_tier": "High",
  "top_risk_factor": "exit_risk_ratio", "engagement_rate": 0.0,
  "total_signals": 7, "features": { /* all 10 */ },
  "scored_at": "<iso>", "written_back": true
} ] }
```
