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

warnings.filterwarnings("ignore", category=DeprecationWarning)

# Ensure the workspace root is on sys.path so `import src.*` works when running
# the dashboard directly (e.g., `streamlit run src/dashboard.py`).
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data_loader import fetch_api_to_df
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

    df = st.session_state.df

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

    else:
        csv_file = st.sidebar.file_uploader("Upload a CSV file", type=["csv"])
        if csv_file is not None:
            df = pd.read_csv(csv_file)
            st.session_state.df = df  # Persist in session state

    if df is None:
        st.info("Provide a data source above (API or CSV upload).")
        return

    # Get selected date range for filtering
    selected_start = getattr(st.session_state, 'selected_start', None)
    selected_end = getattr(st.session_state, 'selected_end', None)

    st.sidebar.write(f"Rows: {df.shape[0]}, Columns: {df.shape[1]}")

    view = st.sidebar.selectbox("View", ["Preview", "Order value analysis"], index=1)

    if view == "Order value analysis":
        # Add status filter if orderStatus column exists
        status_options = ["All"]
        if "orderStatus" in df.columns:
            unique_statuses = sorted(df["orderStatus"].dropna().unique())
            status_options.extend(unique_statuses)
        complete_index = status_options.index("COMPLETE") if "COMPLETE" in status_options else 0
        selected_status = st.sidebar.selectbox("Order Status Filter", status_options, index=complete_index)

    if view == "Preview":
        st.write("### Data Preview")
        st.dataframe(df)

        if st.sidebar.checkbox("Show summary statistics"):
            st.write("### Summary statistics")
            st.write(df.describe(include="all"))

        if st.sidebar.checkbox("Show data types"):
            st.write("### Data types")
            st.write(df.dtypes)

    else:
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
        from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

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


if __name__ == "__main__":
    main()
