"""Helpers to aggregate and summarize order data."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Iterable, Optional, Sequence

import numpy as np
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


def calculate_clv(seg_df: pd.DataFrame, projection_months: int = 12) -> pd.DataFrame:
    """Add Customer Lifetime Value columns to a segmented customer DataFrame.

    Uses the BG/NBD-lite formula: Projected CLV = AOV × purchase_rate × projection_months.
    All inputs come from the existing customer API fields (totalOrders, totalSales,
    firstOrder, lastOrder) plus the computed columns from segment_customers().

    Added columns
    -------------
    historical_clv      Actual spend to date (= totalSales)
    avg_order_value     Average spend per order
    orders_per_month    Monthly purchase frequency over the customer's lifetime
    projected_clv       Forward-looking CLV for ``projection_months`` months
    clv_tier            "High" / "Medium" / "Low" / "No Orders" (tercile among active customers)
    """
    df = seg_df.copy()

    df["historical_clv"] = pd.to_numeric(df.get("totalSales", 0), errors="coerce").fillna(0).clip(lower=0)
    orders = pd.to_numeric(df.get("totalOrders", 0), errors="coerce").fillna(0)

    df["avg_order_value"] = np.where(orders > 0, df["historical_clv"] / orders, 0.0)

    age_months = pd.to_numeric(df.get("customer_age_days", np.nan), errors="coerce").fillna(0) / 30.44
    df["orders_per_month"] = np.where(age_months > 0.5, orders / age_months, 0.0)

    df["projected_clv"] = (df["avg_order_value"] * df["orders_per_month"] * projection_months).clip(lower=0)

    active_mask = orders > 0
    if active_mask.sum() >= 3:
        p33 = float(df.loc[active_mask, "projected_clv"].quantile(0.33))
        p66 = float(df.loc[active_mask, "projected_clv"].quantile(0.66))
    else:
        p33, p66 = 0.0, 0.0

    df["clv_tier"] = np.select(
        [
            ~active_mask,
            df["projected_clv"] >= p66,
            df["projected_clv"] >= p33,
        ],
        ["No Orders", "High", "Medium"],
        default="Low",
    )

    return df


_YOGURT_FLAVOR_PATTERNS: list[tuple[str, str]] = [
    ("blueberry lemon", "Blueberry Lemon"),
    ("meadow berry", "Meadowberry"),
    ("meadowberry", "Meadowberry"),
    ("passion fruit", "Passion Fruit"),
    ("savannah peach", "Savannah Peach"),
    ("strawberry", "Strawberry"),
    ("vanilla bean", "Vanilla Bean"),
    ("wilder raspberry", "Raspberry"),
    ("raspberry", "Raspberry"),
    ("plain", "Plain"),
]


def parse_painterland_unit(unit_name: object) -> dict[str, object]:
    """Normalize a Painterland selling unit into an orderable case SKU.

    Returns case-pack metadata so mixed sales of cases and split singles can be
    rolled up to the same SKU for ordering.
    """

    raw_label = "" if unit_name is None or pd.isna(unit_name) else str(unit_name).strip()
    normalized = re.sub(r"\s+", " ", raw_label).lower()

    flavor = "Unknown"
    for pattern, label in _YOGURT_FLAVOR_PATTERNS:
        if pattern in normalized:
            flavor = label
            break

    is_24oz = "24 oz" in normalized or "24oz" in normalized
    pack_size = 6 if is_24oz else 8
    size_label = "24oz" if is_24oz else "5.3oz"
    is_case_sale = "case" in normalized
    order_sku = f"{flavor} {size_label} case"

    return {
        "order_sku": order_sku,
        "flavor": flavor,
        "size_label": size_label,
        "pack_size": pack_size,
        "is_case_sale": is_case_sale,
        "normalized_unit_name": raw_label or order_sku,
    }


def _normalize_customer_label(value: object) -> str:
    raw = "" if value is None or pd.isna(value) else str(value)
    return re.sub(r"\s+", " ", raw).strip().lower()


def build_product_reorder_plan(
    df: pd.DataFrame,
    producer_name: str,
    product_keyword: str,
    lookback_cycles: int = 6,
    status_filter: str | None = "COMPLETE",
    growth_buffer_pct: float = 0.0,
    manual_uplift_units: float = 0.0,
    horizon_cycles: int = 3,
    inventory_by_sku: dict[str, float] | None = None,
) -> dict[str, object]:
    """Build a cycle-based reorder plan for a focused product family.

    The plan uses the loaded order-item history and treats each ``periodStart``
    value as one ordering cycle. Recommendations are based on the strongest of
    recent demand, trailing average demand, and short-term trend demand.
    """

    required_cols = {"periodStart", "qty", "producerName", "productName"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")

    work_df = df.copy()
    work_df["periodStart"] = pd.to_datetime(work_df["periodStart"], errors="coerce")
    work_df["qty"] = pd.to_numeric(work_df["qty"], errors="coerce").fillna(0)
    if "customerPriceExt" in work_df.columns:
        work_df["customerPriceExt"] = pd.to_numeric(work_df["customerPriceExt"], errors="coerce").fillna(0)
    else:
        work_df["customerPriceExt"] = 0.0

    producer_mask = work_df["producerName"].fillna("").str.contains(producer_name, case=False, regex=False)
    product_mask = (
        work_df["productName"].fillna("").str.contains(product_keyword, case=False, regex=False)
        | work_df.get("subCategory", pd.Series("", index=work_df.index)).fillna("").str.contains(product_keyword, case=False, regex=False)
    )
    status_mask = pd.Series(True, index=work_df.index)
    if status_filter and "orderStatus" in work_df.columns:
        status_mask = work_df["orderStatus"].fillna("").eq(status_filter)

    filtered = work_df[producer_mask & product_mask & status_mask].copy()
    filtered = filtered[filtered["periodStart"].notna()].copy()

    if filtered.empty:
        return {
            "filtered": filtered,
            "cycles": pd.DataFrame(),
            "sku_plan": pd.DataFrame(),
            "customer_summary": pd.DataFrame(),
            "cycle_count": 0,
        }

    filtered["customerName"] = filtered.get("customerName", pd.Series("Unknown", index=filtered.index)).fillna("Unknown")
    filtered["customerType"] = filtered.get("customerType", pd.Series("Unknown", index=filtered.index)).fillna("Unknown")
    filtered["locationName"] = filtered.get("locationName", pd.Series("", index=filtered.index)).fillna("")
    filtered["organization"] = filtered.get("organization", pd.Series("", index=filtered.index)).fillna("")
    filtered["unitName"] = filtered.get("unitName", pd.Series("", index=filtered.index)).fillna("")

    unit_info = filtered["unitName"].apply(parse_painterland_unit).apply(pd.Series)
    filtered = pd.concat([filtered, unit_info], axis=1)
    filtered["display_sku"] = filtered["order_sku"]
    filtered["sku_key"] = filtered["order_sku"]
    filtered["case_equiv_qty"] = np.where(
        filtered["is_case_sale"],
        filtered["qty"],
        filtered["qty"] / filtered["pack_size"],
    )
    filtered["case_sale_qty"] = np.where(filtered["is_case_sale"], filtered["qty"], 0.0)
    filtered["split_unit_qty"] = np.where(filtered["is_case_sale"], 0.0, filtered["qty"])

    available_cycles = sorted(filtered["periodStart"].dropna().unique())
    selected_cycles = available_cycles[-max(1, lookback_cycles):]
    scoped = filtered[filtered["periodStart"].isin(selected_cycles)].copy()

    cycle_summary = (
        scoped.groupby("periodStart", as_index=False)
        .agg(
            total_case_equiv=("case_equiv_qty", "sum"),
            total_cases_sold=("case_sale_qty", "sum"),
            total_split_units=("split_unit_qty", "sum"),
            active_customers=("customerName", "nunique"),
            revenue=("customerPriceExt", "sum"),
        )
        .sort_values("periodStart")
    )

    sku_pivot = (
        scoped.pivot_table(
            index="periodStart",
            columns="sku_key",
            values="case_equiv_qty",
            aggfunc="sum",
            fill_value=0,
        )
        .reindex(selected_cycles, fill_value=0)
        .sort_index()
    )

    sku_meta = (
        scoped.sort_values("periodStart")
        .groupby("sku_key", as_index=False)
        .agg(
            display_sku=("display_sku", "last"),
            productName=("productName", "last"),
            unitName=("unitName", "last"),
            producerName=("producerName", "last"),
            pack_size=("pack_size", "last"),
            size_label=("size_label", "last"),
            flavor=("flavor", "last"),
        )
    )

    sku_rows: list[dict[str, object]] = []
    baseline_total = 0.0
    inventory_by_sku = inventory_by_sku or {}
    cycle_spacing_days = 14
    if len(selected_cycles) >= 2:
        spacing = int((selected_cycles[-1] - selected_cycles[-2]).days)
        if spacing > 0:
            cycle_spacing_days = spacing

    for sku_key in sku_pivot.columns:
        series = sku_pivot[sku_key].astype(float)
        recent_qty = float(series.iloc[-1]) if len(series) else 0.0
        prior_qty = float(series.iloc[-2]) if len(series) > 1 else 0.0
        avg_cycle_qty = float(series.mean()) if len(series) else 0.0
        trend_cycle_qty = float(series.tail(min(3, len(series))).mean()) if len(series) else 0.0
        baseline_qty = max(recent_qty, avg_cycle_qty, trend_cycle_qty)
        baseline_total += baseline_qty

        latest_case_sales = float(
            scoped.loc[(scoped["sku_key"] == sku_key) & (scoped["periodStart"] == selected_cycles[-1]), "case_sale_qty"].sum()
        ) if selected_cycles else 0.0
        latest_split_units = float(
            scoped.loc[(scoped["sku_key"] == sku_key) & (scoped["periodStart"] == selected_cycles[-1]), "split_unit_qty"].sum()
        ) if selected_cycles else 0.0
        prior_case_sales = float(
            scoped.loc[(scoped["sku_key"] == sku_key) & (scoped["periodStart"] == selected_cycles[-2]), "case_sale_qty"].sum()
        ) if len(selected_cycles) > 1 else 0.0
        prior_split_units = float(
            scoped.loc[(scoped["sku_key"] == sku_key) & (scoped["periodStart"] == selected_cycles[-2]), "split_unit_qty"].sum()
        ) if len(selected_cycles) > 1 else 0.0

        sku_rows.append(
            {
                "sku_key": sku_key,
                "recent_case_equiv": recent_qty,
                "prior_case_equiv": prior_qty,
                "avg_cycle_cases": avg_cycle_qty,
                "trend_cycle_cases": trend_cycle_qty,
                "baseline_qty": baseline_qty,
                "active_cycles": int((series > 0).sum()),
                "latest_case_sales": latest_case_sales,
                "latest_split_units": latest_split_units,
                "prior_case_sales": prior_case_sales,
                "prior_split_units": prior_split_units,
            }
        )

    sku_plan = pd.DataFrame(sku_rows).merge(sku_meta, on="sku_key", how="left")
    if sku_plan.empty:
        sku_plan = pd.DataFrame(
            columns=[
                "display_sku", "recent_qty", "prior_qty", "avg_cycle_qty", "trend_cycle_qty",
                "baseline_qty", "manual_uplift_units", "recommended_qty", "active_cycles",
            ]
        )
    else:
        if baseline_total > 0:
            sku_plan["manual_uplift_units"] = manual_uplift_units * (sku_plan["baseline_qty"] / baseline_total)
        else:
            even_split = manual_uplift_units / len(sku_plan) if len(sku_plan) else 0.0
            sku_plan["manual_uplift_units"] = even_split

        sku_plan["inventory_available"] = sku_plan["display_sku"].map(lambda sku: float(inventory_by_sku.get(str(sku), 0.0)))
        sku_plan["recommended_qty"] = sku_plan.apply(
            lambda row: math.ceil(max(0.0, row["baseline_qty"] * (1 + growth_buffer_pct / 100.0) + row["manual_uplift_units"])),
            axis=1,
        )
        sku_plan["delta_vs_recent"] = sku_plan["recommended_qty"] - sku_plan["recent_case_equiv"]
        sku_plan = sku_plan.sort_values(["recommended_qty", "recent_case_equiv", "display_sku"], ascending=[False, False, True])

    forecast_rows: list[dict[str, object]] = []
    latest_cycle = selected_cycles[-1]
    future_cycle_starts = [latest_cycle + pd.Timedelta(days=cycle_spacing_days * step) for step in range(1, horizon_cycles + 1)]

    for _, row in sku_plan.iterrows():
        available_inventory = float(row.get("inventory_available", 0.0))
        cycle_projection = max(0.0, float(row.get("baseline_qty", 0.0)) * (1 + growth_buffer_pct / 100.0) + float(row.get("manual_uplift_units", 0.0)))
        step_change = max(0.0, float(row.get("recent_case_equiv", 0.0)) - float(row.get("prior_case_equiv", 0.0)))
        for bucket_idx, cycle_start in enumerate(future_cycle_starts, start=1):
            projected_demand = max(0.0, cycle_projection + (step_change * 0.35 * (bucket_idx - 1)))
            inventory_applied = min(available_inventory, projected_demand)
            order_needed = max(0.0, projected_demand - inventory_applied)
            available_inventory -= inventory_applied
            forecast_rows.append(
                {
                    "sku_key": row["sku_key"],
                    "display_sku": row["display_sku"],
                    "forecast_cycle_number": bucket_idx,
                    "forecast_cycle_start": cycle_start,
                    "projected_demand": projected_demand,
                    "inventory_applied": inventory_applied,
                    "ending_inventory": available_inventory,
                    "order_needed": math.ceil(order_needed),
                }
            )

    forecast_df = pd.DataFrame(forecast_rows)
    if not forecast_df.empty:
        forecast_summary = (
            forecast_df.groupby("forecast_cycle_start", as_index=False)
            .agg(
                projected_demand=("projected_demand", "sum"),
                inventory_applied=("inventory_applied", "sum"),
                order_needed=("order_needed", "sum"),
            )
            .sort_values("forecast_cycle_start")
        )
    else:
        forecast_summary = pd.DataFrame(columns=["forecast_cycle_start", "projected_demand", "inventory_applied", "order_needed"])

    customer_summary = (
        scoped.groupby(["customerName", "customerType", "locationName", "organization"], dropna=False, as_index=False)
        .agg(
            total_case_equiv=("case_equiv_qty", "sum"),
            cases_sold=("case_sale_qty", "sum"),
            split_units_sold=("split_unit_qty", "sum"),
            total_revenue=("customerPriceExt", "sum"),
            cycles_ordered=("periodStart", "nunique"),
        )
        .sort_values(["total_case_equiv", "total_revenue", "customerName"], ascending=[False, False, True])
    )

    if len(selected_cycles) >= 1:
        latest_cycle = selected_cycles[-1]
        latest_customer_qty = (
            scoped[scoped["periodStart"] == latest_cycle]
            .groupby("customerName")["case_equiv_qty"]
            .sum()
            .rename("latest_cycle_case_equiv")
        )
        customer_summary = customer_summary.merge(latest_customer_qty, on="customerName", how="left")
    if len(selected_cycles) >= 2:
        prior_cycle = selected_cycles[-2]
        prior_customer_qty = (
            scoped[scoped["periodStart"] == prior_cycle]
            .groupby("customerName")["case_equiv_qty"]
            .sum()
            .rename("prior_cycle_case_equiv")
        )
        customer_summary = customer_summary.merge(prior_customer_qty, on="customerName", how="left")

    customer_summary["latest_cycle_case_equiv"] = pd.to_numeric(customer_summary.get("latest_cycle_case_equiv", 0), errors="coerce").fillna(0)
    customer_summary["prior_cycle_case_equiv"] = pd.to_numeric(customer_summary.get("prior_cycle_case_equiv", 0), errors="coerce").fillna(0)
    customer_summary["change_vs_prior_cycle"] = customer_summary["latest_cycle_case_equiv"] - customer_summary["prior_cycle_case_equiv"]

    return {
        "filtered": scoped,
        "cycles": cycle_summary,
        "sku_plan": sku_plan,
        "customer_summary": customer_summary,
        "cycle_count": len(selected_cycles),
        "forecast_by_sku": forecast_df,
        "forecast_summary": forecast_summary,
        "future_cycle_starts": future_cycle_starts,
    }


def build_yogurt_cadence_plan(
    df: pd.DataFrame,
    producer_name: str,
    product_keyword: str,
    lookback_cycles: int = 6,
    status_filter: str | None = "COMPLETE",
    future_periods: int = 2,
    excluded_customer_regex: str | None = r"spoilage|refund",
    launch_accounts: Sequence[str] | None = None,
    inventory_by_sku: dict[str, float] | None = None,
) -> dict[str, object]:
    """Forecast Painterland yogurt demand using customer-SKU cadence rules.

    The cadence model works one customer/SKU pair at a time so new launch
    accounts and alternating buyers do not get washed out by aggregate trends.
    """

    required_cols = {"periodStart", "qty", "producerName", "productName"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")

    work_df = df.copy()
    work_df["periodStart"] = pd.to_datetime(work_df["periodStart"], errors="coerce")
    work_df["qty"] = pd.to_numeric(work_df["qty"], errors="coerce").fillna(0)
    if "customerPriceExt" in work_df.columns:
        work_df["customerPriceExt"] = pd.to_numeric(work_df["customerPriceExt"], errors="coerce").fillna(0)
    else:
        work_df["customerPriceExt"] = 0.0

    producer_mask = work_df["producerName"].fillna("").str.contains(producer_name, case=False, regex=False)
    product_mask = (
        work_df["productName"].fillna("").str.contains(product_keyword, case=False, regex=False)
        | work_df.get("subCategory", pd.Series("", index=work_df.index)).fillna("").str.contains(product_keyword, case=False, regex=False)
    )
    status_mask = pd.Series(True, index=work_df.index)
    if status_filter and "orderStatus" in work_df.columns:
        status_mask = work_df["orderStatus"].fillna("").eq(status_filter)

    filtered = work_df[producer_mask & product_mask & status_mask].copy()
    filtered = filtered[filtered["periodStart"].notna()].copy()
    if filtered.empty:
        return {
            "filtered": filtered,
            "history_cycles": pd.DataFrame(),
            "history_dates": [],
            "future_cycle_starts": [],
            "cycle_summary": pd.DataFrame(),
            "sku_forecast": pd.DataFrame(),
            "forecast_detail": pd.DataFrame(),
            "customer_summary": pd.DataFrame(),
            "current_cycle_sku": pd.DataFrame(),
        }

    filtered["customerName"] = filtered.get("customerName", pd.Series("Unknown", index=filtered.index)).fillna("Unknown")
    filtered["customerType"] = filtered.get("customerType", pd.Series("Unknown", index=filtered.index)).fillna("Unknown")
    filtered["locationName"] = filtered.get("locationName", pd.Series("", index=filtered.index)).fillna("")
    filtered["organization"] = filtered.get("organization", pd.Series("", index=filtered.index)).fillna("")
    filtered["unitName"] = filtered.get("unitName", pd.Series("", index=filtered.index)).fillna("")

    if excluded_customer_regex:
        filtered = filtered[
            ~filtered["customerName"].fillna("").str.contains(excluded_customer_regex, case=False, regex=True)
        ].copy()

    if filtered.empty:
        return {
            "filtered": filtered,
            "history_cycles": pd.DataFrame(),
            "history_dates": [],
            "future_cycle_starts": [],
            "cycle_summary": pd.DataFrame(),
            "sku_forecast": pd.DataFrame(),
            "forecast_detail": pd.DataFrame(),
            "customer_summary": pd.DataFrame(),
            "current_cycle_sku": pd.DataFrame(),
        }

    unit_info = filtered["unitName"].apply(parse_painterland_unit).apply(pd.Series)
    filtered = pd.concat([filtered, unit_info], axis=1)
    filtered["case_equiv_qty"] = np.where(
        filtered["is_case_sale"],
        filtered["qty"],
        filtered["qty"] / filtered["pack_size"],
    )
    filtered["case_sale_qty"] = np.where(filtered["is_case_sale"], filtered["qty"], 0.0)
    filtered["split_unit_qty"] = np.where(filtered["is_case_sale"], 0.0, filtered["qty"])

    available_cycles = sorted(filtered["periodStart"].dropna().unique())
    selected_cycles = available_cycles[-max(1, lookback_cycles):]
    scoped = filtered[filtered["periodStart"].isin(selected_cycles)].copy()

    cycle_summary = (
        scoped.groupby("periodStart", as_index=False)
        .agg(
            total_case_equiv=("case_equiv_qty", "sum"),
            total_cases_sold=("case_sale_qty", "sum"),
            total_split_units=("split_unit_qty", "sum"),
            active_customers=("customerName", "nunique"),
            revenue=("customerPriceExt", "sum"),
        )
        .sort_values("periodStart")
    )

    cycle_spacing_days = 7
    if len(selected_cycles) >= 2:
        diffs = pd.Series(selected_cycles).sort_values().diff().dropna().dt.days
        valid_diffs = diffs[diffs > 0]
        if not valid_diffs.empty:
            cycle_spacing_days = int(valid_diffs.median())

    latest_cycle = selected_cycles[-1]
    future_cycle_starts = [
        latest_cycle + pd.Timedelta(days=cycle_spacing_days * step)
        for step in range(1, max(1, future_periods) + 1)
    ]

    launch_account_keys = {_normalize_customer_label(name) for name in (launch_accounts or []) if str(name).strip()}
    customer_sku_history = (
        scoped.groupby(["customerName", "order_sku", "periodStart"], as_index=False)
        .agg(case_equiv_qty=("case_equiv_qty", "sum"))
    )
    wide = (
        customer_sku_history.pivot(index=["customerName", "order_sku"], columns="periodStart", values="case_equiv_qty")
        .reindex(columns=selected_cycles)
        .fillna(0.0)
    )

    def classify_customer_sku(history: np.ndarray, is_launch_account: bool) -> tuple[str, list[float], str]:
        values = np.array(history, dtype=float)
        nonzero_idx = np.where(values > 0)[0]
        nonzero_vals = values[nonzero_idx]
        active_weeks = len(nonzero_idx)

        if active_weeks == 0:
            return "inactive", [0.0] * len(future_cycle_starts), "no activity"

        if is_launch_account and active_weeks >= 2 and nonzero_idx[-1] == len(values) - 1:
            recent_nonzero = nonzero_vals[-min(2, active_weeks):]
            base = float(recent_nonzero.mean()) if len(recent_nonzero) else 0.0
            return (
                "launch_recurring",
                [base] * len(future_cycle_starts),
                f"launch account recent weeks={recent_nonzero.round(3).tolist()}",
            )

        if active_weeks >= 4:
            recent = values[-3:] if len(values) >= 3 else values
            weights = np.array([0.2, 0.3, 0.5])[-len(recent):]
            weights = weights / weights.sum()
            base = float(np.dot(recent, weights))
            return "weekly", [base] * len(future_cycle_starts), f"weighted recent 3 weeks={recent.round(3).tolist()}"

        if active_weeks >= 2:
            parity_counts = {
                0: int(np.sum((nonzero_idx % 2) == 0)),
                1: int(np.sum((nonzero_idx % 2) == 1)),
            }
            dominant_parity = 0 if parity_counts[0] >= parity_counts[1] else 1
            if parity_counts[dominant_parity] >= 2 and parity_counts[dominant_parity] >= active_weeks - 1:
                parity_values = values[[idx for idx in nonzero_idx if idx % 2 == dominant_parity]]
                base = float(parity_values.mean()) if len(parity_values) else float(nonzero_vals.mean())
                preds: list[float] = []
                for future_idx in range(len(values), len(values) + len(future_cycle_starts)):
                    preds.append(base if future_idx % 2 == dominant_parity else 0.0)
                return "biweekly", preds, f"parity={dominant_parity}, parity_values={parity_values.round(3).tolist()}"

            recent_nonzero = nonzero_vals[-min(2, active_weeks):]
            base = float(recent_nonzero.mean()) if len(recent_nonzero) else 0.0
            return "sporadic", [0.6 * base] * len(future_cycle_starts), f"recent_nonzero={recent_nonzero.round(3).tolist()}, damped 60%"

        if is_launch_account and nonzero_idx[-1] >= len(values) - 2:
            base = float(nonzero_vals[-1])
            return "launch_watch", [0.75 * base] * len(future_cycle_starts), f"recent single launch order={base:.3f}, carried at 75%"

        return "sporadic", [0.0] * len(future_cycle_starts), f"single hit only={float(nonzero_vals[-1]):.3f}"

    detail_rows: list[dict[str, object]] = []
    for (customer_name, order_sku), values in wide.iterrows():
        is_launch_account = _normalize_customer_label(customer_name) in launch_account_keys
        cadence, preds, logic_detail = classify_customer_sku(values.to_numpy(dtype=float), is_launch_account)
        row = {
            "customerName": customer_name,
            "order_sku": order_sku,
            "cadence": cadence,
            "is_launch_account": is_launch_account,
            "logic_detail": logic_detail,
            "active_weeks": int((values.to_numpy(dtype=float) > 0).sum()),
            "six_cycle_cases": float(values.sum()),
        }
        for idx, cycle_date in enumerate(selected_cycles):
            row[cycle_date.strftime("hist_%m%d")] = float(values.iloc[idx])
        for idx, cycle_date in enumerate(future_cycle_starts):
            row[f"proj_{cycle_date.strftime('%m%d')}"] = float(preds[idx])
        detail_rows.append(row)

    forecast_detail = pd.DataFrame(detail_rows)
    if forecast_detail.empty:
        sku_forecast = pd.DataFrame()
    else:
        aggregations: dict[str, tuple[str, str]] = {
            "customer_count": ("customerName", "nunique"),
            "launch_accounts": ("is_launch_account", "sum"),
            "weekly_pairs": ("cadence", lambda s: int((s == "weekly").sum())),
            "launch_pairs": ("cadence", lambda s: int(s.isin(["launch_recurring", "launch_watch"]).sum())),
            "biweekly_pairs": ("cadence", lambda s: int((s == "biweekly").sum())),
            "sporadic_pairs": ("cadence", lambda s: int((s == "sporadic").sum())),
        }
        for cycle_date in future_cycle_starts:
            col = f"proj_{cycle_date.strftime('%m%d')}"
            aggregations[col] = (col, "sum")
        sku_forecast = forecast_detail.groupby("order_sku", as_index=False).agg(**aggregations)

    inventory_by_sku = inventory_by_sku or {}
    if not sku_forecast.empty:
        sku_forecast["inventory_available"] = sku_forecast["order_sku"].map(lambda sku: float(inventory_by_sku.get(str(sku), 0.0)))
        projection_cols = [f"proj_{cycle_date.strftime('%m%d')}" for cycle_date in future_cycle_starts]
        sku_forecast["two_period_recommendation"] = sku_forecast[projection_cols].sum(axis=1)
        sku_forecast = sku_forecast.sort_values(["two_period_recommendation", "order_sku"], ascending=[False, True])

    current_cycle_sku = (
        scoped[scoped["periodStart"] == latest_cycle]
        .groupby("order_sku", as_index=False)
        .agg(
            latest_case_sales=("case_sale_qty", "sum"),
            latest_split_units=("split_unit_qty", "sum"),
            latest_case_equiv=("case_equiv_qty", "sum"),
            active_customers=("customerName", "nunique"),
        )
        .sort_values(["latest_case_equiv", "order_sku"], ascending=[False, True])
    )

    customer_summary = (
        scoped.groupby(["customerName", "customerType", "locationName", "organization"], dropna=False, as_index=False)
        .agg(
            total_case_equiv=("case_equiv_qty", "sum"),
            cases_sold=("case_sale_qty", "sum"),
            split_units_sold=("split_unit_qty", "sum"),
            total_revenue=("customerPriceExt", "sum"),
            cycles_ordered=("periodStart", "nunique"),
        )
        .sort_values(["total_case_equiv", "total_revenue", "customerName"], ascending=[False, False, True])
    )
    customer_summary["is_launch_account"] = customer_summary["customerName"].map(
        lambda name: _normalize_customer_label(name) in launch_account_keys
    )

    latest_customer_qty = (
        scoped[scoped["periodStart"] == latest_cycle]
        .groupby("customerName")["case_equiv_qty"]
        .sum()
        .rename("latest_cycle_case_equiv")
    )
    customer_summary = customer_summary.merge(latest_customer_qty, on="customerName", how="left")
    if len(selected_cycles) >= 2:
        prior_cycle = selected_cycles[-2]
        prior_customer_qty = (
            scoped[scoped["periodStart"] == prior_cycle]
            .groupby("customerName")["case_equiv_qty"]
            .sum()
            .rename("prior_cycle_case_equiv")
        )
        customer_summary = customer_summary.merge(prior_customer_qty, on="customerName", how="left")
    customer_summary["latest_cycle_case_equiv"] = pd.to_numeric(customer_summary.get("latest_cycle_case_equiv", 0), errors="coerce").fillna(0)
    customer_summary["prior_cycle_case_equiv"] = pd.to_numeric(customer_summary.get("prior_cycle_case_equiv", 0), errors="coerce").fillna(0)
    customer_summary["change_vs_prior_cycle"] = customer_summary["latest_cycle_case_equiv"] - customer_summary["prior_cycle_case_equiv"]

    return {
        "filtered": scoped,
        "history_cycles": cycle_summary,
        "history_dates": selected_cycles,
        "future_cycle_starts": future_cycle_starts,
        "cycle_summary": cycle_summary,
        "sku_forecast": sku_forecast,
        "forecast_detail": forecast_detail,
        "customer_summary": customer_summary,
        "current_cycle_sku": current_cycle_sku,
        "excluded_customer_regex": excluded_customer_regex,
        "launch_accounts": list(launch_accounts or []),
    }


def save_aggregation(df: pd.DataFrame, out_path: str) -> None:
    """Save aggregated DataFrame to CSV."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
