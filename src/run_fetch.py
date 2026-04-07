"""Small CLI to fetch an API endpoint and save it as CSV.

Example:
    python src/run_fetch.py \
      --base-url https://data.localfoodmarketplace.com \
      --url /api/products \
      --api-key 158d2724-fa51-4f7d-be0e-682e4e2860dc \
      --output data/output.csv
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from urllib.parse import urljoin

from src.data_loader import fetch_api_to_df, save_df_csv


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Fetch an API endpoint and save as CSV")
    parser.add_argument("--base-url", default=None, help="Optional base URL (used when URL is relative)")
    parser.add_argument("--url", required=True, help="API URL to fetch (absolute or relative)")
    parser.add_argument("--api-key", default=None, help="API key to include in request headers")
    parser.add_argument(
        "--api-key-header",
        default="x-api-key",
        help="Header name to send the API key in (default: x-api-key)",
    )
    parser.add_argument("--output", required=True, help="Output CSV file path")
    parser.add_argument("--record-path", default=None, help="Optional record_path for nested JSON")
    parser.add_argument("--meta", nargs="*", default=None, help="Optional meta fields for nested JSON")
    parser.add_argument(
        "--last-days",
        type=int,
        default=None,
        help="If provided, fetch data starting from this many days ago until today (UTC).",
    )
    parser.add_argument(
        "--start-date",
        default=None,
        help="Optional ISO date (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS) to use as the start date.",
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="Optional ISO date (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS) to use as the end date.",
    )
    return parser.parse_args(argv)


def _get_iso_dates(args):
    # Prefer explicit dates, otherwise use last-days
    if args.start_date or args.end_date:
        return args.start_date, args.end_date

    if args.last_days is None:
        return None, None

    now = datetime.utcnow()
    start = now - timedelta(days=args.last_days)
    return start.isoformat(), now.isoformat()


def main(argv=None):
    args = parse_args(argv)

    url = args.url
    if args.base_url and not args.url.lower().startswith("http"):
        url = urljoin(args.base_url, args.url)

    start_date, end_date = _get_iso_dates(args)
    params = {}
    if start_date:
        params["startDate"] = start_date
    if end_date:
        params["endDate"] = end_date

    df = fetch_api_to_df(
        url,
        params=params or None,
        record_path=args.record_path,
        meta=args.meta,
        api_key=args.api_key,
        api_key_header=args.api_key_header,
    )

    save_df_csv(df, args.output)


if __name__ == "__main__":
    main()
