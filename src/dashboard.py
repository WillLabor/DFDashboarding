"""A Streamlit dashboard that can fetch API data or load a CSV.

This dashboard includes an "order value" view that uses the API response
structure where only one row per order contains the order-level totals.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)

# Ensure the workspace root is on sys.path so `import src.*` works when running
# the dashboard directly (e.g., `streamlit run src/dashboard.py`).
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data_loader import fetch_api_to_df, fetch_price_levels, fetch_availability_to_df, fetch_customers_from_api
from src.order_analysis import average_order_value_by_type_period, calculate_clv
from src.ml_experiments import run_customer_ml

DEFAULT_BASE_URL = "https://data.localfoodmarketplace.com"
DEFAULT_ENDPOINT = "/api/Orders"
DEFAULT_API_KEY = os.environ.get("LFM_API_KEY", "")
DEFAULT_LAST_DAYS = 730

SEGMENT_COLORS = {
    "Champions":          "#10b981",
    "Loyal":              "#3b82f6",
    "At-Risk":            "#f59e0b",
    "Regular":            "#8b5cf6",
    "New":                "#06b6d4",
    "Lost":               "#ef4444",
    "Occasional":         "#94a3b8",
    "Never Ordered":      "#475569",
    "Insufficient Data":  "#cbd5e1",
}


def _compute_date_range(
    last_days: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[str | None, str | None]:
    """Return an (ISO start, ISO end) tuple for API date filtering."""

    if start_date or end_date:
        return start_date, end_date

    if last_days is None:
        return None, None

    from datetime import datetime, timedelta, UTC

    now = datetime.now(UTC)
    start = now - timedelta(days=last_days)
    # Make naive for comparison with data
    start = start.replace(tzinfo=None)
    now = now.replace(tzinfo=None)
    return start.isoformat(), now.isoformat()


@st.cache_data(show_spinner=False)
def fetch_orders_from_api(
    base_url: str,
    endpoint: str,
    api_key: str,
    last_days: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Fetch order data from the API and return as a DataFrame."""

    url = endpoint
    if base_url and not endpoint.lower().startswith("http"):
        url = base_url.rstrip("/") + endpoint

    start_date, end_date = _compute_date_range(last_days, start_date, end_date)

    params: dict[str, str] = {}
    if start_date:
        params["startDate"] = start_date
    if end_date:
        params["endDate"] = end_date

    return fetch_api_to_df(
        url,
        params=params or None,
        api_key=api_key,
    )


