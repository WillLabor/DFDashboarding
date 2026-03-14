# API Python Program

A starter Python workspace for:

- Fetching data from APIs (JSON → pandas DataFrame)
- Building simple dashboards (Streamlit)
- Running ML experiments and exporting CSV output for other AI tools

## Getting Started

1. Create a Python environment (recommended):
   ```bash
   python -m venv .venv
   .\.venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the dashboard (example):
   ```bash
   streamlit run src/dashboard.py
   ```

4. Explore the notebooks in `notebooks/` for ML experiments.

## Project Layout

- `src/` - core Python modules (data loading, dashboard, ML experiments)
- `notebooks/` - notebooks for exploration and experiments
- `data/` - (optional) place to store CSV extracts

## Workflow

1. Fetch API data and save to CSV (example using Local Food Marketplace API):
   ```bash
   python src/run_fetch.py \
     --base-url https://data-dev.localfoodmarketplace.com \
     --url /api/Orders \
     --api-key 158d2724-fa51-4f7d-be0e-682e4e2860dc \
     --last-days 90 \
     --output data/orders_last_90_days.csv
   ```

   - Use the Swagger docs to find available endpoints: https://data-dev.localfoodmarketplace.com/swagger/index.html
   - For date filters, you can also pass `--start-date` and `--end-date` in ISO format.

2. Open the dashboard to explore the exported CSV:
   ```bash
   streamlit run src/dashboard.py
   ```

3. Run ML experiments:
   ```bash
   python src/ml_experiments.py --input-csv data/output.csv --target <target_column>
   ```

4. Optionally open `notebooks/` for interactive exploration.
