# Delivered Fresh · Analytics Dashboard

Multi-tenant analytics dashboard for Local Food Marketplace (LFM) customers.

- **Azure-hosted** — Azure App Service (Linux) with centralized updates
- **Secure** — Microsoft Entra login via App Service Authentication
- **Multi-customer** — each customer's LFM API key stored in Azure Key Vault
- **Self-service onboarding** — customers enter their own API key on first login

## Architecture

```
User → Azure App Service (Easy Auth / Entra) → app.py
         │
         ├─ Azure SQL Database (users, customers metadata)
         ├─ Azure Key Vault (customer LFM API keys)
         └─ LFM Data API (orders, customers, availability)
```

## Project Layout

```
app.py                  # Azure entry point (auth → onboarding → dashboard)
app/
  auth/auth_helpers.py  # Read Easy Auth identity from headers
  db/models.py          # SQLAlchemy models (Customer, User)
  db/session.py         # DB engine + session factory
  db/init_db.py         # Schema creation + pilot data seeding
  services/
    keyvault.py         # Azure Key Vault client (+ dev fallback)
    lfm_client.py       # LFM API key validation
    customer_service.py # User/customer business logic
src/
  dashboard.py          # Streamlit analytics dashboard (6 views)
  data_loader.py        # LFM API data fetching
  order_analysis.py     # Order aggregation + RFM segmentation
  ml_experiments.py     # Churn risk + upgrade potential models
sql/
  001_create_customers.sql
  002_create_users.sql
```

## Local Development

### 1. Environment setup

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
copy .env.example .env
# Edit .env — set DEV_USER_* values and optionally LFM_API_KEY
```

### 3. Initialize the local database

```bash
# Create tables + seed a test customer:
python -m app.db.init_db "My Test Co" "dev@example.com" "00000000-0000-0000-0000-000000000001"
```

### 4. Run the app (Azure path with auth)

```bash
streamlit run app.py
```

This runs the full auth → onboarding → dashboard flow using SQLite and
file-based secrets locally.

### 5. Run the dashboard directly (no auth)

```bash
# Set LFM_API_KEY in .env first
streamlit run src/dashboard.py
```

## Azure Deployment

### Prerequisites

| Resource | Suggested Name | Notes |
|----------|---------------|-------|
| Resource Group | `rg-lfm-analytics-pilot` | Single region |
| App Service Plan | `asp-lfmanalytics-pilot` | Linux, B1 or B2 |
| Web App | `app-lfmanalytics-pilot` | Python 3.12, Linux |
| Azure SQL Server | `sql-lfmanalytics-pilot` | |
| Azure SQL Database | `lfm-analytics-appdb` | Basic/S0 tier |
| Key Vault | `kv-lfmanalytics-pilot` | |

### Step 1: Create Azure resources

Create the resources above in the Azure portal or CLI. Capture the
connection strings and URLs.

### Step 2: Configure App Service

**Application Settings (environment variables):**

| Setting | Value |
|---------|-------|
| `APP_ENV` | `production` |
| `AZURE_SQL_CONNECTION_STRING` | `mssql+pyodbc://user:pass@server.database.windows.net/dbname?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes` |
| `KEY_VAULT_URL` | `https://kv-lfmanalytics-pilot.vault.azure.net/` |
| `LFM_API_BASE_URL` | `https://data.localfoodmarketplace.com` |

**Startup command:**
```
python -m streamlit run app.py --server.port 8000 --server.address 0.0.0.0 --server.headless true --browser.gatherUsageStats false
```

### Step 3: Enable managed identity

Turn on **System-assigned managed identity** for the Web App, then grant it:
- **Key Vault**: `Key Vault Secrets User` role (read + write secrets)
- **Azure SQL**: create a contained database user for the managed identity

### Step 4: Enable App Service Authentication

- Add **Microsoft Entra** as an identity provider
- Set to **Require authentication**
- Users will sign in via Microsoft before reaching the app

### Step 5: Initialize the database

Run the SQL scripts in `sql/` against your Azure SQL database, or let
the app auto-create tables on first startup (SQLAlchemy handles this).

### Step 6: Seed pilot customers

For each pilot customer, insert a row into `customers` and link their
admin user(s):

```sql
INSERT INTO customers (name) VALUES ('Acme Farm Co-op');
-- Note the customer id returned

INSERT INTO users (entra_object_id, email, display_name, customer_id, role)
VALUES ('their-entra-object-id', 'admin@acme.com', 'Admin User', 1, 'admin');
```

When the user logs in, they'll be guided through API key setup automatically.

### Step 7: Deploy from GitHub

Connect the repo to App Service via **Deployment Center** or GitHub Actions.
The `main` branch is the local backup; deploy from `azure-deploy`.

## User Flow

1. User visits the app URL → signs in via Microsoft Entra
2. App resolves their identity → finds/creates user record in SQL
3. If no customer mapping → shows "Contact your admin" message
4. If customer has no API key → shows onboarding form to enter & validate key
5. API key saved to Key Vault → user redirected to dashboard
6. Dashboard loads data using the customer's API key from Key Vault

## API Endpoints Used

| Endpoint | Purpose |
|----------|---------|
| `/api/Orders` | Order data with line items |
| `/api/Customers` | Customer records with lifetime metrics |
| `/api/PriceLevel` | Available price levels (also used for API key validation) |
| `/api/Availability` | Product availability by price level |

Base URL: `https://data.localfoodmarketplace.com`
Swagger docs: `https://data.localfoodmarketplace.com/swagger/index.html`