def main(api_key: str | None = None, user_display_name: str | None = None) -> None:
    managed_mode = api_key is not None

    if not managed_mode:
        st.set_page_config(page_title="Delivered Fresh · Analytics", layout="wide", page_icon="🌿")

    # --- Modern CSS ---
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .block-container { padding-top: 2.5rem; padding-bottom: 2rem; }
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, #f6faf4 0%, #eef6eb 100%);
        border: 1px solid #c3ddb8;
        border-top: 3px solid #4a7c3f;
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 1px 3px rgba(74,124,63,0.10);
    }
    [data-testid="stMetricLabel"] { font-size: 0.75rem; font-weight: 600; color: #4a7c3f; text-transform: uppercase; letter-spacing: 0.05em; }
    [data-testid="stMetricValue"] { font-size: 1.6rem; font-weight: 700; color: #1e3d18; }
    [data-testid="stMetricDelta"] { font-size: 0.85rem; }
    .section-header { font-size: 1rem; font-weight: 600; color: #4a7c3f; text-transform: uppercase; letter-spacing: 0.08em; margin: 1.5rem 0 0.75rem; border-bottom: 2px solid #c3ddb8; padding-bottom: 0.4rem; }
    .filter-bar { background: #f6faf4; border-radius: 12px; padding: 16px; border: 1px solid #c3ddb8; margin-bottom: 1rem; }
    [data-testid="stSidebar"] { background: #1a2e14 !important; }
    [data-testid="stSidebar"] * { color: #ffffff !important; }
    [data-testid="stSidebar"] .stButton > button {
        background: #4a7c3f !important; color: #fff !important;
        border: none !important; border-radius: 8px !important;
        font-weight: 600 !important;
    }
    [data-testid="stSidebar"] .stButton > button:hover { background: #3a6231 !important; }
    [data-testid="stSidebar"] input, [data-testid="stSidebar"] select,
    [data-testid="stSidebar"] textarea,
    [data-testid="stSidebar"] [data-baseweb="input"] input,
    [data-testid="stSidebar"] [data-baseweb="select"] span,
    [data-testid="stSidebar"] [data-baseweb="select"] div,
    [data-testid="stSidebar"] .stNumberInput input,
    [data-testid="stSidebar"] .stTextInput input {
        background: #243d1c !important; color: #ffffff !important;
        border-color: #4a7c3f !important;
        -webkit-text-fill-color: #ffffff !important;
    }
    div[data-baseweb="select"] { border-color: #4a7c3f !important; }
    .stTabs [data-baseweb="tab-list"] { border-bottom-color: #c3ddb8; }
    .stTabs [data-baseweb="tab"][aria-selected="true"] {
        color: #4a7c3f !important; border-bottom-color: #4a7c3f !important;
        font-weight: 700;
    }
    .stProgress > div > div { background-color: #4a7c3f !important; }
    /* Compact multiselect: clamp tag area to one line, hide overflow */
    [data-testid="stMultiSelect"] [data-baseweb="select"] > div:first-child {
        max-height: 40px !important;
        overflow: hidden !important;
        flex-wrap: nowrap !important;
    }
    [data-testid="stMultiSelect"] [data-baseweb="tag"] {
        height: 26px !important;
        font-size: 0.72rem !important;
        padding: 0 6px !important;
        max-width: 140px !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # Dark / light mode toggle
    if "dark_mode" not in st.session_state:
        st.session_state.dark_mode = False
    dark = st.sidebar.toggle("Dark mode", value=st.session_state.dark_mode, key="dark_toggle")
    st.session_state.dark_mode = dark
    if dark:
        st.markdown("""
        <style>
        html, body, [class*="css"] { background-color: #0a140a !important; color: #d4edca !important; }
        [data-testid="stMetric"] { background: linear-gradient(135deg, #162212 0%, #0a140a 100%) !important; border-color: #3a6231 !important; border-top-color: #5a9348 !important; }
        [data-testid="stMetricLabel"] { color: #5a9348 !important; }
        [data-testid="stMetricValue"] { color: #d4edca !important; }
        .filter-bar { background: #162212 !important; border-color: #3a6231 !important; }
        .section-header { color: #5a9348 !important; border-color: #3a6231 !important; }
        </style>""", unsafe_allow_html=True)

    # ── Branded sidebar header ───────────────────────────────────────────────
    st.sidebar.markdown(
        """
        <div style="text-align:center; padding: 0.5rem 0 1rem;">
          <img src="https://images.squarespace-cdn.com/content/v1/655cf2b8c8ee2227cde11a60/05f282e9-37e2-43c5-940f-5155cac1c3e3/wsl-DF-white.png"
               style="width:140px; opacity:0.92;" alt="Delivered Fresh">
          <div style="font-size:0.65rem; color:#6dab5a; letter-spacing:0.12em; text-transform:uppercase; margin-top:0.4rem;">Analytics Dashboard</div>
        </div>
        <hr style="border-color:#2e4d26; margin:0 0 0.5rem;">
        """,
        unsafe_allow_html=True,
    )

    # ── Page header ─────────────────────────────────────────────────────────
    st.markdown(
        """
        <div style="background:#1a2e14; border-radius:12px; display:flex; align-items:center; gap:1.1rem; padding:0.8rem 1.4rem; margin-bottom:1.2rem; box-shadow:0 2px 8px rgba(0,0,0,0.18);">
          <img src="https://images.squarespace-cdn.com/content/v1/655cf2b8c8ee2227cde11a60/05f282e9-37e2-43c5-940f-5155cac1c3e3/wsl-DF-white.png"
               style="height:46px; flex-shrink:0;" alt="Delivered Fresh">
          <div style="border-left:1px solid #3a6231; padding-left:1.1rem;">
            <div style="font-size:1.45rem; font-weight:800; color:#ffffff; line-height:1.1;">Delivered Fresh</div>
            <div style="font-size:0.72rem; color:#8fce74; letter-spacing:0.12em; text-transform:uppercase; font-weight:600; margin-top:0.2rem;">Order &amp; Customer Analytics</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if managed_mode and user_display_name:
        st.sidebar.markdown(f"👤 **{user_display_name}**")
        st.sidebar.markdown("---")

    # Initialize session state for data persistence
    if "df" not in st.session_state:
        st.session_state.df = None
    if "price_levels_df" not in st.session_state:
        st.session_state.price_levels_df = None
    if "availability_df" not in st.session_state:
        st.session_state.availability_df = None
    if "customers_df" not in st.session_state:
        st.session_state.customers_df = None
    if "ml_results" not in st.session_state:
        st.session_state.ml_results = None

    df = st.session_state.df
    price_levels_df = st.session_state.price_levels_df
    availability_df = st.session_state.availability_df
    customers_df = st.session_state.customers_df
    ml_results = st.session_state.ml_results

    if not managed_mode:
        base_url = DEFAULT_BASE_URL
        endpoint = DEFAULT_ENDPOINT
    else:
        base_url = DEFAULT_BASE_URL
        endpoint = DEFAULT_ENDPOINT

    st.sidebar.markdown("---")
    st.sidebar.header("📅 Date Filter")

    from datetime import date, timedelta
    _default_end = date.today()
    _default_start = _default_end - timedelta(days=90)

    date_range = st.sidebar.date_input(
        "Order date range",
        value=(_default_start, _default_end),
        min_value=date(2015, 1, 1),
        max_value=_default_end,
        help="Select start and end dates. Click to open calendar.",
        key="order_date_range",
    )
    # date_input with range returns a tuple of 1 or 2 dates while user is selecting
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        _start_date_sel, _end_date_sel = date_range
    else:
        _start_date_sel = date_range[0] if isinstance(date_range, (list, tuple)) else date_range
        _end_date_sel = _default_end

    start_date_str = _start_date_sel.isoformat()
    end_date_str = _end_date_sel.isoformat()

    if st.sidebar.button("🔄 Fetch Orders", use_container_width=True):
        with st.spinner("Fetching from API…"):
            try:
                # Fetch only the selected date range (Option A)
                df = fetch_orders_from_api(
                    base_url=base_url,
                    endpoint=endpoint,
                    api_key=api_key,
                    last_days=None,
                    start_date=start_date_str,
                    end_date=end_date_str,
                )
                st.session_state.df = df
                st.session_state.selected_start = start_date_str
                st.session_state.selected_end = end_date_str
                st.session_state.fetch_start = start_date_str
                st.session_state.fetch_end = end_date_str
                st.success(f"Fetched {len(df):,} rows ({start_date_str} → {end_date_str}).")
            except Exception as exc:
                st.error(f"Error fetching data: {exc}")

    st.sidebar.markdown("---")
    st.sidebar.subheader("Product Availability")

    # Step 1: fetch the price levels (cheap — 1 API call, cached)
    if st.sidebar.button("Fetch Price Levels"):
        with st.spinner("Fetching price levels…"):
            try:
                pl_df = fetch_price_levels(base_url=base_url, api_key=api_key)
                st.session_state.price_levels_df = pl_df
                price_levels_df = pl_df
                st.sidebar.success(f"Found {len(pl_df)} price level(s).")
            except Exception as exc:
                st.sidebar.error(f"Price levels error: {exc}")

    # Step 2: choose a price level and fetch availability
    if price_levels_df is not None and not price_levels_df.empty:
        id_col = "id" if "id" in price_levels_df.columns else price_levels_df.columns[0]
        name_col = "name" if "name" in price_levels_df.columns else id_col
        default_col = "default" if "default" in price_levels_df.columns else None

        # Build display labels: "Retail (id=3)" style
        pl_options = [
            (int(row[id_col]), str(row[name_col]))
            for _, row in price_levels_df.iterrows()
        ]
        pl_labels = {pl_id: f"{pl_name} (id={pl_id})" for pl_id, pl_name in pl_options}

        selected_pl_id = st.sidebar.selectbox(
            "Select price level",
            options=[pl_id for pl_id, _ in pl_options],
            format_func=lambda x: pl_labels.get(x, str(x)),
            key="selected_price_level_id",
        )

        if st.sidebar.button("Fetch Availability"):
            with st.spinner(f"Fetching availability for price level {pl_labels.get(selected_pl_id)}…"):
                try:
                    avail_df = fetch_availability_to_df(
                        base_url=base_url,
                        api_key=api_key,
                        price_level_id=selected_pl_id,
                    )
                    st.session_state.availability_df = avail_df
                    availability_df = avail_df
                    if len(avail_df) > 0:
                        st.sidebar.success(f"Fetched {len(avail_df)} availability records.")
                    else:
                        st.sidebar.warning("API returned 0 records for this price level.")
                except Exception as exc:
                    st.sidebar.error(f"Availability error: {exc}")
    elif price_levels_df is not None:
        st.sidebar.warning("No price levels returned by API.")
    else:
        st.sidebar.info("Click 'Fetch Price Levels' first.")

    # ── Customer Data ────────────────────────────────────────────────────
    st.sidebar.markdown("---")
    st.sidebar.subheader("Customer Data")

    from datetime import datetime
    default_since = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
    cust_since = st.sidebar.date_input(
        "Last ordered after",
        value=date.today() - timedelta(days=730),
        min_value=date(2015, 1, 1),
        max_value=date.today(),
        help="Fetch customers who placed at least one order after this date.",
        key="cust_since_date",
    )
    if st.sidebar.button("Fetch Customers", use_container_width=True):
        with st.spinner("Fetching customer data…"):
            try:
                cdf = fetch_customers_from_api(
                    base_url=base_url,
                    api_key=api_key,
                    last_order_after=cust_since.isoformat() if cust_since else None,
                )
                st.session_state.customers_df = cdf
                customers_df = cdf
                st.sidebar.success(f"Fetched {len(cdf)} customers.")
            except Exception as exc:
                st.sidebar.error(f"Customer fetch error: {exc}")

    if customers_df is not None:
        st.sidebar.caption(f"{len(customers_df)} customers loaded.")

    # Determine what data is available to decide default view and visibility
    has_orders    = df is not None
    has_customers = customers_df is not None and not customers_df.empty

    if not has_orders and not has_customers:
        st.info("Fetch data using the sidebar buttons above (Orders or Customers).")
        return

    # Get selected date range for filtering
    selected_start = getattr(st.session_state, 'selected_start', None)
    selected_end = getattr(st.session_state, 'selected_end', None)

    if has_orders:
        st.sidebar.write(f"Orders loaded: {df.shape[0]:,} rows")

    # ── View picker in the main area ─────────────────────────────────────────
    VIEW_LABELS = {
        "Order value analysis": "📊 Orders",
        "Customer Segments":    "👥 Segments",
        "Customer LTV":         "💰 LTV",
        "Product Trends":       "📦 Products",
        "Product Availability": "📋 Availability",
        "Preview":              "🔍 Preview",
    }
    VIEW_KEYS = list(VIEW_LABELS.keys())
    VIEW_DISPLAY = [VIEW_LABELS[k] for k in VIEW_KEYS]

    # Default view index
    default_view_index = 1 if has_orders else (2 if has_customers else 0)
    if "selected_view" not in st.session_state:
        st.session_state.selected_view = VIEW_KEYS[default_view_index]

    # Pill-style tab row
    st.markdown("""
    <style>
    div[data-testid="stHorizontalBlock"] div[data-testid="column"] button[kind="secondary"] {
        border-radius: 20px !important; font-size: 0.82rem !important; padding: 4px 14px !important;
    }
    </style>""", unsafe_allow_html=True)

    tab_cols = st.columns(len(VIEW_KEYS))
    for i, (key, label) in enumerate(zip(VIEW_KEYS, VIEW_DISPLAY)):
        is_active = (st.session_state.selected_view == key)
        btn_type = "primary" if is_active else "secondary"
        if tab_cols[i].button(label, key=f"view_btn_{i}", type=btn_type, use_container_width=True):
            st.session_state.selected_view = key
            st.rerun()

    view = st.session_state.selected_view
    st.markdown("<hr style='margin:0.3rem 0 1rem; border-color:#c3ddb8;'>", unsafe_allow_html=True)

    # ── ML Scoring sidebar (Customer Segments only) ─────────────────────────
    if view == "Customer Segments" and has_customers:
        st.sidebar.markdown("---")
        st.sidebar.subheader("🤖 ML Scoring")
        if st.sidebar.button("Run ML Scoring", help="Train churn-risk & upgrade-potential models on loaded customers"):
            from src.order_analysis import segment_customers
            with st.spinner("Training models and scoring customers… (~10 sec)"):
                try:
                    seg_for_ml = segment_customers(customers_df)
                    ml_res = run_customer_ml(seg_for_ml)
                    st.session_state.ml_results = ml_res
                    ml_results = ml_res
                    churn_auc = ml_res.get("churn_auc", None)
                    upgrade_auc = ml_res.get("upgrade_auc", None)
                    msg = "ML scoring complete!"
                    if churn_auc:
                        msg += f"  Churn AUC: {churn_auc:.2f}"
                    if upgrade_auc:
                        msg += f"  Upgrade AUC: {upgrade_auc:.2f}"
                    st.sidebar.success(msg)
                except Exception as exc:
                    st.sidebar.error(f"ML error: {exc}")
        if ml_results is not None:
            churn_auc = ml_results.get("churn_auc")
            upgrade_auc = ml_results.get("upgrade_auc")
            if churn_auc:
                st.sidebar.caption(f"Churn model ROC-AUC: **{churn_auc:.2f}**")
            if upgrade_auc:
                st.sidebar.caption(f"Upgrade model ROC-AUC: **{upgrade_auc:.2f}**")

    if view == "Preview":
        if not has_orders:
            st.info("Fetch order data first using 'Fetch from API' in the sidebar.")
            return
        st.write("### Data Preview")
        st.dataframe(df)

        if st.sidebar.checkbox("Show summary statistics"):
            st.write("### Summary statistics")
            st.write(df.describe(include="all"))

        if st.sidebar.checkbox("Show data types"):
            st.write("### Data types")
            st.write(df.dtypes)

    elif view == "Order value analysis":
        if not has_orders:
            st.info("Fetch order data first using 'Fetch from API' in the sidebar.")
            return

        required_cols = {"orderId", "periodStart", "customerType", "orderSubTotal", "orderTotal"}
        if not required_cols.issubset(set(df.columns)):
            st.warning(
                "Order value analysis requires these columns: "
                + ", ".join(sorted(required_cols))
                + ".\nPlease fetch from the API or upload a matching orders CSV."
            )
            return

        from src.order_analysis import extract_orders_at_order_level
        # Load all orders with no status filter so customer history lookups are complete.
        # Status filtering is applied after the page filter bar (see _filtered_full below).
        order_df_full = extract_orders_at_order_level(df, status_filter=None)
        order_df_full["periodStart"] = pd.to_datetime(order_df_full["periodStart"], errors="coerce")
        order_df_full["customerType"] = order_df_full["customerType"].str.strip()

        email_col = "email" if "email" in order_df_full.columns else None

        # --- Build per-customer lookups from full 2-year data ---
        if email_col:
            customer_first_order = order_df_full.groupby(email_col)["periodStart"].min()
            customer_all_periods = order_df_full.groupby(email_col)["periodStart"].apply(set)

            def _avg_weeks(group):
                dates = sorted(group["periodStart"].dropna().unique())
                if len(dates) < 2:
                    return None
                diffs = [(dates[i + 1] - dates[i]).days / 7 for i in range(len(dates) - 1)]
                return sum(diffs) / len(diffs)

            customer_avg_weeks = order_df_full.groupby(email_col).apply(_avg_weeks)

        # --- Top filters ---
        unique_periods = sorted(order_df_full["periodStart"].dropna().unique())
        all_ctypes = sorted(order_df_full["customerType"].dropna().unique())

        period_meta = (
            pd.DataFrame({"periodStart": unique_periods})
            .dropna()
            .drop_duplicates()
            .sort_values("periodStart")
        )
        period_meta["Year"] = period_meta["periodStart"].dt.year
        period_meta["MonthStart"] = period_meta["periodStart"].dt.to_period("M").dt.to_timestamp()
        iso = period_meta["periodStart"].dt.isocalendar()
        period_meta["IsoYear"] = iso["year"].astype(int)
        period_meta["IsoWeek"] = iso["week"].astype(int)
        period_meta["WeekKey"] = (
            period_meta["IsoYear"].astype(str) + "-W" + period_meta["IsoWeek"].astype(str).str.zfill(2)
        )

        with st.container():
            st.markdown('<div class="filter-bar">', unsafe_allow_html=True)
            year_col, month_col, week_col = st.columns([1, 1, 1])

            available_years = sorted(period_meta["Year"].dropna().unique().tolist())
            with year_col:
                selected_years = st.multiselect(
                    "Year",
                    options=available_years,
                    default=available_years,
                    key="period_year_filter",
                )

            month_pool = period_meta[period_meta["Year"].isin(selected_years)]
            available_months = sorted(month_pool["MonthStart"].dropna().unique().tolist())
            with month_col:
                selected_months = st.multiselect(
                    "Month",
                    options=available_months,
                    default=available_months,
                    format_func=lambda x: x.strftime("%Y-%m") if pd.notna(x) else "",
                    key="period_month_filter",
                )

            week_pool = month_pool[month_pool["MonthStart"].isin(selected_months)]
            week_pairs = (
                week_pool[["IsoYear", "IsoWeek"]]
                .drop_duplicates()
                .sort_values(["IsoYear", "IsoWeek"])
                .itertuples(index=False, name=None)
            )
            available_weeks = [f"{y}-W{w:02d}" for y, w in week_pairs]
            with week_col:
                selected_weeks = st.multiselect(
                    "Week",
                    options=available_weeks,
                    default=available_weeks,
                    key="period_week_filter",
                )

            ctype_col, status_col = st.columns([1, 1])
            with ctype_col:
                selected_types = st.multiselect(
                    "Customer Type",
                    options=all_ctypes,
                    default=all_ctypes,
                    key="ctype_filter",
                )
            with status_col:
                status_options = ["All"]
                if "orderStatus" in order_df_full.columns:
                    status_options.extend(sorted(order_df_full["orderStatus"].dropna().unique()))
                complete_index = status_options.index("COMPLETE") if "COMPLETE" in status_options else 0
                selected_status = st.selectbox(
                    "Order Status",
                    options=status_options,
                    index=complete_index,
                    key="order_status_filter",
                )
            st.markdown('</div>', unsafe_allow_html=True)

        if not selected_years:
            st.info("Select at least one year above.")
            return
        if not selected_months:
            st.info("Select at least one month above.")
            return
        if not selected_weeks:
            st.info("Select at least one week above.")
            return
        if not selected_types:
            st.info("Select at least one customer type above.")
            return

        selected_periods = period_meta[
            period_meta["Year"].isin(selected_years)
            & period_meta["MonthStart"].isin(selected_months)
            & period_meta["WeekKey"].isin(selected_weeks)
        ]["periodStart"].tolist()

        if not selected_periods:
            st.info("No periodStart values match your Year/Month/Week filters.")
            return

        # Apply status filter (set by page filter bar above)
        status_filter = None if selected_status == "All" else selected_status
        if status_filter is not None and "orderStatus" in order_df_full.columns:
            _filtered_full = order_df_full[order_df_full["orderStatus"] == status_filter]
        else:
            _filtered_full = order_df_full

        display_df = _filtered_full[
            _filtered_full["periodStart"].isin(selected_periods) &
            _filtered_full["customerType"].isin(selected_types)
        ]

        # --- Build per-(period, customerType) metrics ---
        rows = []
        new_customer_rows = []  # for the new customers detail table
        for (period, ctype), grp in display_df.groupby(["periodStart", "customerType"]):
            revenue = grp["orderTotal"].sum()
            n_orders = grp["orderId"].nunique()
            aov = revenue / n_orders if n_orders else 0
            pct_over_100 = (grp["orderTotal"] > 100).sum() / n_orders * 100 if n_orders else 0

            if email_col:
                emails = grp[email_col].dropna().unique()
                new_custs_in_period = []
                for e in emails:
                    if customer_first_order.get(e) == period:
                        name = grp.loc[grp[email_col] == e, "customerName"].iloc[0] if "customerName" in grp.columns else ""
                        new_custs_in_period.append({"Email": e, "Name": name, "Customer Type": ctype, "First Period": period.strftime('%m/%d/%y')})
                new_customer_rows.extend(new_custs_in_period)
                new_custs = len(new_custs_in_period)
                recurring = sum(
                    1 for e in emails
                    if any(p < period for p in customer_all_periods.get(e, set()))
                )
                total_custs = len(emails)
                recurring_pct = recurring / total_custs * 100 if total_custs else 0
                weeks_vals = [
                    customer_avg_weeks.get(e)
                    for e in emails
                    if pd.notna(customer_avg_weeks.get(e))
                ]
                avg_weeks_period = sum(weeks_vals) / len(weeks_vals) if weeks_vals else None
            else:
                new_custs = 0
                recurring_pct = 0
                avg_weeks_period = None

            rows.append({
                "Period Start": period,
                "Customer Type": ctype,
                "Revenue": revenue,
                "Total Orders": n_orders,
                "AOV": aov,
                "% Orders >$100": pct_over_100,
                "New Customers *": new_custs,
                "Recurring % *": recurring_pct,
                "Avg Weeks *": avg_weeks_period,
            })

        metrics_df = pd.DataFrame(rows).sort_values(["Period Start", "Customer Type"])

        # --- Summary KPIs ---
        total_orders = int(metrics_df["Total Orders"].sum())
        total_revenue = metrics_df["Revenue"].sum()
        avg_order_value = total_revenue / total_orders if total_orders else 0
        pct_orders_over_100 = (display_df["orderTotal"] > 100).sum() / len(display_df) * 100 if len(display_df) else 0

        if email_col:
            filtered_emails = display_df[email_col].dropna().unique()
            num_new_customers = sum(1 for e in filtered_emails if customer_first_order.get(e) in selected_periods)
            recurring_count = sum(
                1 for e in filtered_emails
                if any(p < min(selected_periods) for p in customer_all_periods.get(e, set()))
            )
            total_custs = len(filtered_emails)
            recurring_pct = recurring_count / total_custs * 100 if total_custs else 0
            weeks_vals = [
                customer_avg_weeks.get(e)
                for e in filtered_emails
                if pd.notna(customer_avg_weeks.get(e))
            ]
            avg_weeks_between = sum(weeks_vals) / len(weeks_vals) if weeks_vals else None
        else:
            num_new_customers = 0
            recurring_pct = 0
            avg_weeks_between = None

        # --- KPI cards ---
        st.markdown('<p class="section-header">Summary</p>', unsafe_allow_html=True)
        _fetch_start = getattr(st.session_state, 'fetch_start', None)
        _fetch_end   = getattr(st.session_state, 'fetch_end', None)
        _range_label = f"{_fetch_start} → {_fetch_end}" if _fetch_start and _fetch_end else "fetched range"
        st.info(
            f"📊 **Revenue, Orders & AOV** reflect your selected filters. "
            f"**Metrics marked \\*** use all loaded data ({_range_label}) for accurate customer history.",
            icon=None,
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Revenue", f"${total_revenue:,.2f}")
        c2.metric("Total Orders", f"{total_orders:,}")
        c3.metric("AOV", f"${avg_order_value:.2f}")
        c4.metric("% Orders >$100", f"{pct_orders_over_100:.1f}%")
        c5, c6, c7, _ = st.columns(4)
        c5.metric("New Customers *", f"{num_new_customers:,}")
        c6.metric("Recurring % *", f"{recurring_pct:.1f}%")
        c7.metric("Avg Weeks Between Orders *", f"{avg_weeks_between:.1f}" if avg_weeks_between else "N/A")

        # --- AG Grid metrics table ---
        st.markdown('<p class="section-header">Metrics by Period & Customer Type</p>', unsafe_allow_html=True)

        grid_df = metrics_df.copy()
        grid_df["Period Start"] = grid_df["Period Start"].dt.strftime('%m/%d/%y')
        grid_df["Revenue"] = grid_df["Revenue"].round(2)
        grid_df["AOV"] = grid_df["AOV"].round(2)
        grid_df["% Orders >$100"] = grid_df["% Orders >$100"].round(1)
        grid_df["Recurring % *"] = grid_df["Recurring % *"].round(1)
        grid_df["Avg Weeks *"] = grid_df["Avg Weeks *"].apply(
            lambda x: round(x, 1) if x is not None and not (isinstance(x, float) and pd.isna(x)) else None
        )

        st.dataframe(
            grid_df,
            use_container_width=True,
            height=400,
            column_config={
                "Revenue": st.column_config.NumberColumn(format="$%.2f"),
                "AOV": st.column_config.NumberColumn(format="$%.2f"),
                "% Orders >$100": st.column_config.NumberColumn(format="%.1f%%"),
                "Recurring % *": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )

        # --- Plotly trend chart ---
        st.markdown('<p class="section-header">Trends</p>', unsafe_allow_html=True)
        chart_metrics = ["Revenue", "Total Orders", "AOV", "% Orders >$100", "New Customers *", "Recurring % *", "Avg Weeks *"]
        chart_metric = st.selectbox("Metric to chart", chart_metrics, index=0)

        chart_data = metrics_df.copy()
        chart_data["Avg Weeks *"] = pd.to_numeric(chart_data["Avg Weeks *"], errors="coerce")
        chart_data["Period Label"] = chart_data["Period Start"].dt.strftime('%m/%d/%y')

        fig = px.line(
            chart_data,
            x="Period Label",
            y=chart_metric,
            color="Customer Type",
            markers=True,
            template="plotly_dark" if dark else "plotly_white",
            labels={"Period Label": "Period Start", chart_metric: chart_metric},
        )
        fig.update_traces(line=dict(width=2.5), marker=dict(size=7))
        fig.update_layout(
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            hovermode="x unified",
            margin=dict(l=0, r=0, t=30, b=0),
            height=380,
        )
        st.plotly_chart(fig, use_container_width=True)

        # --- New customers table ---
        if new_customer_rows:
            st.markdown('<p class="section-header">New Customers (First Order in Selected Periods)</p>', unsafe_allow_html=True)
            new_cust_df = pd.DataFrame(new_customer_rows).sort_values(["First Period", "Customer Type"])
            st.dataframe(new_cust_df, use_container_width=True, height=300)

        # --- Plotly comparison tabs ---
        if len(metrics_df["Period Start"].unique()) > 1:
            st.markdown('<p class="section-header">Period Comparisons</p>', unsafe_allow_html=True)
            comp_tab1, comp_tab2, comp_tab3 = st.tabs(["📅 Week-over-Week", "🗓 Month-over-Month", "📆 Year-over-Year"])

            numeric_metrics = ["Revenue", "Total Orders", "AOV", "% Orders >$100", "New Customers *", "Recurring % *"]
            comp_df = metrics_df.copy()

            def _build_comparison(df_in, freq):
                d = df_in.groupby("Period Start")[numeric_metrics].sum()
                d.index = pd.to_datetime(d.index)
                resampled = d.resample(freq).sum()
                pct = resampled.pct_change() * 100
                return resampled, pct

            def _render_comparison_tab(raw, pct, metric_key, label_suffix):
                sel = st.selectbox(f"Metric", numeric_metrics, key=f"sel_{label_suffix}")
                col_a, col_b = st.columns([2, 1])
                with col_a:
                    fig2 = go.Figure()
                    fig2.add_trace(go.Bar(
                        x=raw.index.strftime('%m/%d/%y'),
                        y=raw[sel],
                        marker_color="#6366f1",
                        name=sel,
                    ))
                    fig2.update_layout(
                        template="plotly_dark" if dark else "plotly_white",
                        height=300,
                        margin=dict(l=0, r=0, t=20, b=0),
                        hovermode="x",
                    )
                    st.plotly_chart(fig2, use_container_width=True)
                with col_b:
                    pct_display = pct[[sel]].copy()
                    pct_display.index = pct_display.index.strftime('%m/%d/%y')
                    pct_display.columns = ["% Change"]
                    pct_display["% Change"] = pct_display["% Change"].apply(
                        lambda x: f"{x:+.1f}%" if pd.notna(x) else "—"
                    )
                    st.dataframe(pct_display, use_container_width=True)

            with comp_tab1:
                raw_wow, pct_wow = _build_comparison(comp_df, "W")
                _render_comparison_tab(raw_wow, pct_wow, "Revenue", "wow")
            with comp_tab2:
                raw_mom, pct_mom = _build_comparison(comp_df, "ME")
                _render_comparison_tab(raw_mom, pct_mom, "Revenue", "mom")
            with comp_tab3:
                raw_yoy, pct_yoy = _build_comparison(comp_df, "YE")
                _render_comparison_tab(raw_yoy, pct_yoy, "Revenue", "yoy")

    elif view == "Customer Segments":
        from src.order_analysis import segment_customers

        dark = st.sidebar.checkbox("Dark mode", value=False, key="dark_cust")

        # SEGMENT_COLORS is defined at module level
        SEGMENT_ACTIONS = {
            "Champions":     "🎁 Reward: loyalty programme, early product access, referral asks",
            "Loyal":         "⬆️  Upsell: premium bundles, subscription upgrade offer",
            "At-Risk":       "🚨 Win-back: personal call / email + limited-time discount",
            "Regular":       "📈 Nurture: increase frequency, recurring-order nudge",
            "New":           "👋 Onboard: welcome series, highlight popular products",
            "Lost":          "💌 Re-engage: 'We miss you' promo + satisfaction survey",
            "Occasional":    "🛒 Reactivate: seasonal promotions, low-barrier offer",
            "Never Ordered": "📣 Activate: first-order incentive / intro call",
        }

        if customers_df is None or customers_df.empty:
            st.title("👥 Customer Segments")
            st.info(
                "No customer data loaded yet.\n\n"
                "In the sidebar, set a **'Last ordered after'** date and click **Fetch Customers**."
            )
            return

        seg_df = segment_customers(customers_df)

        # ── KPI row ──────────────────────────────────────────────────────────
        st.title("👥 Customer Segments")
        total = len(seg_df)
        champ_loyal_n = int(seg_df["segment"].isin(["Champions", "Loyal"]).sum())
        at_risk_n  = int((seg_df["segment"] == "At-Risk").sum())
        lost_n     = int((seg_df["segment"] == "Lost").sum())
        new_n      = int((seg_df["segment"] == "New").sum())

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Total Customers", f"{total:,}")
        k2.metric("Champions + Loyal", f"{champ_loyal_n:,}", f"{champ_loyal_n/total*100:.0f}%")
        k3.metric("At-Risk", f"{at_risk_n:,}")
        k4.metric("Lost", f"{lost_n:,}")
        k5.metric("New", f"{new_n:,}")

        # ── Segment distribution charts ───────────────────────────────────────
        st.markdown('<p class="section-header">Segment Distribution</p>', unsafe_allow_html=True)

        seg_counts = (
            seg_df.groupby("segment", dropna=False)
            .agg(
                count=("totalOrders", "count"),
                avg_total_sales=("totalSales", "mean"),
                avg_total_orders=("totalOrders", "mean"),
                avg_days_since_last=("days_since_last_order", "mean"),
            )
            .reset_index()
            .round(1)
        )
        seg_counts["segment"] = seg_counts["segment"].fillna("Unknown")

        col_pie, col_bar = st.columns([1, 1.5])
        with col_pie:
            fig_pie = px.pie(
                seg_counts,
                values="count",
                names="segment",
                color="segment",
                color_discrete_map=SEGMENT_COLORS,
                hole=0.45,
                template="plotly_dark" if dark else "plotly_white",
                title="Customer Count by Segment",
            )
            fig_pie.update_traces(textposition="outside", textinfo="percent+label")
            fig_pie.update_layout(showlegend=False, margin=dict(l=0, r=0, t=40, b=0), height=380)
            st.plotly_chart(fig_pie, use_container_width=True)

        with col_bar:
            bar_data = seg_counts.sort_values("avg_total_sales", ascending=False)
            fig_bar = px.bar(
                bar_data,
                x="segment",
                y="avg_total_sales",
                color="segment",
                color_discrete_map=SEGMENT_COLORS,
                template="plotly_dark" if dark else "plotly_white",
                labels={"segment": "Segment", "avg_total_sales": "Avg Lifetime Sales ($)"},
                title="Average Lifetime Sales per Segment",
            )
            fig_bar.update_layout(showlegend=False, margin=dict(l=0, r=0, t=40, b=0), height=380)
            st.plotly_chart(fig_bar, use_container_width=True)

        # ── Segment profile + action table ────────────────────────────────────
        st.markdown('<p class="section-header">Segment Profiles & Marketing Actions</p>', unsafe_allow_html=True)

        profile = seg_counts.copy()
        profile["Suggested Action"] = profile["segment"].map(SEGMENT_ACTIONS).fillna("")
        profile = profile.rename(columns={
            "segment":             "Segment",
            "count":               "# Customers",
            "avg_total_sales":     "Avg Sales ($)",
            "avg_total_orders":    "Avg # Orders",
            "avg_days_since_last": "Avg Days Since Last Order",
        })
        profile = profile.sort_values("# Customers", ascending=False)

        st.dataframe(profile, use_container_width=True, height=340)

        # ── Customer drill-down by segment ────────────────────────────────────
        st.markdown('<p class="section-header">Customer List by Segment</p>', unsafe_allow_html=True)

        seg_options = sorted(seg_df["segment"].dropna().unique(),
                             key=lambda s: ["Champions","Loyal","At-Risk","Regular","New","Lost","Occasional","Never Ordered"].index(s)
                             if s in ["Champions","Loyal","At-Risk","Regular","New","Lost","Occasional","Never Ordered"] else 99)
        selected_seg = st.selectbox("Select segment to inspect", options=seg_options, key="seg_select")

        seg_customers = seg_df[seg_df["segment"] == selected_seg].copy()

        _cust_display_cols = [c for c in [
            "fullName", "email", "custType", "locName", "plName",
            "totalOrders", "totalSales", "days_since_last_order",
            "firstOrder", "lastOrder",
        ] if c in seg_customers.columns]
        cust_display = seg_customers[_cust_display_cols].copy()

        # Format dates to readable strings
        for dc in ("firstOrder", "lastOrder"):
            if dc in cust_display.columns:
                cust_display[dc] = pd.to_datetime(cust_display[dc], errors="coerce").dt.strftime("%Y-%m-%d")
        if "days_since_last_order" in cust_display.columns:
            cust_display["days_since_last_order"] = cust_display["days_since_last_order"].round(0).astype("Int64")
        if "totalSales" in cust_display.columns:
            cust_display["totalSales"] = cust_display["totalSales"].round(2)

        cust_display = cust_display.sort_values("totalSales", ascending=False) if "totalSales" in cust_display.columns else cust_display

        st.caption(f"{len(cust_display)} customers in **{selected_seg}** segment")
        st.dataframe(cust_display, use_container_width=True, height=420)

        # ── Order data enrichment (if orders are loaded) ─────────────────────
        if df is not None and "email" in seg_df.columns and "email" in df.columns:
            st.markdown('<p class="section-header">Order Insights for Selected Segment</p>', unsafe_allow_html=True)

            seg_emails = set(seg_customers["email"].dropna().str.strip().str.lower())
            df_copy = df.copy()
            df_copy["_email_lower"] = df_copy["email"].fillna("").str.strip().str.lower()
            seg_orders = df_copy[df_copy["_email_lower"].isin(seg_emails)].copy()

            if seg_orders.empty:
                st.info("No matching orders found for this segment (email join). Ensure both datasets use the same email addresses.")
            else:
                seg_orders["periodStart"] = pd.to_datetime(seg_orders["periodStart"], errors="coerce")

                oi_col1, oi_col2, oi_col3 = st.columns(3)
                if "orderTotal" in seg_orders.columns:
                    unique_seg_orders = seg_orders.drop_duplicates(subset=["orderId"]) if "orderId" in seg_orders.columns else seg_orders
                    oi_col1.metric("Orders in Dataset", f"{unique_seg_orders['orderId'].nunique() if 'orderId' in unique_seg_orders.columns else len(unique_seg_orders):,}")
                    oi_col2.metric("Avg Order Value", f"${unique_seg_orders['orderTotal'].mean():,.2f}")
                    oi_col3.metric("Total Revenue", f"${unique_seg_orders['orderTotal'].sum():,.0f}")

                ins_col1, ins_col2 = st.columns([1.2, 1])

                with ins_col1:
                    if "productName" in seg_orders.columns and "qty" in seg_orders.columns:
                        top_products = (
                            seg_orders.groupby("productName")["qty"]
                            .sum()
                            .nlargest(10)
                            .reset_index()
                            .rename(columns={"productName": "Product", "qty": "Units Ordered"})
                        )
                        fig_top = px.bar(
                            top_products,
                            x="Units Ordered",
                            y="Product",
                            orientation="h",
                            color_discrete_sequence=[SEGMENT_COLORS.get(selected_seg, "#3b82f6")],
                            template="plotly_dark" if dark else "plotly_white",
                            title=f"Top 10 Products — {selected_seg}",
                        )
                        fig_top.update_layout(yaxis=dict(autorange="reversed"), margin=dict(l=0, r=0, t=40, b=0), height=350)
                        st.plotly_chart(fig_top, use_container_width=True)

                with ins_col2:
                    if "periodStart" in seg_orders.columns and "orderTotal" in seg_orders.columns:
                        period_rev = (
                            seg_orders.drop_duplicates(subset=["orderId"])
                            .groupby(seg_orders["periodStart"].dt.to_period("M").astype(str))["orderTotal"]
                            .sum()
                            .reset_index()
                            .rename(columns={"periodStart": "Month", "orderTotal": "Revenue ($)"})
                            .tail(24)
                        )
                        fig_rev = px.line(
                            period_rev,
                            x="Month",
                            y="Revenue ($)",
                            markers=True,
                            color_discrete_sequence=[SEGMENT_COLORS.get(selected_seg, "#3b82f6")],
                            template="plotly_dark" if dark else "plotly_white",
                            title=f"Revenue Trend — {selected_seg}",
                        )
                        fig_rev.update_layout(margin=dict(l=0, r=0, t=40, b=0), height=350)
                        st.plotly_chart(fig_rev, use_container_width=True)

        # ── Look-alike / upgrade candidates ──────────────────────────────────
        if selected_seg in ("At-Risk", "Loyal", "Champions", "Regular"):
            with st.expander("🎯 Upgrade & Look-alike Candidates", expanded=False):
                if selected_seg in ("Loyal", "Champions"):
                    # Find Regular customers who have high avg order value (near Loyal tier)
                    loyal_min_sales = float(seg_df[seg_df["segment"].isin(["Loyal","Champions"])]["totalSales"].quantile(0.25))
                    candidates = seg_df[
                        (seg_df["segment"] == "Regular") &
                        (seg_df["totalSales"] >= loyal_min_sales)
                    ].copy()
                    label = "Regular customers close to Loyal tier (high lifetime value)"
                elif selected_seg == "At-Risk":
                    # High-spend At-Risk = highest win-back priority
                    at_risk_customers = seg_df[seg_df["segment"] == "At-Risk"].copy()
                    median_sales = float(at_risk_customers["totalSales"].median()) if len(at_risk_customers) else 0
                    candidates = at_risk_customers[at_risk_customers["totalSales"] >= median_sales]
                    label = "High-value At-Risk customers — top win-back priority"
                else:  # Regular
                    # Occasional customers with recent activity
                    candidates = seg_df[
                        (seg_df["segment"] == "Occasional") &
                        (seg_df["days_since_last_order"].fillna(999) < 90)
                    ].copy()
                    label = "Occasional customers who ordered recently — potential Regulars"

                st.caption(f"**{label}** ({len(candidates)} customers)")
                if not candidates.empty:
                    cand_cols = [c for c in ["fullName","email","custType","totalOrders","totalSales","days_since_last_order"] if c in candidates.columns]
                    cand_display = candidates[cand_cols].sort_values("totalSales", ascending=False) if "totalSales" in cand_cols else candidates[cand_cols]
                    st.dataframe(cand_display, use_container_width=True, height=300)
                else:
                    st.info("No candidates found for this segment.")

        # ── ML Insights ───────────────────────────────────────────────────────
        if ml_results is not None:
            scored_df = ml_results.get("scored_df")
            churn_imp  = ml_results.get("churn_importances")
            upgrade_imp = ml_results.get("upgrade_importances")

            st.markdown('<p class="section-header">🤖 ML Insights: Churn Risk & Upgrade Potential</p>', unsafe_allow_html=True)

            # Model quality
            auc_col1, auc_col2 = st.columns(2)
            with auc_col1:
                if "churn_auc" in ml_results:
                    st.metric("Churn Model ROC-AUC", f"{ml_results['churn_auc']:.2f}",
                              help="1.0 = perfect, 0.5 = random. Above 0.75 is good.")
            with auc_col2:
                if "upgrade_auc" in ml_results:
                    st.metric("Upgrade Model ROC-AUC", f"{ml_results['upgrade_auc']:.2f}",
                              help="1.0 = perfect, 0.5 = random. Above 0.75 is good.")

            # Feature importance charts
            if churn_imp is not None or upgrade_imp is not None:
                fi_col1, fi_col2 = st.columns(2)
                with fi_col1:
                    if churn_imp is not None:
                        fig_ci = px.bar(
                            x=churn_imp.values,
                            y=churn_imp.index,
                            orientation="h",
                            color_discrete_sequence=["#ef4444"],
                            template="plotly_dark" if dark else "plotly_white",
                            title="Churn Risk — Feature Importance",
                            labels={"x": "Importance", "y": ""},
                        )
                        fig_ci.update_layout(margin=dict(l=0, r=0, t=40, b=0), height=300)
                        st.plotly_chart(fig_ci, use_container_width=True)
                with fi_col2:
                    if upgrade_imp is not None:
                        fig_ui = px.bar(
                            x=upgrade_imp.values,
                            y=upgrade_imp.index,
                            orientation="h",
                            color_discrete_sequence=["#10b981"],
                            template="plotly_dark" if dark else "plotly_white",
                            title="Upgrade Potential — Feature Importance",
                            labels={"x": "Importance", "y": ""},
                        )
                        fig_ui.update_layout(margin=dict(l=0, r=0, t=40, b=0), height=300)
                        st.plotly_chart(fig_ui, use_container_width=True)

            if scored_df is not None and "churn_risk_score" in scored_df.columns:
                # ── Top win-back targets: NOT already Lost, high churn risk, high value
                st.markdown('<p class="section-header">🚨 Top Win-Back Targets</p>', unsafe_allow_html=True)
                st.caption("High churn risk score + high lifetime sales — prioritise these for outreach first.")
                winback = scored_df[
                    ~scored_df["segment"].isin(["Lost", "Never Ordered"]) &
                    scored_df["churn_risk_score"].notna()
                ].copy()
                winback = winback.nlargest(20, "churn_risk_score")
                wb_cols = [c for c in ["fullName", "email", "custType", "segment",
                                        "churn_risk_score", "upgrade_potential_score",
                                        "totalOrders", "totalSales", "days_since_last_order"] if c in winback.columns]
                winback_display = winback[wb_cols].round(1)
                winback_display.columns = [c.replace("churn_risk_score", "Churn Risk (0-100)").replace("upgrade_potential_score", "Upgrade Potential (0-100)") for c in winback_display.columns]
                st.dataframe(winback_display, use_container_width=True, height=340)

                # ── Top upsell / upgrade candidates
                if "upgrade_potential_score" in scored_df.columns:
                    st.markdown('<p class="section-header">⬆️ Top Upsell / Upgrade Candidates</p>', unsafe_allow_html=True)
                    st.caption("High upgrade potential but not yet Champions/Loyal — nudge these toward the next tier.")
                    upsell = scored_df[
                        ~scored_df["segment"].isin(["Champions", "Loyal", "Lost", "Never Ordered"]) &
                        scored_df["upgrade_potential_score"].notna()
                    ].copy()
                    upsell = upsell.nlargest(20, "upgrade_potential_score")
                    us_cols = [c for c in ["fullName", "email", "custType", "segment",
                                            "upgrade_potential_score", "churn_risk_score",
                                            "totalOrders", "totalSales", "days_since_last_order"] if c in upsell.columns]
                    upsell_display = upsell[us_cols].round(1)
                    upsell_display.columns = [c.replace("upgrade_potential_score", "Upgrade Potential (0-100)").replace("churn_risk_score", "Churn Risk (0-100)") for c in upsell_display.columns]
                    st.dataframe(upsell_display, use_container_width=True, height=340)

                # ── Score distribution scatter
                st.markdown('<p class="section-header">Score Distribution by Segment</p>', unsafe_allow_html=True)
                scatter_df = scored_df[
                    scored_df["churn_risk_score"].notna() &
                    scored_df.get("upgrade_potential_score", pd.Series(dtype=float)).notna()
                ].copy() if "upgrade_potential_score" in scored_df.columns else None

                if scatter_df is not None and not scatter_df.empty:
                    hover_name = "fullName" if "fullName" in scatter_df.columns else None
                    fig_sc = px.scatter(
                        scatter_df,
                        x="churn_risk_score",
                        y="upgrade_potential_score",
                        color="segment",
                        color_discrete_map=SEGMENT_COLORS,
                        hover_name=hover_name,
                        hover_data={c: True for c in ["totalSales", "totalOrders", "days_since_last_order"] if c in scatter_df.columns},
                        template="plotly_dark" if dark else "plotly_white",
                        labels={"churn_risk_score": "Churn Risk (0-100)", "upgrade_potential_score": "Upgrade Potential (0-100)"},
                        title="Churn Risk vs Upgrade Potential — each dot is a customer",
                        opacity=0.75,
                    )
                    fig_sc.add_vline(x=50, line_dash="dash", line_color="gray", opacity=0.4)
                    fig_sc.add_hline(y=50, line_dash="dash", line_color="gray", opacity=0.4)
                    fig_sc.update_layout(height=500, margin=dict(l=0, r=0, t=40, b=0))
                    st.plotly_chart(fig_sc, use_container_width=True)
                    st.caption("Top-right quadrant = high upgrade potential + low churn risk → Champions-in-waiting. "
                               "Top-left = high upgrade potential but high churn risk → act fast.")
        else:
            st.info("Click **Run ML Scoring** in the sidebar to generate churn risk and upgrade potential scores for every customer.")

    elif view == "Product Trends":
        if df is None:
            st.info("Fetch order data first from the API.")
            return

        st.title("📦 Product Trends Analysis")

        product_df = df.copy()
        product_df["periodStart"] = pd.to_datetime(product_df["periodStart"], errors="coerce")
        product_df["producerName"] = product_df["producerName"].fillna("Unknown").astype(str).str.strip()

        # Validate required columns
        required_product_cols = {"productName", "producerName", "periodStart", "qty"}
        if not required_product_cols.issubset(set(product_df.columns)):
            missing = required_product_cols - set(product_df.columns)
            st.warning(f"Missing columns for product analysis: {', '.join(sorted(missing))}")
            return

        # Identify available money columns (present in orders data when available)
        has_revenue = "customerPriceExt" in product_df.columns
        has_cost    = "costExt" in product_df.columns
        if has_revenue:
            product_df["customerPriceExt"] = pd.to_numeric(product_df["customerPriceExt"], errors="coerce").fillna(0)
        if has_cost:
            product_df["costExt"] = pd.to_numeric(product_df["costExt"], errors="coerce").fillna(0)
        if has_revenue and has_cost:
            product_df["margin"] = product_df["customerPriceExt"] - product_df["costExt"]

        unique_periods_product = sorted(product_df["periodStart"].dropna().unique())
        all_producers_product  = sorted(product_df["producerName"].dropna().unique())

        # ── Filter bar ────────────────────────────────────────────────────────
        with st.container():
            st.markdown('<div class="filter-bar">', unsafe_allow_html=True)
            pf_col1, pf_col2 = st.columns([1, 1])
            with pf_col1:
                _prev_prod = st.session_state.get("prod_producer_filter", [])
                _prod_label = (
                    f"Producer — {len(_prev_prod)} selected"
                    if _prev_prod else "Producer (select to begin)"
                )
                selected_producers_prod = st.multiselect(
                    _prod_label,
                    options=all_producers_product,
                    default=[],
                    key="prod_producer_filter",
                    placeholder="Choose one or more producers…",
                )
            with pf_col2:
                _n_periods_all = len(unique_periods_product)
                _prev_periods = st.session_state.get("prod_period_filter", unique_periods_product[-12:] if _n_periods_all > 12 else unique_periods_product)
                _n_periods_sel = len(_prev_periods)
                _period_label = (
                    f"Period — All {_n_periods_all}"
                    if _n_periods_sel == _n_periods_all
                    else f"Period — {_n_periods_sel} of {_n_periods_all}"
                )
                selected_product_periods = st.multiselect(
                    _period_label,
                    options=unique_periods_product,
                    default=unique_periods_product[-12:] if _n_periods_all > 12 else unique_periods_product,
                    format_func=lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else '',
                    key="prod_period_filter",
                )

            # Product multiselect — only shown after producers are selected, options driven by producer selection
            selected_products_prod = []
            if selected_producers_prod:
                available_products = sorted(
                    product_df[product_df["producerName"].isin(selected_producers_prod)]["productName"]
                    .dropna().unique().tolist()
                )
                _prev_prods = st.session_state.get("prod_product_filter", available_products)
                # Keep only values still valid for current producer selection
                _prev_prods = [p for p in _prev_prods if p in available_products]
                _n_prods_sel = len(_prev_prods) if _prev_prods else len(available_products)
                _n_prods_all = len(available_products)
                _prods_label = (
                    f"Product — All {_n_prods_all}"
                    if _n_prods_sel == _n_prods_all
                    else f"Product — {_n_prods_sel} of {_n_prods_all} selected"
                )
                selected_products_prod = st.multiselect(
                    _prods_label,
                    options=available_products,
                    default=available_products,
                    key="prod_product_filter",
                    placeholder="All products selected by default",
                )
            st.markdown('</div>', unsafe_allow_html=True)

        if not selected_producers_prod:
            st.info("Select one or more producers above to begin.")
            return
        if not selected_product_periods:
            st.info("Select at least one period.")
            return

        # Apply filters
        _prod_filter = selected_products_prod if selected_products_prod else []
        filtered_products = product_df[
            product_df["producerName"].isin(selected_producers_prod) &
            product_df["periodStart"].isin(selected_product_periods) &
            (product_df["productName"].isin(_prod_filter) if _prod_filter else True)
        ].copy()

        if filtered_products.empty:
            st.info("No data matches your current filters.")
            return

        # ── Top Products Summary (at top) ─────────────────────────────────────
        st.markdown('<p class="section-header">Top Products Summary — by Volume & Margin</p>', unsafe_allow_html=True)

        _agg: dict = {"qty": "sum"}
        if has_revenue:
            _agg["customerPriceExt"] = "sum"
        if has_cost:
            _agg["costExt"] = "sum"
        if has_revenue and has_cost:
            _agg["margin"] = "sum"

        prod_summary_all = (
            filtered_products.groupby(["producerName", "productName"])
            .agg(**{k: (k, v) for k, v in _agg.items()})
            .reset_index()
            .rename(columns={
                "qty": "Total Units",
                "customerPriceExt": "Revenue ($)",
                "costExt": "Cost ($)",
                "margin": "Margin ($)",
            })
        )

        top_n = 5
        sum_col1, sum_col2 = st.columns(2)

        with sum_col1:
            st.markdown("**📦 Top Products by Volume**")
            top_vol = prod_summary_all.nlargest(top_n * len(selected_producers_prod), "Total Units")
            fig_vol = px.bar(
                top_vol.head(top_n * max(1, len(selected_producers_prod))),
                x="Total Units",
                y="productName",
                color="producerName",
                orientation="h",
                template="plotly_dark" if dark else "plotly_white",
                labels={"productName": "", "producerName": "Producer"},
                title=f"Top {top_n} Products per Producer — Units",
            )
            fig_vol.update_layout(yaxis=dict(autorange="reversed"), margin=dict(l=0, r=0, t=40, b=0), height=320, showlegend=True)
            st.plotly_chart(fig_vol, use_container_width=True)

        with sum_col2:
            if has_revenue and has_cost and "Margin ($)" in prod_summary_all.columns:
                st.markdown("**💰 Top Products by Margin**")
                top_margin = prod_summary_all.nlargest(top_n * max(1, len(selected_producers_prod)), "Margin ($)")
                fig_margin = px.bar(
                    top_margin.head(top_n * max(1, len(selected_producers_prod))),
                    x="Margin ($)",
                    y="productName",
                    color="producerName",
                    orientation="h",
                    template="plotly_dark" if dark else "plotly_white",
                    labels={"productName": "", "producerName": "Producer"},
                    title=f"Top {top_n} Products per Producer — Margin ($)",
                )
                fig_margin.update_layout(yaxis=dict(autorange="reversed"), margin=dict(l=0, r=0, t=40, b=0), height=320, showlegend=True)
                st.plotly_chart(fig_margin, use_container_width=True)
            elif has_revenue and "Revenue ($)" in prod_summary_all.columns:
                st.markdown("**💰 Top Products by Revenue**")
                top_rev = prod_summary_all.nlargest(top_n * max(1, len(selected_producers_prod)), "Revenue ($)")
                fig_rev2 = px.bar(
                    top_rev.head(top_n * max(1, len(selected_producers_prod))),
                    x="Revenue ($)",
                    y="productName",
                    color="producerName",
                    orientation="h",
                    template="plotly_dark" if dark else "plotly_white",
                    labels={"productName": "", "producerName": "Producer"},
                    title=f"Top {top_n} Products per Producer — Revenue ($)",
                )
                fig_rev2.update_layout(yaxis=dict(autorange="reversed"), margin=dict(l=0, r=0, t=40, b=0), height=320, showlegend=True)
                st.plotly_chart(fig_rev2, use_container_width=True)
            else:
                st.info("Cost/revenue data not available in this dataset for margin analysis.")

        # Full summary table
        with st.expander("📋 Full product summary table", expanded=False):
            disp_cols = ["producerName", "productName", "Total Units"]
            if "Revenue ($)" in prod_summary_all.columns:
                disp_cols.append("Revenue ($)")
            if "Cost ($)" in prod_summary_all.columns:
                disp_cols.append("Cost ($)")
            if "Margin ($)" in prod_summary_all.columns:
                disp_cols.append("Margin ($)")
            st.dataframe(
                prod_summary_all[disp_cols].sort_values("Total Units", ascending=False).round(2),
                use_container_width=True, height=300,
            )

        # ── Trend chart over time ──────────────────────────────────────────────
        st.markdown('<p class="section-header">Trends Over Time by Producer</p>', unsafe_allow_html=True)

        trend_metric_options: dict[str, str] = {"Total Units": "qty"}
        if has_revenue:
            trend_metric_options["Total Revenue ($)"] = "customerPriceExt"
        if has_cost:
            trend_metric_options["Total Cost ($)"] = "costExt"
        if has_revenue and has_cost:
            trend_metric_options["Margin (Revenue − Cost)"] = "margin"

        selected_trend_label = st.selectbox(
            "Metric",
            options=list(trend_metric_options.keys()),
            index=0,
            key="prod_trend_metric",
        )
        trend_col = trend_metric_options[selected_trend_label]

        producer_trends = (
            filtered_products.groupby(["periodStart", "producerName"])
            .agg(**{trend_col: (trend_col, "sum")})
            .reset_index()
        )
        producer_trends["Period Label"] = producer_trends["periodStart"].dt.strftime('%Y-%m-%d')

        fig_producer = px.line(
            producer_trends,
            x="Period Label",
            y=trend_col,
            color="producerName",
            markers=True,
            template="plotly_dark" if dark else "plotly_white",
            labels={"Period Label": "Period", trend_col: selected_trend_label, "producerName": "Producer"},
            title=f"{selected_trend_label} by Producer Over Time",
        )
        fig_producer.update_traces(line=dict(width=2.5), marker=dict(size=7))
        fig_producer.update_layout(
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            hovermode="x unified",
            margin=dict(l=0, r=0, t=30, b=0),
            height=420,
        )
        st.plotly_chart(fig_producer, use_container_width=True)

        # ── Product drill-down ─────────────────────────────────────────────────
        st.markdown('<p class="section-header">Product Detail by Producer</p>', unsafe_allow_html=True)
        selected_producer_detail = st.selectbox(
            "Select a producer",
            options=sorted(selected_producers_prod),
            key="detail_producer_prod",
        )

        if selected_producer_detail:
            producer_products = filtered_products[filtered_products["producerName"] == selected_producer_detail]

            product_trends_df = (
                producer_products.groupby(["periodStart", "productName"])
                .agg(**{trend_col: (trend_col, "sum")})
                .reset_index()
            )
            product_trends_df["Period Label"] = product_trends_df["periodStart"].dt.strftime('%Y-%m-%d')

            # Top 10 products by selected metric
            top_products = (
                producer_products.groupby("productName")[trend_col]
                .sum()
                .nlargest(10)
                .index.tolist()
            )
            product_trends_top = product_trends_df[product_trends_df["productName"].isin(top_products)]

            fig_product = px.line(
                product_trends_top,
                x="Period Label",
                y=trend_col,
                color="productName",
                markers=True,
                template="plotly_dark" if dark else "plotly_white",
                labels={"Period Label": "Period", trend_col: selected_trend_label},
                title=f"Top 10 Products — {selected_producer_detail} — {selected_trend_label}",
            )
            fig_product.update_traces(line=dict(width=2.5), marker=dict(size=7))
            fig_product.update_layout(
                legend=dict(orientation="v", yanchor="top", y=0.99, xanchor="right", x=0.99),
                hovermode="x unified",
                margin=dict(l=0, r=0, t=30, b=0),
                height=420,
            )
            st.plotly_chart(fig_product, use_container_width=True)

    elif view == "Customer LTV":
        dark = st.sidebar.checkbox("Dark mode", value=False, key="dark_ltv")
        tpl  = "plotly_dark" if dark else "plotly_white"

        if not has_customers:
            st.title("💰 Customer Lifetime Value")
            st.info("Fetch your customers first using the **Fetch Customers** button in the sidebar.")
            return

        # ── Sidebar controls ──────────────────────────────────────────────────
        st.sidebar.markdown("---")
        st.sidebar.subheader("LTV Projection")
        proj_months = st.sidebar.select_slider(
            "Projection window",
            options=[3, 6, 12, 24, 36],
            value=12,
            help="How many months ahead to project each customer's spend.",
        )

        # ── Compute ───────────────────────────────────────────────────────────
        from src.order_analysis import segment_customers
        seg_df  = segment_customers(customers_df)
        clv_df  = calculate_clv(seg_df, projection_months=proj_months)

        active  = clv_df[clv_df["totalOrders"] > 0].copy()

        st.title("💰 Customer Lifetime Value")
        st.caption(
            f"Based on {len(clv_df):,} customers · "
            f"{len(active):,} with order history · "
            f"{proj_months}-month projection window"
        )

        # ── KPI row ───────────────────────────────────────────────────────────
        k1, k2, k3, k4, k5 = st.columns(5)
        total_portfolio = active["projected_clv"].sum()
        avg_clv         = active["projected_clv"].mean()
        median_clv      = active["projected_clv"].median()
        high_count      = (active["clv_tier"] == "High").sum()
        total_historical = active["historical_clv"].sum()

        k1.metric("Portfolio Projected CLV",  f"${total_portfolio:,.0f}",
                  help=f"Sum of all customers' {proj_months}-month projected spend")
        k2.metric("Avg Customer CLV",          f"${avg_clv:,.0f}")
        k3.metric("Median Customer CLV",       f"${median_clv:,.0f}")
        k4.metric("High-Tier Customers",       f"{high_count:,}",
                  help="Top third of customers by projected CLV")
        k5.metric("Total Historical Spend",    f"${total_historical:,.0f}")

        st.markdown("---")

        # ── Charts row ────────────────────────────────────────────────────────
        col_hist, col_seg = st.columns(2)

        with col_hist:
            fig_dist = px.histogram(
                active,
                x="projected_clv",
                color="clv_tier",
                nbins=40,
                color_discrete_map={"High": "#10b981", "Medium": "#3b82f6", "Low": "#f59e0b"},
                template=tpl,
                labels={"projected_clv": f"Projected CLV ({proj_months}m, $)", "count": "Customers"},
                title="CLV Distribution by Tier",
            )
            fig_dist.update_layout(margin=dict(l=0, r=0, t=40, b=0), height=340, bargap=0.05)
            st.plotly_chart(fig_dist, use_container_width=True)

        with col_seg:
            seg_clv = (
                active.groupby("segment")["projected_clv"]
                .agg(["mean", "sum", "count"])
                .rename(columns={"mean": "Avg CLV", "sum": "Total CLV", "count": "Customers"})
                .reset_index()
                .sort_values("Avg CLV", ascending=False)
            )
            fig_seg = px.bar(
                seg_clv,
                x="segment",
                y="Avg CLV",
                color="segment",
                color_discrete_map=SEGMENT_COLORS,
                text="Customers",
                hover_data={"Total CLV": ":.0f", "Avg CLV": ":.0f", "Customers": True},
                template=tpl,
                labels={"Avg CLV": f"Avg Projected CLV ({proj_months}m, $)", "segment": ""},
                title="Average CLV by Segment",
            )
            fig_seg.update_traces(texttemplate="%{text} customers", textposition="outside")
            fig_seg.update_layout(margin=dict(l=0, r=0, t=40, b=0), height=340, showlegend=False)
            st.plotly_chart(fig_seg, use_container_width=True)

        # ── AOV vs Purchase Rate scatter ──────────────────────────────────────
        st.markdown('<p class="section-header">AOV vs Purchase Frequency</p>', unsafe_allow_html=True)
        hover_name = "fullName" if "fullName" in active.columns else None
        fig_scatter = px.scatter(
            active,
            x="orders_per_month",
            y="avg_order_value",
            size="historical_clv",
            color="segment",
            color_discrete_map=SEGMENT_COLORS,
            hover_name=hover_name,
            hover_data={c: True for c in ["totalOrders", "totalSales", "projected_clv", "clv_tier"] if c in active.columns},
            size_max=40,
            template=tpl,
            labels={"orders_per_month": "Orders / Month", "avg_order_value": "Avg Order Value ($)"},
            title=f"Bubble size = historical spend · each dot is a customer",
            opacity=0.7,
        )
        fig_scatter.update_layout(height=450, margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig_scatter, use_container_width=True)
        st.caption(
            "Top-right = high value + high frequency → your best CLV customers. "
            "Top-left = high AOV but infrequent → re-engagement opportunities."
        )

        # ── Segment CLV summary table ─────────────────────────────────────────
        st.markdown('<p class="section-header">CLV Summary by Segment</p>', unsafe_allow_html=True)
        seg_summary = (
            active.groupby("segment").agg(
                Customers=("projected_clv", "count"),
                Avg_Historical_CLV=("historical_clv", "mean"),
                Avg_Projected_CLV=("projected_clv", "mean"),
                Total_Projected_CLV=("projected_clv", "sum"),
                Avg_AOV=("avg_order_value", "mean"),
                Avg_Orders_Per_Month=("orders_per_month", "mean"),
            )
            .round(2)
            .reset_index()
            .sort_values("Total_Projected_CLV", ascending=False)
        )
        seg_summary = seg_summary.rename(columns={
            "Avg_Historical_CLV": "Avg Historical CLV ($)",
            "Avg_Projected_CLV": f"Avg Projected CLV {proj_months}m ($)",
            "Total_Projected_CLV": f"Total Projected CLV {proj_months}m ($)",
            "Avg_AOV": "Avg Order Value ($)",
            "Avg_Orders_Per_Month": "Avg Orders / Month",
        })
        st.dataframe(seg_summary, use_container_width=True, height=280)

        # ── Full customer CLV table ────────────────────────────────────────────
        st.markdown('<p class="section-header">All Customers — CLV Breakdown</p>', unsafe_allow_html=True)
        clv_cols = [c for c in [
            "fullName", "email", "custType", "segment", "clv_tier",
            "historical_clv", "projected_clv", "avg_order_value",
            "orders_per_month", "totalOrders", "days_since_last_order",
        ] if c in clv_df.columns]
        clv_display = clv_df[clv_cols].sort_values("projected_clv", ascending=False).round(2)
        clv_display = clv_display.rename(columns={
            "historical_clv": "Historical CLV ($)",
            "projected_clv": f"Projected CLV {proj_months}m ($)",
            "avg_order_value": "Avg Order Value ($)",
            "orders_per_month": "Orders / Month",
            "days_since_last_order": "Days Since Last Order",
            "clv_tier": "CLV Tier",
        })
        st.dataframe(clv_display, use_container_width=True, height=480)

    elif view == "Product Availability":
        dark = st.sidebar.checkbox("Dark mode", value=False, key="dark_avail")

        if availability_df is None or availability_df.empty:
            st.title("📋 Product Availability")
            st.info(
                "No availability data loaded. In the sidebar:\n\n"
                "1. Click **Fetch Price Levels** to discover your price level IDs.\n"
                "2. Select a price level from the dropdown.\n"
                "3. Click **Fetch Availability** to load data."
            )
            return

        st.title("📋 Product Availability Analysis")

        avail = availability_df.copy()
        avail["periodStart"] = pd.to_datetime(avail["periodStart"], errors="coerce")

        # Column-name safety (API returns 'producer' not 'producerName')
        producer_col = "producer" if "producer" in avail.columns else (
            "producerName" if "producerName" in avail.columns else None
        )
        if producer_col is None or "productName" not in avail.columns:
            st.warning(f"Unexpected columns in availability data: {list(avail.columns)}")
            st.dataframe(avail.head(50))
            return

        avail[producer_col] = avail[producer_col].fillna("Unknown").str.strip()
        all_avail_producers = sorted(avail[producer_col].dropna().unique())
        all_avail_periods = sorted(avail["periodStart"].dropna().unique())

        # --- Filters ---
        with st.container():
            st.markdown('<div class="filter-bar">', unsafe_allow_html=True)
            fa_col1, fa_col2 = st.columns([1, 1])
            with fa_col1:
                sel_avail_producers = st.multiselect(
                    "Filter by Producer",
                    options=all_avail_producers,
                    default=all_avail_producers[:5] if len(all_avail_producers) > 5 else all_avail_producers,
                    key="avail_producer_filter",
                )
            with fa_col2:
                sel_avail_periods = st.multiselect(
                    "Filter by Period Start",
                    options=all_avail_periods,
                    default=all_avail_periods[-12:] if len(all_avail_periods) > 12 else all_avail_periods,
                    format_func=lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else '',
                    key="avail_period_filter",
                )
            st.markdown('</div>', unsafe_allow_html=True)

        if not sel_avail_producers or not sel_avail_periods:
            st.info("Select at least one producer and one period.")
            return

        filtered_avail = avail[
            avail[producer_col].isin(sel_avail_producers) &
            avail["periodStart"].isin(sel_avail_periods)
        ]

        # --- Listing vs Sold trends ---
        qty_cols = [c for c in ["quantityListed", "quantityAvailable", "quantitySold"] if c in avail.columns]
        if qty_cols:
            st.markdown('<p class="section-header">Quantity Trends by Producer</p>', unsafe_allow_html=True)
            trend_agg = filtered_avail.groupby(["periodStart", producer_col])[qty_cols].sum().reset_index()
            trend_agg["Period Label"] = trend_agg["periodStart"].dt.strftime('%Y-%m-%d')
            metric_to_plot = st.selectbox("Metric", options=qty_cols,
                                          format_func=lambda c: c.replace("quantity", "Qty "),
                                          key="avail_metric")
            fig_avail = px.line(
                trend_agg,
                x="Period Label",
                y=metric_to_plot,
                color=producer_col,
                markers=True,
                template="plotly_dark" if dark else "plotly_white",
                labels={"Period Label": "Period", producer_col: "Producer"},
                title=f"{metric_to_plot.replace('quantity', 'Qty ')} by Producer",
            )
            fig_avail.update_traces(line=dict(width=2.5), marker=dict(size=7))
            fig_avail.update_layout(
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                hovermode="x unified", margin=dict(l=0, r=0, t=30, b=0), height=400,
            )
            st.plotly_chart(fig_avail, use_container_width=True)

        # --- Summary table per producer ---
        st.markdown('<p class="section-header">Availability Summary by Producer</p>', unsafe_allow_html=True)
        agg_dict = {"productName": "nunique"}
        for c in ["quantityListed", "quantityAvailable", "quantitySold"]:
            if c in filtered_avail.columns:
                agg_dict[c] = "sum"
        avail_summary = (
            filtered_avail.groupby(producer_col)
            .agg(**{("num_products" if k == "productName" else k): (k, v) for k, v in agg_dict.items()})
            .reset_index()
            .sort_values("quantitySold" if "quantitySold" in agg_dict else producer_col, ascending=False)
            .round(1)
        )
        st.dataframe(avail_summary, use_container_width=True, height=300)

        # --- Product drill-down ---
        st.markdown('<p class="section-header">Product Detail by Producer</p>', unsafe_allow_html=True)
        sel_avail_producer_detail = st.selectbox(
            "Select a producer", options=sorted(sel_avail_producers), key="avail_detail_producer"
        )
        if sel_avail_producer_detail:
            prod_detail = filtered_avail[filtered_avail[producer_col] == sel_avail_producer_detail]
            detail_agg = {k: v for k, v in agg_dict.items() if k != "productName"}
            if detail_agg:
                prod_table = (
                    prod_detail.groupby("productName")
                    .agg(**{c: (c, "sum") for c in detail_agg})
                    .reset_index()
                    .sort_values(list(detail_agg.keys())[0], ascending=False)
                    .round(1)
                )
                st.dataframe(prod_table, use_container_width=True, height=350)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    main()
