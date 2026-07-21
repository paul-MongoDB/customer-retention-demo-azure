"""
Real-time churn scoring gateway.

The churn model is trained and served in Microsoft Fabric (a registered ML model
with a real-time endpoint). This gateway computes the customer's fresh behavioral
features from Atlas, calls Fabric's model endpoint for the score, writes the
result back to churn_risk_scores (which the storefront panel reads), and returns
it. The model and the inference run in Fabric; this service only gathers fresh
features (the Atlas->Fabric mirror has lag, so freshness must come from Atlas)
and relays the call.
"""
import logging
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import fabric_client
import features as feat
from config import CHURN_RISK_SCORES_COLLECTION, PORT
from mongo import get_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("scoring-service")

app = FastAPI(title="Leafy Churn Scoring Gateway")


class ScoreRequest(BaseModel):
    # AML-style shape: {"input_data": {"columns": ["uid"], "data": [["u1"]]}}
    # Flat convenience shape: {"uid": "u1"}
    input_data: dict | None = None
    uid: str | None = None


def _extract_uids(req: ScoreRequest):
    if req.input_data:
        cols = req.input_data.get("columns") or []
        rows = req.input_data.get("data") or []
        if "uid" in cols:
            i = cols.index("uid")
            return [r[i] for r in rows]
        return [r[0] for r in rows if r]
    if req.uid:
        return [req.uid]
    raise HTTPException(status_code=422, detail="Provide 'uid' or AML-style 'input_data'.")


@app.get("/")
def root():
    return {
        "status": "healthy",
        "service": "leafy-churn-scoring-gateway",
        "fabric_configured": fabric_client.is_configured(),
    }


@app.get("/health")
def health():
    return {"status": "ok", "fabric_configured": fabric_client.is_configured()}


@app.post("/score")
def score(req: ScoreRequest):
    uids = _extract_uids(req)
    db = get_db()
    df = feat.compute_features(db, uids)
    scored_at = datetime.now(timezone.utc)
    coll = db[CHURN_RISK_SCORES_COLLECTION]

    predictions = []
    for uid in uids:
        match = df[df["uid"] == uid]
        if match.empty:
            # Genuinely no behavioral signals for this user. Do not fabricate a
            # score and do not bother Fabric.
            predictions.append({
                "uid": uid,
                "churn_probability": 0.0,
                "churn_risk_tier": "Low",
                "top_risk_factor": None,
                "engagement_rate": 0.0,
                "total_signals": 0,
                "features": None,
                "scored_at": scored_at.isoformat(),
                "written_back": False,
                "note": "no behavioral signals for this user",
            })
            logger.info("Scored uid=%s -> no signals, default Low (no Fabric call)", uid)
            continue

        row = match.iloc[0]
        features_dict = {
            "total_signals": int(row["total_signals"]),
            "exit_risk_count": int(row["exit_risk_count"]),
            "search_friction_count": int(row["search_friction_count"]),
            "high_intent_count": int(row["high_intent_count"]),
            "session_count": int(row["session_count"]),
            "total_nbas": int(row["total_nbas"]),
            "redeemed_count": int(row["redeemed_count"]),
            "exit_risk_ratio": float(row["exit_risk_ratio"]),
            "engagement_rate": float(row["engagement_rate"]),
            "signals_per_session": float(row["signals_per_session"]),
        }

        # The model runs in Fabric. Send the fresh features, get the score back.
        try:
            pred = fabric_client.score_features(row)
        except Exception as e:  # noqa: BLE001 -- surface Fabric failures to the caller
            logger.error("Fabric scoring failed for uid=%s: %s", uid, e)
            raise HTTPException(status_code=502, detail=f"Fabric scoring failed: {e}")

        # Write back the exact schema the Fabric batch notebook writes, so the
        # storefront churn panel (ChurnRiskPanel.jsx) lights up with no UI change.
        doc = {
            "uid": uid,
            "churn_probability": pred["churn_probability"],
            "churn_risk_tier": pred["churn_risk_tier"],
            "scored_at": scored_at,
            "top_risk_factor": pred["top_risk_factor"],
            "total_signals": int(row["total_signals"]),
            "engagement_rate": float(row["engagement_rate"]),
        }
        coll.update_one({"uid": uid}, {"$set": doc}, upsert=True)

        predictions.append({
            "uid": uid,
            "churn_probability": pred["churn_probability"],
            "churn_risk_tier": pred["churn_risk_tier"],
            "top_risk_factor": pred["top_risk_factor"],
            "engagement_rate": float(row["engagement_rate"]),
            "total_signals": int(row["total_signals"]),
            "features": features_dict,
            "scored_at": scored_at.isoformat(),
            "written_back": True,
        })
        logger.info(
            "Scored uid=%s prob=%.3f tier=%s top=%s via Fabric (written back)",
            uid, pred["churn_probability"], pred["churn_risk_tier"], pred["top_risk_factor"],
        )

    return {"predictions": predictions}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
