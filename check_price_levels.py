"""
One-time script: discover your price levels then test Availability.
Uses only 2 API calls total - safe within the 10-calls/10-min limit.

Run with:
    python check_price_levels.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.data_loader import fetch_price_levels, fetch_availability_to_df

BASE_URL = "https://data.localfoodmarketplace.com"
API_KEY  = "158d2724-fa51-4f7d-be0e-682e4e2860dc"   # same key as dashboard

# ── Step 1: fetch price levels ────────────────────────────────────────────────
print("Fetching price levels from /api/PriceLevel …")
pl_df = fetch_price_levels(base_url=BASE_URL, api_key=API_KEY)

if pl_df.empty:
    print("  ⚠  No price levels returned. Check your API key / account access.")
    sys.exit(1)

print(f"\n  Found {len(pl_df)} price level(s):\n")
print(pl_df.to_string(index=False))

# ── Step 2: try availability for each price level (capped at 3 to save calls) ─
print("\nTesting /api/Availability for each price level …")
for _, row in pl_df.head(3).iterrows():
    pl_id   = int(row["id"])
    pl_name = row.get("name", pl_id)
    is_def  = row.get("default", False)
    label   = f"{pl_name} (id={pl_id})" + (" [DEFAULT]" if is_def else "")

    avail = fetch_availability_to_df(base_url=BASE_URL, api_key=API_KEY, price_level_id=pl_id)
    print(f"  {label}: {len(avail)} rows")
    if not avail.empty:
        print(f"    Columns: {list(avail.columns)}")
        print(f"    First row sample: {avail.iloc[0].to_dict()}\n")
