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


def save_aggregation(df: pd.DataFrame, out_path: str) -> None:
    """Save aggregated DataFrame to CSV."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
