"""Helpers to aggregate and summarize order data."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

import pandas as pd


def load_orders(path: str) -> pd.DataFrame:
    """Load an orders CSV into a DataFrame."""
    return pd.read_csv(path)


def summarize_orders(df: pd.DataFrame) -> pd.DataFrame:
    """Return high-level summary metrics for orders."""
    summary = {
        "num_orders": len(df),
        "total_revenue": df.get("orderTotal", pd.Series(dtype=float)).sum(),
        "total_items": df.get("qty", pd.Series(dtype=float)).sum(),
        "unique_customers": df.get("customerId", pd.Series(dtype="Int64")).nunique(dropna=True),
    }
    return pd.DataFrame([summary])


def aggregate_orders(
    df: pd.DataFrame,
    group_by: Iterable[str],
    metrics: Optional[dict[str, str]] = None,
) -> pd.DataFrame:
    """Aggregate orders with group-by and aggregation metrics.

    Example:
        aggregate_orders(df, ["customerId"], {"orderTotal": "sum", "qty": "sum"})
    """

    if metrics is None:
        metrics = {"orderTotal": "sum", "qty": "sum"}

    grouped = df.groupby(list(group_by)).agg(metrics)
    # Flatten MultiIndex columns if present
    grouped.columns = ["_".join(col).strip() if isinstance(col, tuple) else col for col in grouped.columns]
    return grouped.reset_index()


def extract_orders_at_order_level(df: pd.DataFrame, status_filter: str | None = None) -> pd.DataFrame:
    """Return one row per order (orderId) with subtotal/total and classification.

    The API returns one row per order item; only one of the rows in each order
    contains the order-level `orderSubTotal`/`orderTotal` values. This function
    collapses rows to a single order record using first non-null values.

    If status_filter is provided, only include orders with that orderStatus.
    """
    # Filter by status if specified
    if status_filter:
        df = df[df["orderStatus"] == status_filter]

    # keep the fields we want for order-level aggregation
    keep_cols = [
        "orderId",
        "periodStart",
        "customerType",
        "orderSubTotal",
        "orderTotal",
        "orderStatus",
    ]

    # Add customer fields if they exist in the actual API response
    customer_fields = ["email", "customerId", "customerName", "locationName"]
    for field in customer_fields:
        if field in df.columns:
            keep_cols.append(field)

    # keep only orders where we have an orderId
    df = df.loc[df["orderId"].notna(), keep_cols]

    # take first non-null value per order (the rows with subtotals/totals will remain)
    agg_dict = {
        "periodStart": "first",
        "customerType": "first",
        "orderSubTotal": "first",
        "orderTotal": "first",
        "orderStatus": "first",
    }
    for field in customer_fields:
        if field in keep_cols:
            agg_dict[field] = "first"

    order_level = (
        df.sort_values("orderId")
        .groupby("orderId", as_index=False)
        .agg(agg_dict)
    )

    return order_level


def average_order_value_by_type_period(df: pd.DataFrame, status_filter: str | None = None) -> pd.DataFrame:
    """Compute average order/subtotal value by (periodStart, customerType)."""

    order_level = extract_orders_at_order_level(df, status_filter=status_filter)
    order_level["periodStart"] = pd.to_datetime(order_level["periodStart"], errors="coerce")

    agg = (
        order_level
        .groupby(["periodStart", "customerType"], dropna=False)
        .agg(
            orders=("orderId", "nunique"),
            avg_order_subtotal=("orderSubTotal", "mean"),
            avg_order_total=("orderTotal", "mean"),
            sum_order_subtotal=("orderSubTotal", "sum"),
            sum_order_total=("orderTotal", "sum"),
        )
        .reset_index()
    )

    return agg


# ---------------------------------------------------------------------------
# Customer segmentation
# ---------------------------------------------------------------------------

_SEGMENT_ACTIONS: dict[str, str] = {
    "Champions":     "🎁 Reward: loyalty programme, early product access, referral asks",
    "Loyal":         "⬆️  Upsell: premium bundles, subscription upgrade offer",
    "At-Risk":       "🚨 Win-back: personal call or email, limited-time discount",
    "Regular":       "📈 Nurture: increase frequency, recurring-order nudge",
    "New":           "👋 Onboard: welcome series, highlight popular products",
    "Lost":          "💌 Re-engage: 'We miss you' promo, satisfaction survey",
    "Occasional":    "🛒 Reactivate: seasonal promotions, low-barrier offer",
    "Never Ordered": "📣 Activate: first-order incentive, demo / intro call",
}


def segment_customers(customers_df: pd.DataFrame) -> pd.DataFrame:
    """Classify customers into lifecycle segments using RFM-like logic.

    Segments (evaluated in priority order):
      Never Ordered – No lastOrder on record
      New           – First order ≤ 90 days ago AND ≤ 2 total orders
      Lost          – Last order > 270 days ago
      Champions     – Recent + highly frequent + high-spend (all top-third)
      Loyal         – Frequent + high-spend (regardless of slight recency lag)
      At-Risk       – High value/frequency but last order > 90 days ago
      Regular       – Ordered within 90 days with some purchase history
      Occasional    – Has orders but doesn't fit higher tiers

    Adds computed columns: days_since_last_order, customer_age_days, segment.
    """
    df = customers_df.copy()
    today = pd.Timestamp.now()

    for col in ("lastOrder", "firstOrder", "dateEntered"):
        if col in df.columns:
            parsed = pd.to_datetime(df[col], errors="coerce")
            if parsed.dt.tz is not None:
                parsed = parsed.dt.tz_convert("UTC").dt.tz_localize(None)
            df[col] = parsed

    df["totalOrders"] = pd.to_numeric(df.get("totalOrders", pd.Series(0, index=df.index)), errors="coerce").fillna(0)
    df["totalSales"]  = pd.to_numeric(df.get("totalSales",  pd.Series(0, index=df.index)), errors="coerce").fillna(0)

    if "lastOrder" in df.columns:
        df["days_since_last_order"] = (today - df["lastOrder"]).dt.days
        df["days_since_last_order"] = df["days_since_last_order"].where(df["lastOrder"].notna())
    else:
        df["days_since_last_order"] = pd.NA

    if "firstOrder" in df.columns:
        df["customer_age_days"] = (today - df["firstOrder"]).dt.days
        df["customer_age_days"] = df["customer_age_days"].where(df["firstOrder"].notna())
    else:
        df["customer_age_days"] = pd.NA

    # Percentile thresholds — computed only from customers who have ordered
    active = df[(df["totalOrders"] > 0) & df["days_since_last_order"].notna()]
    if len(active) < 5:
        df["segment"] = "Insufficient Data"
        return df

    r_p33 = float(active["days_since_last_order"].quantile(0.33))
    f_p66 = float(active["totalOrders"].quantile(0.66))
    m_p66 = float(active["totalSales"].quantile(0.66))

    def _classify(row) -> str:
        if pd.isna(row.get("lastOrder")) or pd.isna(row.get("days_since_last_order")):
            return "Never Ordered"

        r   = float(row["days_since_last_order"])
        f   = float(row["totalOrders"])
        m   = float(row["totalSales"])
        age = row.get("customer_age_days")

        if pd.notna(age) and float(age) <= 90 and f <= 2:
            return "New"
        if r > 270:
            return "Lost"
        if r <= r_p33 and f >= f_p66 and m >= m_p66:
            return "Champions"
        if f >= f_p66 and m >= m_p66 and r <= 180:
            return "Loyal"
        if (m >= m_p66 or f >= f_p66) and r > 90:
            return "At-Risk"
        if r <= 90 and f >= 1:
            return "Regular"
        return "Occasional"

    df["segment"] = df.apply(_classify, axis=1)
    return df


def save_aggregation(df: pd.DataFrame, out_path: str) -> None:
    """Save aggregated DataFrame to CSV."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
