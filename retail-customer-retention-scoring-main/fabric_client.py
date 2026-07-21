"""
Client for Microsoft Fabric's real-time ML model endpoint.

The churn model is trained and served in Fabric (a registered MLflow model with
a real-time endpoint). This module gets a Microsoft Entra token and calls the
model's scoring endpoint, so the gateway never hosts the model -- the inference
runs in Fabric.

Endpoint (from the Fabric REST API docs):
    POST {base}/v1/workspaces/{workspaceId}/mlModels/{modelId}/endpoint/score
    body: {"formatType": "dataframe", "orientation": "values", "inputs": [[...]]}
    -> {"predictions": [[...]]}   (200), or 202 long-running operation.
"""
import logging
import time

import httpx
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

import features as feat
from config import (
    AZURE_CLIENT_ID,
    FABRIC_API_BASE,
    FABRIC_MODEL_ID,
    FABRIC_WORKSPACE_ID,
)

logger = logging.getLogger("scoring-service")

# The Fabric REST API token audience.
_FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"

_credential = None


def _get_credential():
    global _credential
    if _credential is None:
        if AZURE_CLIENT_ID:
            _credential = ManagedIdentityCredential(client_id=AZURE_CLIENT_ID)
        else:
            _credential = DefaultAzureCredential()
    return _credential


def is_configured() -> bool:
    return bool(FABRIC_WORKSPACE_ID and FABRIC_MODEL_ID)


def _score_url() -> str:
    return (
        f"{FABRIC_API_BASE.rstrip('/')}/v1/workspaces/{FABRIC_WORKSPACE_ID}"
        f"/mlModels/{FABRIC_MODEL_ID}/endpoint/score"
    )


def score_features(feature_row) -> dict:
    """Score one feature row (keyed by FEATURE_COLUMNS) against the Fabric model
    endpoint. Returns {churn_probability, churn_risk_tier, top_risk_factor}."""
    if not is_configured():
        raise RuntimeError(
            "FABRIC_WORKSPACE_ID and FABRIC_MODEL_ID must be set to call Fabric."
        )

    values = [float(feature_row[c]) for c in feat.FEATURE_COLUMNS]
    headers = {
        "Authorization": f"Bearer {_get_credential().get_token(_FABRIC_SCOPE).token}",
        "Content-Type": "application/json",
    }
    body = {"formatType": "dataframe", "orientation": "values", "inputs": [values]}

    with httpx.Client(timeout=90) as client:
        resp = client.post(_score_url(), headers=headers, json=body)
        if resp.status_code == 202:  # long-running operation
            resp = _await_lro(client, resp, headers)
        resp.raise_for_status()
        data = resp.json()

    return _parse_predictions(data)


def _await_lro(client, resp, headers, max_wait=80):
    """Poll a 202 long-running scoring operation until it returns a 200 result."""
    location = resp.headers.get("Location")
    retry_after = int(resp.headers.get("Retry-After", "3"))
    waited = 0
    while location and waited < max_wait:
        time.sleep(min(retry_after, max_wait - waited))
        waited += retry_after
        poll = client.get(location, headers={"Authorization": headers["Authorization"]})
        if poll.status_code == 200:
            return poll
        poll.raise_for_status()
    raise TimeoutError("Fabric scoring did not complete within the wait window.")


def _parse_predictions(data: dict) -> dict:
    """Parse the scoring response. The registered pyfunc returns
    [churn_probability, churn_risk_tier, top_risk_factor] per row."""
    preds = data.get("predictions")
    if not preds:
        raise ValueError(f"No predictions in Fabric response: {data}")
    row = preds[0]
    if isinstance(row, dict):  # record orientation
        return {
            "churn_probability": float(row["churn_probability"]),
            "churn_risk_tier": str(row["churn_risk_tier"]),
            "top_risk_factor": str(row["top_risk_factor"]),
        }
    # values orientation: [prob, tier, top_factor]
    return {
        "churn_probability": float(row[0]),
        "churn_risk_tier": str(row[1]),
        "top_risk_factor": str(row[2]),
    }
