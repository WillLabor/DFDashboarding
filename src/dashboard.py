"""A Streamlit dashboard that can fetch API data or load a CSV.

This dashboard includes an "order value" view that uses the API response
structure where only one row per order contains the order-level totals.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import warnings
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

warnings.filterwarnings("ignore", category=DeprecationWarning)

# Ensure the workspace root is on sys.path so `import src.*` works when running
# the dashboard directly (e.g., `streamlit run src/dashboard.py`).
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data_loader import fetch_api_to_df, fetch_price_levels, fetch_availability_to_df, fetch_customers_from_api
from src.order_analysis import average_order_value_by_type_period

DEFAULT_BASE_URL = "https://data-dev.localfoodmarketplace.com"
DEFAULT_ENDPOINT = "/api/Orders"
DEFAULT_API_KEY = "158d2724-fa51-4f7d-be0e-682e4e2860dc"
DEFAULT_LAST_DAYS = 730


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


def main() -> None:
    st.set_page_config(page_title="Orders Dashboard", layout="wide", page_icon="📦")

    # --- Modern CSS ---
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    [data-testid="stMetricLabel"] { font-size: 0.75rem; font-weight: 600; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; }
    [data-testid="stMetricValue"] { font-size: 1.6rem; font-weight: 700; color: #1e293b; }
    .section-header { font-size: 1rem; font-weight: 600; color: #475569; text-transform: uppercase; letter-spacing: 0.08em; margin: 1.5rem 0 0.75rem; border-bottom: 2px solid #e2e8f0; padding-bottom: 0.4rem; }
    .filter-bar { background: #f8fafc; border-radius: 12px; padding: 16px; border: 1px solid #e2e8f0; margin-bottom: 1rem; }
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
        html, body, [class*="css"] { background-color: #0e1117 !important; color: #f1f5f9 !important; }
        [data-testid="stMetric"] { background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%) !important; border-color: #334155 !important; }
        [data-testid="stMetricLabel"] { color: #94a3b8 !important; }
        [data-testid="stMetricValue"] { color: #f1f5f9 !important; }
        .filter-bar { background: #1e293b !important; border-color: #334155 !important; }
        .section-header { color: #94a3b8 !important; border-color: #334155 !important; }
        </style>""", unsafe_allow_html=True)

    st.title("📦 Orders Dashboard")

    source = st.sidebar.radio("Data source", ["API", "CSV upload"], index=0)

    # Initialize session state for data persistence
    if "df" not in st.session_state:
        st.session_state.df = None
    if "price_levels_df" not in st.session_state:
        st.session_state.price_levels_df = None
    if "availability_df" not in st.session_state:
        st.session_state.availability_df = None
    if "customers_df" not in st.session_state:
        st.session_state.customers_df = None

    df = st.session_state.df
    price_levels_df = st.session_state.price_levels_df
    availability_df = st.session_state.availability_df
    customers_df = st.session_state.customers_df

    if source == "API":
        st.sidebar.header("API settings")
        base_url = st.sidebar.text_input("Base URL", DEFAULT_BASE_URL, disabled=True)
        endpoint = st.sidebar.text_input("Endpoint", DEFAULT_ENDPOINT, disabled=True)
        api_key = st.sidebar.text_input(
            "API key",
            DEFAULT_API_KEY,
            type="password",
            disabled=True,
        )

        st.sidebar.markdown("---")
        st.sidebar.header("Date filter")
        last_days = st.sidebar.number_input(
            "Last N days", min_value=1, max_value=730, value=DEFAULT_LAST_DAYS, step=1
        )
        start_date = st.sidebar.text_input(
            "Start date (ISO)", "", help="Optional: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS"
        )
        end_date = st.sidebar.text_input(
            "End date (ISO)", "", help="Optional: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS"
        )

        if st.sidebar.button("Fetch from API"):
            with st.spinner("Fetching from API…"):
                try:
                    # Always fetch last 730 days for calculations, but filter display later
                    df = fetch_orders_from_api(
                        base_url=base_url,
                        endpoint=endpoint,
                        api_key=api_key,
                        last_days=730,  # Always fetch 2 years
                        start_date=None,
                        end_date=None,
                    )
                    st.session_state.df = df  # Persist in session state
                    st.session_state.selected_start, st.session_state.selected_end = _compute_date_range(
                        last_days, start_date or None, end_date or None
                    )
                    st.success("Fetched data successfully.")
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

        from datetime import datetime, timedelta
        default_since = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
        cust_since = st.sidebar.text_input(
            "Last ordered after (ISO)",
            value=default_since,
            help="Fetch customers who placed at least one order after this date. Leave blank for all.",
            key="cust_since_date",
        )
        if st.sidebar.button("Fetch Customers"):
            with st.spinner("Fetching customer data…"):
                try:
                    cdf = fetch_customers_from_api(
                        base_url=base_url,
                        api_key=api_key,
                        last_order_after=cust_since.strip() or None,
                    )
                    st.session_state.customers_df = cdf
                    customers_df = cdf
                    st.sidebar.success(f"Fetched {len(cdf)} customers.")
                except Exception as exc:
                    st.sidebar.error(f"Customer fetch error: {exc}")

        if customers_df is not None:
            st.sidebar.caption(f"{len(customers_df)} customers loaded.")
        csv_file = st.sidebar.file_uploader("Upload a CSV file", type=["csv"])
        if csv_file is not None:
            df = pd.read_csv(csv_file)
            st.session_state.df = df  # Persist in session state

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

    # Default view: Customer Segments when only customer data is available
    default_view_index = 2 if (has_customers and not has_orders) else 1

    view = st.sidebar.selectbox(
        "View",
        ["Preview", "Order value analysis", "Customer Segments", "Product Trends", "Product Availability"],
        index=default_view_index,
    )

    if view == "Order value analysis" and has_orders:
        # Add status filter if orderStatus column exists
        status_options = ["All"]
        if "orderStatus" in df.columns:
            unique_statuses = sorted(df["orderStatus"].dropna().unique())
            status_options.extend(unique_statuses)
        complete_index = status_options.index("COMPLETE") if "COMPLETE" in status_options else 0
        selected_status = st.sidebar.selectbox("Order Status Filter", status_options, index=complete_index)

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

        status_filter = None if selected_status == "All" else selected_status

        from src.order_analysis import extract_orders_at_order_level
        order_df_full = extract_orders_at_order_level(df, status_filter=status_filter)
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

            ctype_col, _ = st.columns([1, 2])
            with ctype_col:
                selected_types = st.multiselect(
                    "Filter by Customer Type",
                    options=all_ctypes,
                    default=all_ctypes,
                    key="ctype_filter",
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

        display_df = order_df_full[
            order_df_full["periodStart"].isin(selected_periods) &
            order_df_full["customerType"].isin(selected_types)
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
        st.caption("* Metrics marked with * use rolling 2-year data")
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

        gb = GridOptionsBuilder.from_dataframe(grid_df)
        gb.configure_default_column(resizable=True, sortable=True, filter=True, min_column_width=100)
        gb.configure_column("Revenue", type=["numericColumn"], valueFormatter="'$' + value.toLocaleString('en-US', {minimumFractionDigits:2})")
        gb.configure_column("AOV", type=["numericColumn"], valueFormatter="'$' + value.toFixed(2)")
        gb.configure_column("% Orders >$100", type=["numericColumn"], valueFormatter="value + '%'")
        gb.configure_column("Recurring % *", type=["numericColumn"], valueFormatter="value + '%'")
        gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=20)
        gb.configure_grid_options(domLayout='autoHeight')
        grid_options = gb.build()

        AgGrid(
            grid_df,
            gridOptions=grid_options,
            update_mode=GridUpdateMode.NO_UPDATE,
            height=400,
            use_container_width=True,
            allow_unsafe_jscode=True,
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
            gb2 = GridOptionsBuilder.from_dataframe(new_cust_df)
            gb2.configure_default_column(resizable=True, sortable=True, filter=True)
            gb2.configure_pagination(paginationAutoPageSize=False, paginationPageSize=15)
            AgGrid(
                new_cust_df,
                gridOptions=gb2.build(),
                update_mode=GridUpdateMode.NO_UPDATE,
                height=300,
                use_container_width=True,
            )

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

        SEGMENT_COLORS = {
            "Champions":     "#10b981",
            "Loyal":         "#3b82f6",
            "At-Risk":       "#f59e0b",
            "Regular":       "#8b5cf6",
            "New":           "#06b6d4",
            "Lost":          "#ef4444",
            "Occasional":    "#94a3b8",
            "Never Ordered": "#475569",
            "Insufficient Data": "#cbd5e1",
        }
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

        gb_p = GridOptionsBuilder.from_dataframe(profile)
        gb_p.configure_default_column(resizable=True, sortable=True, filter=True, wrapText=True, autoHeight=True)
        gb_p.configure_column("Suggested Action", minWidth=340)
        gb_p.configure_column("Segment", minWidth=140)
        gb_p.configure_pagination(paginationAutoPageSize=False, paginationPageSize=10)
        AgGrid(
            profile,
            gridOptions=gb_p.build(),
            update_mode=GridUpdateMode.NO_UPDATE,
            height=340,
            use_container_width=True,
        )

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
        gb_c = GridOptionsBuilder.from_dataframe(cust_display)
        gb_c.configure_default_column(resizable=True, sortable=True, filter=True)
        gb_c.configure_pagination(paginationAutoPageSize=False, paginationPageSize=20)
        AgGrid(
            cust_display,
            gridOptions=gb_c.build(),
            update_mode=GridUpdateMode.NO_UPDATE,
            height=420,
            use_container_width=True,
        )

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
                    gb_cand = GridOptionsBuilder.from_dataframe(cand_display)
                    gb_cand.configure_default_column(resizable=True, sortable=True, filter=True)
                    gb_cand.configure_pagination(paginationAutoPageSize=False, paginationPageSize=15)
                    AgGrid(cand_display, gridOptions=gb_cand.build(), update_mode=GridUpdateMode.NO_UPDATE, height=300, use_container_width=True)
                else:
                    st.info("No candidates found for this segment.")

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
        available_cols = set(product_df.columns)
        missing = required_product_cols - available_cols

        if missing:
            st.warning(f"Missing columns for product analysis: {', '.join(sorted(missing))}")
            return

        unique_periods_product = sorted(product_df["periodStart"].dropna().unique())
        all_producers_product = sorted(product_df["producerName"].dropna().unique())

        # --- Product Filters ---
        with st.container():
            st.markdown('<div class="filter-bar">', unsafe_allow_html=True)
            filter_col1, filter_col2 = st.columns([1, 1])
            with filter_col1:
                selected_producers_prod = st.multiselect(
                    "Filter by Producer",
                    options=all_producers_product,
                    default=all_producers_product[:5] if len(all_producers_product) > 5 else all_producers_product,
                    key="prod_producer_filter",
                )
            with filter_col2:
                selected_product_periods = st.multiselect(
                    "Filter by Period Start",
                    options=unique_periods_product,
                    default=unique_periods_product[-12:] if len(unique_periods_product) > 12 else unique_periods_product,
                    format_func=lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else '',
                    key="prod_period_filter",
                )
            st.markdown('</div>', unsafe_allow_html=True)

        if not selected_producers_prod:
            st.info("Select at least one producer.")
            return
        if not selected_product_periods:
            st.info("Select at least one period.")
            return

        # Filter data
        filtered_products = product_df[
            product_df["producerName"].isin(selected_producers_prod) &
            product_df["periodStart"].isin(selected_product_periods)
        ]

        # --- Producer-level trends by quantity ordered ---
        st.markdown('<p class="section-header">Unit Sales Trends by Producer</p>', unsafe_allow_html=True)
        producer_qty_trends = filtered_products.groupby(["periodStart", "producerName"]).agg(
            total_qty=("qty", "sum"),
            num_orders=("orderId", "nunique"),
            num_products=("productName", "nunique"),
        ).reset_index()
        producer_qty_trends["Period Label"] = producer_qty_trends["periodStart"].dt.strftime('%Y-%m-%d')

        fig_producer = px.line(
            producer_qty_trends,
            x="Period Label",
            y="total_qty",
            color="producerName",
            markers=True,
            template="plotly_dark" if dark else "plotly_white",
            labels={"Period Label": "Period", "total_qty": "Total Units Sold", "producerName": "Producer"},
            title="Total Units Ordered by Producer Over Time",
        )
        fig_producer.update_traces(line=dict(width=2.5), marker=dict(size=7))
        fig_producer.update_layout(
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            hovermode="x unified",
            margin=dict(l=0, r=0, t=30, b=0),
            height=400,
        )
        st.plotly_chart(fig_producer, use_container_width=True)

        # --- Producer summary table ---
        st.markdown('<p class="section-header">Producer Summary (Selected Periods)</p>', unsafe_allow_html=True)
        producer_summary = filtered_products.groupby("producerName").agg(
            products=("productName", "nunique"),
            total_units=("qty", "sum"),
            avg_units_per_order=("qty", "mean"),
            num_orders=("orderId", "nunique"),
        ).reset_index().round(2)
        producer_summary = producer_summary.sort_values("total_units", ascending=False)

        gb_prod = GridOptionsBuilder.from_dataframe(producer_summary)
        gb_prod.configure_default_column(resizable=True, sortable=True, filter=True)
        gb_prod.configure_pagination(paginationAutoPageSize=False, paginationPageSize=15)
        AgGrid(
            producer_summary,
            gridOptions=gb_prod.build(),
            update_mode=GridUpdateMode.NO_UPDATE,
            height=300,
            use_container_width=True,
        )

        # --- Product-level trends ---
        st.markdown('<p class="section-header">Top Products by Producer</p>', unsafe_allow_html=True)
        selected_producer_detail = st.selectbox(
            "Select a producer to see top products",
            options=sorted(selected_producers_prod),
            key="detail_producer_prod",
        )

        if selected_producer_detail:
            producer_products = filtered_products[filtered_products["producerName"] == selected_producer_detail]
            product_trends = producer_products.groupby(["periodStart", "productName"]).agg(
                total_qty=("qty", "sum"),
            ).reset_index()
            product_trends["Period Label"] = product_trends["periodStart"].dt.strftime('%Y-%m-%d')
            
            # Show top 5 products by total quantity
            top_products = producer_products.groupby("productName")["qty"].sum().nlargest(5).index.tolist()
            product_trends_top = product_trends[product_trends["productName"].isin(top_products)]

            fig_product = px.line(
                product_trends_top,
                x="Period Label",
                y="total_qty",
                color="productName",
                markers=True,
                template="plotly_dark" if dark else "plotly_white",
                labels={"Period Label": "Period", "total_qty": "Units Ordered"},
                title=f"Top 5 Products - {selected_producer_detail}",
            )
            fig_product.update_traces(line=dict(width=2.5), marker=dict(size=7))
            fig_product.update_layout(
                legend=dict(orientation="v", yanchor="top", y=0.99, xanchor="right", x=0.99),
                hovermode="x unified",
                margin=dict(l=0, r=0, t=30, b=0),
                height=400,
            )
            st.plotly_chart(fig_product, use_container_width=True)

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
        gb_avail = GridOptionsBuilder.from_dataframe(avail_summary)
        gb_avail.configure_default_column(resizable=True, sortable=True, filter=True)
        gb_avail.configure_pagination(paginationAutoPageSize=False, paginationPageSize=15)
        AgGrid(avail_summary, gridOptions=gb_avail.build(),
               update_mode=GridUpdateMode.NO_UPDATE, height=300, use_container_width=True)

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
                gb_prod_detail = GridOptionsBuilder.from_dataframe(prod_table)
                gb_prod_detail.configure_default_column(resizable=True, sortable=True, filter=True)
                gb_prod_detail.configure_pagination(paginationAutoPageSize=False, paginationPageSize=20)
                AgGrid(prod_table, gridOptions=gb_prod_detail.build(),
                       update_mode=GridUpdateMode.NO_UPDATE, height=350, use_container_width=True)


if __name__ == "__main__":
    main()
