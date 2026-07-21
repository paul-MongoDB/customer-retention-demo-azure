"""
Shared churn feature engineering.

A faithful re-implementation of the Fabric notebooks (train_churn_model.py and
score_new_users.py, which live in the backend repo under fabric_notebooks/)
using pymongo aggregations instead of Spark. The scoring service (main.py)
imports this module so it computes identical features and produces scores that
match what Fabric produces. Keep this in lockstep with the notebooks: same
feature set, same derived-column guards, same tier bins.
"""
import pandas as pd

# Order matters: it must match feature_columns.json written by the trainer and
# by the Fabric notebook.
FEATURE_COLUMNS = [
    "total_signals", "exit_risk_count", "search_friction_count",
    "high_intent_count", "session_count", "total_nbas",
    "redeemed_count", "exit_risk_ratio", "engagement_rate",
    "signals_per_session",
]

# Identical to the Fabric notebooks. Fixed edges avoid NaN at exact boundaries.
TIER_BINS = [-0.01, 0.3, 0.6, 1.01]
TIER_LABELS = ["Low", "Medium", "High"]

_INT_FEATURES = [
    "total_signals", "exit_risk_count", "search_friction_count",
    "high_intent_count", "session_count", "total_nbas", "redeemed_count",
]


def _signal_pipeline(uids=None):
    pipeline = []
    if uids is not None:
        pipeline.append({"$match": {"uid": {"$in": list(uids)}}})
    pipeline += [
        {"$group": {
            "_id": "$uid",
            "total_signals": {"$sum": 1},
            "exit_risk_count": {"$sum": {"$cond": [{"$eq": ["$signal", "exit-risk"]}, 1, 0]}},
            "search_friction_count": {"$sum": {"$cond": [{"$eq": ["$signal", "search-friction"]}, 1, 0]}},
            "high_intent_count": {"$sum": {"$cond": [{"$eq": ["$signal", "high-intent"]}, 1, 0]}},
            "sessions": {"$addToSet": "$sid"},
        }},
        {"$project": {
            "total_signals": 1,
            "exit_risk_count": 1,
            "search_friction_count": 1,
            "high_intent_count": 1,
            "session_count": {"$size": "$sessions"},
        }},
    ]
    return pipeline


def _nba_pipeline(uids=None):
    pipeline = []
    if uids is not None:
        pipeline.append({"$match": {"uid": {"$in": list(uids)}}})
    pipeline += [
        {"$group": {
            "_id": "$uid",
            "total_nbas": {"$sum": 1},
            "redeemed_count": {"$sum": {"$cond": [{"$eq": ["$redeemed", True]}, 1, 0]}},
        }},
    ]
    return pipeline


def compute_features(db, uids=None):
    """Return a DataFrame of uid + the 10 feature columns.

    Mirrors the notebook's groupBy on session_signals, left-join with
    next_best_actions, fillna(0), and derived columns. Driven by users present
    in session_signals (a user with no signals yields no row).
    """
    signals = list(db["session_signals"].aggregate(_signal_pipeline(uids)))
    if not signals:
        return pd.DataFrame(columns=["uid"] + FEATURE_COLUMNS)

    sig_df = pd.DataFrame(signals).rename(columns={"_id": "uid"})

    nba = list(db["next_best_actions"].aggregate(_nba_pipeline(uids)))
    nba_df = (
        pd.DataFrame(nba).rename(columns={"_id": "uid"})
        if nba else pd.DataFrame(columns=["uid", "total_nbas", "redeemed_count"])
    )

    df = sig_df.merge(nba_df, on="uid", how="left")

    # Users with no NBAs (left-join nulls) -> 0, matching the notebook's fillna(0).
    for col in ("total_nbas", "redeemed_count"):
        if col not in df.columns:
            df[col] = 0
    df[["total_nbas", "redeemed_count"]] = df[["total_nbas", "redeemed_count"]].fillna(0)

    # Derived features with the same guards as the notebook.
    df["exit_risk_ratio"] = df["exit_risk_count"] / df["total_signals"]
    df["engagement_rate"] = df.apply(
        lambda r: (r["redeemed_count"] / r["total_nbas"]) if r["total_nbas"] > 0 else 0.0,
        axis=1,
    )
    df["signals_per_session"] = df["total_signals"] / df["session_count"]

    df[_INT_FEATURES] = df[_INT_FEATURES].fillna(0).astype(int)

    return df[["uid"] + FEATURE_COLUMNS]


def tier_for(probabilities):
    """Map a Series of churn probabilities to tier labels (Fabric-identical bins)."""
    return pd.cut(probabilities, bins=TIER_BINS, labels=TIER_LABELS)


def top_risk_factor(row, feature_importances):
    """The feature with the largest value-times-importance contribution, identical
    to the notebook's per-user top_risk_factor logic. `row` is a Series keyed by
    feature name."""
    contributions = {
        col: row[col] * imp for col, imp in zip(FEATURE_COLUMNS, feature_importances)
    }
    return max(contributions, key=contributions.get)
