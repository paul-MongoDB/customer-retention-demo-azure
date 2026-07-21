# Fabric Notebook: Train Churn Model
# -----------------------------------
# Run this ONCE during demo setup after baseline data has been mirrored.
# Trains a Random Forest churn model, saves it to Lakehouse Files,
# and writes initial churn_predictions table.
#
# Copy each cell block into a separate Fabric notebook cell.

# ===== Cell 1: Load mirrored data =====

df_signals = spark.sql("SELECT * FROM RetentionAnalytics.dbo.session_signals")
df_nba = spark.sql("SELECT * FROM RetentionAnalytics.dbo.next_best_actions")

print(f"Session Signals: {df_signals.count()} rows")
print(f"Next Best Actions: {df_nba.count()} rows")

# ===== Cell 2: Signal and NBA distribution =====

df_signals.groupBy("signal").count().orderBy("count", ascending=False).show()
df_signals.groupBy("signal", "severity").count().orderBy("signal", "count", ascending=False).show()
df_nba.groupBy("type").count().orderBy("count", ascending=False).show()
df_nba.groupBy("type", "redeemed").count().orderBy("type", "redeemed").show()

# ===== Cell 3: Feature engineering =====

from pyspark.sql import functions as F

user_signals = df_signals.groupBy("uid").agg(
    F.count("*").alias("total_signals"),
    F.sum(F.when(F.col("signal") == "exit-risk", 1).otherwise(0)).alias("exit_risk_count"),
    F.sum(F.when(F.col("signal") == "search-friction", 1).otherwise(0)).alias("search_friction_count"),
    F.sum(F.when(F.col("signal") == "high-intent", 1).otherwise(0)).alias("high_intent_count"),
    F.countDistinct("sid").alias("session_count"),
)

