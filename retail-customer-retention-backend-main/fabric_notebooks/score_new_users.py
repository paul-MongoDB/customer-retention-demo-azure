# Fabric Notebook: Score New Users
# ----------------------------------
# Run this MANUALLY during the demo after burst data has been mirrored.
# Loads the pre-trained model, scores only new (unscored) users,
# writes to churn_predictions table AND back to MongoDB Atlas.
#
# Copy each cell block into a separate Fabric notebook cell.

# ===== Cell 1: Parameters (mark as "Toggle parameter cell" in Fabric) =====

MONGODB_URI = "<YOUR_MONGODB_URI>"  # Replace with your Atlas connection string
DB_NAME = "leafy_popup_store"
COLLECTION_NAME = "churn_risk_scores"

# ===== Cell 2: Install pymongo (first run only) =====

%pip install pymongo

# ===== Cell 3: Load saved model =====

import pickle
import json

model_path = "/lakehouse/default/Files/models/churn_model.pkl"
cols_path = "/lakehouse/default/Files/models/feature_columns.json"

with open(model_path, "rb") as f:
    model = pickle.load(f)
print("Model loaded successfully")

with open(cols_path, "r") as f:
    feature_cols = json.load(f)
print(f"Feature columns: {feature_cols}")

# ===== Cell 4: Load data and find new users =====

from pyspark.sql import functions as F
import pandas as pd
import numpy as np

# Load mirrored data
df_signals = spark.sql("SELECT * FROM RetentionAnalytics.dbo.session_signals")
df_nba = spark.sql("SELECT * FROM RetentionAnalytics.dbo.next_best_actions")

# Load existing predictions
try:
    df_existing = spark.sql("SELECT uid FROM churn_predictions")
    existing_uids = set(row.uid for row in df_existing.collect())
    print(f"Already scored users: {len(existing_uids)}")
except:
    existing_uids = set()
    print("No existing predictions found, scoring all users")

# Get all unique user IDs from signals
all_uids = set(row.uid for row in df_signals.select("uid").distinct().collect())
new_uids = all_uids - existing_uids
print(f"Total users in signals: {len(all_uids)}")
print(f"New users to score: {len(new_uids)}")

if len(new_uids) == 0:
    print("No new users to score. Done!")
    # Stop execution here in Fabric by not running subsequent cells

# ===== Cell 5: Feature engineering for new users =====

# Filter to only new users
df_new_signals = df_signals.filter(F.col("uid").isin(list(new_uids)))
df_new_nba = df_nba.filter(F.col("uid").isin(list(new_uids)))

user_signals = df_new_signals.groupBy("uid").agg(
    F.count("*").alias("total_signals"),
    F.sum(F.when(F.col("signal") == "exit-risk", 1).otherwise(0)).alias("exit_risk_count"),
    F.sum(F.when(F.col("signal") == "search-friction", 1).otherwise(0)).alias("search_friction_count"),
    F.sum(F.when(F.col("signal") == "high-intent", 1).otherwise(0)).alias("high_intent_count"),
    F.countDistinct("sid").alias("session_count"),
)

user_nba = df_new_nba.groupBy("uid").agg(
    F.count("*").alias("total_nbas"),
    F.sum(F.when(F.col("redeemed") == True, 1).otherwise(0)).alias("redeemed_count"),
)

user_features = user_signals.join(user_nba, on="uid", how="left").fillna(0)

user_features = user_features.withColumn(
    "exit_risk_ratio", F.col("exit_risk_count") / F.col("total_signals")
).withColumn(
    "engagement_rate",
    F.when(F.col("total_nbas") > 0, F.col("redeemed_count") / F.col("total_nbas")).otherwise(0.0)
).withColumn(
    "signals_per_session", F.col("total_signals") / F.col("session_count")
)

pdf = user_features.toPandas()
print(f"Prepared features for {len(pdf)} new users")

# ===== Cell 6: Score new users =====

X = pdf[feature_cols].fillna(0)

pdf["churn_probability"] = model.predict_proba(X)[:, 1] if hasattr(model, "predict_proba") else 0.5

pdf["churn_risk_tier"] = pd.cut(
    pdf["churn_probability"],
    bins=[-0.01, 0.3, 0.6, 1.01],
    labels=["Low", "Medium", "High"]
)

# Identify top risk factor per user
for idx, row in pdf.iterrows():
    feature_contributions = {col: row[col] * imp for col, imp in zip(feature_cols, model.feature_importances_)}
    pdf.at[idx, "top_risk_factor"] = max(feature_contributions, key=feature_contributions.get)

print("Scoring complete!")
print(pdf[["uid", "churn_probability", "churn_risk_tier", "top_risk_factor"]].to_string(index=False))

# ===== Cell 7: Append to churn_predictions table =====

output_cols = [
    "uid", "total_signals", "exit_risk_count", "search_friction_count",
    "high_intent_count", "session_count", "total_nbas", "redeemed_count",
    "engagement_rate", "exit_risk_ratio", "churn_probability", "churn_risk_tier",
    "top_risk_factor"
]

predictions_pdf = pdf[output_cols].copy()
predictions_pdf["churn_risk_tier"] = predictions_pdf["churn_risk_tier"].astype(str)

spark_predictions = spark.createDataFrame(predictions_pdf)
spark_predictions.write.format("delta").mode("append").saveAsTable("churn_predictions")

print(f"Appended {len(predictions_pdf)} predictions to churn_predictions table")

# ===== Cell 8: Write predictions back to MongoDB Atlas =====

from pymongo import MongoClient
from datetime import datetime

# Uses MONGODB_URI, DB_NAME, and COLLECTION_NAME from the parameters cell
client = MongoClient(MONGODB_URI, tls=True, tlsAllowInvalidCertificates=True)
db = client[DB_NAME]
collection = db[COLLECTION_NAME]

scored_at = datetime.utcnow()
write_count = 0

for _, row in predictions_pdf.iterrows():
    doc = {
        "uid": row["uid"],
        "churn_probability": float(row["churn_probability"]),
        "churn_risk_tier": row["churn_risk_tier"],
        "scored_at": scored_at,
        "top_risk_factor": row["top_risk_factor"],
        "total_signals": int(row["total_signals"]),
        "engagement_rate": float(row["engagement_rate"]),
    }
    collection.update_one(
        {"uid": row["uid"]},
        {"$set": doc},
        upsert=True
    )
    write_count += 1

client.close()
print(f"Wrote {write_count} predictions back to MongoDB Atlas ({DB_NAME}.{COLLECTION_NAME})")
print("Predictions are now available in the Leafy store UI via Change Streams!")

# ===== Cell 9: Summary =====

print("=" * 50)
print("SCORING SUMMARY")
print("=" * 50)
print(f"New users scored: {len(pdf)}")
print(f"High risk: {(pdf['churn_risk_tier'] == 'High').sum()}")
print(f"Medium risk: {(pdf['churn_risk_tier'] == 'Medium').sum()}")
print(f"Low risk: {(pdf['churn_risk_tier'] == 'Low').sum()}")
print(f"Predictions written to Lakehouse: churn_predictions (append)")
print(f"Predictions written to Atlas: {DB_NAME}.{COLLECTION_NAME} (upsert)")
print("=" * 50)
