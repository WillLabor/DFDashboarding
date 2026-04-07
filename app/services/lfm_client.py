"""Lightweight LFM API client for validating API keys."""

from __future__ import annotations

import os

import requests

DEFAULT_BASE_URL = "https://data.localfoodmarketplace.com"


def validate_api_key(api_key: str, base_url: str | None = None) -> bool:
    """Validate an LFM API key by fetching price levels (lightweight call).

    Returns True if the API returns a successful response.
    """
    base = base_url or os.environ.get("LFM_API_BASE_URL", DEFAULT_BASE_URL)
    try:
        resp = requests.get(
            f"{base.rstrip('/')}/api/PriceLevel",
            headers={"x-api-key": api_key},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False
