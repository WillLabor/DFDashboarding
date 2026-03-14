"""Simple utilities to fetch API data and turn it into a pandas DataFrame."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)


def make_api_headers(
    api_key: Optional[str] = None,
    api_key_header: str = "x-api-key",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Build headers for API requests, including API key authentication."""
    result: Dict[str, str] = {} if headers is None else dict(headers)
    if api_key:
        result[api_key_header] = api_key
    return result


def fetch_json(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 30,
    api_key: Optional[str] = None,
    api_key_header: str = "x-api-key",
) -> Any:
    """Fetch a JSON response from an API endpoint."""
    headers = make_api_headers(api_key=api_key, api_key_header=api_key_header, headers=headers)
    resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def json_to_df(
    data: Any,
    record_path: Optional[str] = None,
    meta: Optional[list] = None,
) -> pd.DataFrame:
    """Normalize JSON data into a flat DataFrame."""
    return pd.json_normalize(data, record_path=record_path, meta=meta, errors="ignore")


def fetch_api_to_df(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    record_path: Optional[str] = None,
    meta: Optional[list] = None,
    timeout: int = 30,
    api_key: Optional[str] = None,
    api_key_header: str = "x-api-key",
) -> pd.DataFrame:
    """Fetch data from an API and return a pandas DataFrame."""
    data = fetch_json(
        url,
        params=params,
        headers=headers,
        timeout=timeout,
        api_key=api_key,
        api_key_header=api_key_header,
    )
    df = json_to_df(data, record_path=record_path, meta=meta)
    return df


def save_df_csv(df: pd.DataFrame, path: str, index: bool = False) -> None:
    """Save a DataFrame to a CSV file."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=index)
    logger.info("Saved CSV to %s", out_path)