user_nba = df_nba.groupBy("uid").agg(
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

print(f"Users with features: {user_features.count()}")
user_features.show(10, truncate=False)

# ===== Cell 4: Train model =====

import pandas as pd
import numpy as np
import pickle
import json
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_score

pdf = user_features.toPandas()

# Churn label: high exit risk + low engagement
pdf["churned"] = ((pdf["exit_risk_ratio"] > 0.4) & (pdf["engagement_rate"] < 0.3)).astype(int)

print(f"Total users: {len(pdf)}")
print(f"Churned: {pdf['churned'].sum()}")
print(f"Retained: {(pdf['churned'] == 0).sum()}")

feature_cols = [
    "total_signals", "exit_risk_count", "search_friction_count",
    "high_intent_count", "session_count", "total_nbas",
    "redeemed_count", "exit_risk_ratio", "engagement_rate",
    "signals_per_session"
]

X = pdf[feature_cols].fillna(0)
y = pdf["churned"]

model = RandomForestClassifier(n_estimators=50, max_depth=3, random_state=42)

if len(pdf) >= 5:
    scores = cross_val_score(model, X, y, cv=min(5, len(pdf)), scoring="accuracy")
    print(f"\nCross-validation accuracy: {scores.mean():.2f} (+/- {scores.std():.2f})")

model.fit(X, y)

importance = pd.DataFrame({
    "feature": feature_cols,
    "importance": model.feature_importances_
}).sort_values("importance", ascending=False)

print("\nFeature Importance:")
print(importance.to_string(index=False))

# ===== Cell 5: Save model to Lakehouse Files =====

import os

model_dir = "/lakehouse/default/Files/models"
os.makedirs(model_dir, exist_ok=True)

model_path = f"{model_dir}/churn_model.pkl"
with open(model_path, "wb") as f:
    pickle.dump(model, f)
print(f"Model saved to {model_path}")

cols_path = f"{model_dir}/feature_columns.json"
with open(cols_path, "w") as f:
    json.dump(feature_cols, f)
print(f"Feature columns saved to {cols_path}")

# ===== Cell 5b: Register the model so Fabric can serve it in real time =====
# Registers an MLflow model whose endpoint returns the full churn intelligence
# (probability + tier + top risk factor). The retention agent calls this Fabric
# endpoint in real time for customers who have no batch score yet, so Fabric does
# BOTH batch scoring (Cell 6 / score_new_users) and real-time scoring.

import mlflow
import mlflow.pyfunc
from mlflow.models import infer_signature

REGISTERED_MODEL_NAME = "leafy-churn-scorer"
TIER_BINS = [-0.01, 0.3, 0.6, 1.01]
TIER_LABELS = ["Low", "Medium", "High"]


class ChurnScorer(mlflow.pyfunc.PythonModel):
    """Wraps the RandomForest and returns churn_probability, churn_risk_tier, and
    top_risk_factor per row -- the same outputs the batch scoring notebook
    produces, so real-time and batch scores match."""

    def load_context(self, context):
        with open(context.artifacts["model"], "rb") as f:
            self.model = pickle.load(f)
        with open(context.artifacts["feature_columns"], "r") as f:
            self.feature_cols = json.load(f)

    def predict(self, context, model_input):
        feats = model_input[self.feature_cols].astype(float).fillna(0)
        proba = self.model.predict_proba(feats)
        prob = proba[:, 1] if proba.shape[1] > 1 else np.full(len(feats), float(self.model.classes_[0] == 1))
        tier = pd.cut(prob, bins=TIER_BINS, labels=TIER_LABELS).astype(str)
        importances = self.model.feature_importances_
        top = []
        for _, r in feats.iterrows():
            contrib = {c: r[c] * imp for c, imp in zip(self.feature_cols, importances)}
            top.append(max(contrib, key=contrib.get))
        return pd.DataFrame({
            "churn_probability": prob.astype(float),
            "churn_risk_tier": tier,
            "top_risk_factor": top,
        })


# Signature: 10 named float features in -> 3 outputs. A schema is required for
# Fabric endpoints (models with no schema are not eligible).
sig_input = X[feature_cols].astype(float).head(2)
sig_output = pd.DataFrame({
    "churn_probability": [0.0, 0.0],
    "churn_risk_tier": ["Low", "Low"],
    "top_risk_factor": [feature_cols[0], feature_cols[0]],
})
signature = infer_signature(sig_input, sig_output)

with mlflow.start_run():
    mlflow.pyfunc.log_model(
        artifact_path="churn_scorer",
        python_model=ChurnScorer(),
        artifacts={"model": model_path, "feature_columns": cols_path},
        signature=signature,
        registered_model_name=REGISTERED_MODEL_NAME,
    )

print(f"Registered MLflow model '{REGISTERED_MODEL_NAME}'.")
print("Next steps in Fabric:")
print("  1. Open the model, select the latest version, and 'Activate version endpoint'.")
print("  2. Turn auto-sleep Off (or warm it before a demo) to avoid the idle cold start.")
print("  3. Copy the workspace ID and model ID into the scoring gateway")
print("     (FABRIC_WORKSPACE_ID / FABRIC_MODEL_ID).")
print("Note: if your tenant's endpoints don't accept a custom pyfunc, log the")
print("sklearn model instead (mlflow.sklearn) and derive tier/top_risk_factor in")
print("the gateway -- see the scoring gateway README.")

# ===== Cell 6: Generate predictions and save to Lakehouse =====

pdf["churn_probability"] = model.predict_proba(X)[:, 1] if len(np.unique(y)) > 1 else 0.5

# Fixed bin edges to avoid nan for values at exact boundaries
pdf["churn_risk_tier"] = pd.cut(
    pdf["churn_probability"],
    bins=[-0.01, 0.3, 0.6, 1.01],
    labels=["Low", "Medium", "High"]
)

# Identify top risk factor per user
for idx, row in pdf.iterrows():
    feature_contributions = {col: row[col] * imp for col, imp in zip(feature_cols, model.feature_importances_)}
    pdf.at[idx, "top_risk_factor"] = max(feature_contributions, key=feature_contributions.get)

output_cols = [
    "uid", "total_signals", "exit_risk_count", "search_friction_count",
    "high_intent_count", "session_count", "total_nbas", "redeemed_count",
    "engagement_rate", "exit_risk_ratio", "churn_probability", "churn_risk_tier",
    "top_risk_factor"
]

predictions_pdf = pdf[output_cols].copy()
predictions_pdf["churn_risk_tier"] = predictions_pdf["churn_risk_tier"].astype(str)

print("Churn Predictions:")
print(predictions_pdf[["uid", "churn_probability", "churn_risk_tier", "top_risk_factor"]].to_string(index=False))

spark_predictions = spark.createDataFrame(predictions_pdf)
spark_predictions.write.format("delta").mode("overwrite").saveAsTable("churn_predictions")

print(f"\nSaved {len(predictions_pdf)} predictions to churn_predictions table!")

# ===== Cell 7: Summary stats =====

print("=" * 50)
print("TRAINING SUMMARY")
print("=" * 50)
print(f"Users analyzed: {len(pdf)}")
print(f"Behavioral signals processed: {df_signals.count()}")
print(f"Retention actions generated: {df_nba.count()}")
print(f"High risk users: {(pdf['churn_risk_tier'] == 'High').sum()}")
print(f"Medium risk users: {(pdf['churn_risk_tier'] == 'Medium').sum()}")
print(f"Low risk users: {(pdf['churn_risk_tier'] == 'Low').sum()}")
print(f"Average engagement rate: {pdf['engagement_rate'].mean():.1%}")
print(f"Model saved to: {model_path}")
print("=" * 50)
