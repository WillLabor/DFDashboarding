"""Customer ML scoring: churn risk and upgrade potential.

Two Random Forest models trained on customer RFM features:
  - Churn Risk Score (0-100): probability a customer will become Lost/At-Risk
  - Upgrade Potential Score (0-100): probability a customer could reach Champions/Loyal tier

Also retains the original CLI classification runner at the bottom.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import cross_val_score, train_test_split

# Features used by both models
ML_FEATURES = [
    "totalOrders",
    "totalSales",
    "days_since_last_order",
    "customer_age_days",
    "avg_order_value",
    "orders_per_month",
    "recency_age_ratio",
]

FEATURE_LABELS = {
    "totalOrders":          "Total Orders",
    "totalSales":           "Lifetime Sales ($)",
    "days_since_last_order":"Days Since Last Order",
    "customer_age_days":    "Customer Age (days)",
    "avg_order_value":      "Avg Order Value ($)",
    "orders_per_month":     "Orders / Month",
    "recency_age_ratio":    "Recency / Age Ratio",
}


def build_customer_features(seg_df: pd.DataFrame) -> pd.DataFrame:
    """Add derived RFM features needed for ML scoring."""
    df = seg_df.copy()

    for col in ("totalOrders", "totalSales", "days_since_last_order", "customer_age_days"):
        df[col] = pd.to_numeric(df.get(col, 0), errors="coerce").fillna(0)

    df["days_since_last_order"] = df["days_since_last_order"].replace(0, 999)
    df["avg_order_value"]   = df["totalSales"] / df["totalOrders"].clip(lower=1)
    df["orders_per_month"]  = df["totalOrders"] / (df["customer_age_days"] / 30).clip(lower=1)
    df["recency_age_ratio"] = df["days_since_last_order"] / df["customer_age_days"].clip(lower=1)

    return df


def run_customer_ml(seg_df: pd.DataFrame) -> dict:
    """Train churn-risk and upgrade-potential models, then score every customer.

    Returns a dict with:
      scored_df            – original seg_df + churn_risk_score + upgrade_potential_score (0-100)
      churn_importances    – pd.Series of feature importances (churn model)
      upgrade_importances  – pd.Series of feature importances (upgrade model)
      churn_auc            – cross-validated ROC-AUC for churn model (float)
      upgrade_auc          – cross-validated ROC-AUC for upgrade model (float)
    """
    df = build_customer_features(seg_df)
    X_all = df[ML_FEATURES].fillna(0)
    results: dict = {}

    # ── Model 1: Churn Risk ─────────────────────────────────────────────────
    # Train on customers with a clear outcome: Lost/At-Risk=1 vs Champions/Loyal/Regular=0
    churn_mask = df["segment"].isin(["Champions", "Loyal", "Regular", "Lost", "At-Risk"])
    df_c = df[churn_mask]
    y_c  = df_c["segment"].isin(["Lost", "At-Risk"]).astype(int)

    churn_model = None
    if y_c.sum() >= 10 and (len(y_c) - y_c.sum()) >= 10:
        churn_model = RandomForestClassifier(
            n_estimators=300, class_weight="balanced", random_state=42, n_jobs=-1
        )
        churn_model.fit(df_c[ML_FEATURES].fillna(0), y_c)
        cv_folds = min(5, int(y_c.value_counts().min()))
        cv = cross_val_score(churn_model, df_c[ML_FEATURES].fillna(0), y_c,
                             cv=cv_folds, scoring="roc_auc")
        results["churn_auc"] = float(np.mean(cv))
        results["churn_importances"] = (
            pd.Series(churn_model.feature_importances_, index=ML_FEATURES)
            .rename(index=FEATURE_LABELS)
            .sort_values(ascending=True)   # ascending=True for horizontal bar readability
        )

    # ── Model 2: Upgrade Potential ──────────────────────────────────────────
    # Train on mid-tier customers: Champions/Loyal=1 vs Regular/Occasional=0
    upgrade_mask = df["segment"].isin(["Champions", "Loyal", "Regular", "Occasional"])
    df_u = df[upgrade_mask]
    y_u  = df_u["segment"].isin(["Champions", "Loyal"]).astype(int)

    upgrade_model = None
    if y_u.sum() >= 10 and (len(y_u) - y_u.sum()) >= 10:
        upgrade_model = RandomForestClassifier(
            n_estimators=300, class_weight="balanced", random_state=42, n_jobs=-1
        )
        upgrade_model.fit(df_u[ML_FEATURES].fillna(0), y_u)
        cv_folds = min(5, int(y_u.value_counts().min()))
        cv = cross_val_score(upgrade_model, df_u[ML_FEATURES].fillna(0), y_u,
                             cv=cv_folds, scoring="roc_auc")
        results["upgrade_auc"] = float(np.mean(cv))
        results["upgrade_importances"] = (
            pd.Series(upgrade_model.feature_importances_, index=ML_FEATURES)
            .rename(index=FEATURE_LABELS)
            .sort_values(ascending=True)
        )

    # ── Score all customers ─────────────────────────────────────────────────
    scored = df.copy()
    if churn_model is not None:
        scored["churn_risk_score"] = (
            churn_model.predict_proba(X_all)[:, 1] * 100
        ).round(1)
    else:
        scored["churn_risk_score"] = float("nan")

    if upgrade_model is not None:
        scored["upgrade_potential_score"] = (
            upgrade_model.predict_proba(X_all)[:, 1] * 100
        ).round(1)
    else:
        scored["upgrade_potential_score"] = float("nan")

    results["scored_df"] = scored
    return results


# ---------------------------------------------------------------------------
# Original CLI classification runner (kept for backward compatibility)
# ---------------------------------------------------------------------------

def run_classification(
    input_csv: str,
    target_column: str,
    features: list[str] | None = None,
    test_size: float = 0.2,
    random_state: int = 42,
) -> None:
    df = pd.read_csv(input_csv)
    if features is None:
        features = [c for c in df.columns if c != target_column]
    X = df[features]
    y = df[target_column]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state,
        stratify=y if len(set(y)) > 1 else None,
    )
    model = RandomForestClassifier(random_state=random_state, n_jobs=-1)
    model.fit(X_train, y_train)
    print("=== classification report ===")
    print(classification_report(y_test, model.predict(X_test)))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run a quick ML experiment")
    parser.add_argument("--input-csv", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--features", nargs="*", default=None)
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--random-state", type=int, default=42)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    run_classification(args.input_csv, args.target, args.features,
                       args.test_size, args.random_state)


if __name__ == "__main__":
    main()
