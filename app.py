"""Azure-hosted Streamlit entry point.

Handles authentication, customer resolution, API key onboarding,
then launches the existing analytics dashboard.

Run locally:   streamlit run app.py
Run on Azure:  configured via App Service startup command
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load .env for local development (no-op if file missing)
from dotenv import load_dotenv
load_dotenv()

import streamlit as st

from app.auth.auth_helpers import get_current_user
from app.db.models import Base, Customer
from app.db.session import get_engine, get_session
from app.services.customer_service import (
    get_or_create_user,
    get_customer_for_user,
    save_api_key_reference,
)
from app.services.lfm_client import validate_api_key

# Auto-create tables on startup (idempotent)
Base.metadata.create_all(get_engine())


# ── Auth resolution (cached in session_state) ────────────────────────────────

def _resolve_auth():
    """Authenticate the user and resolve their customer account.

    Returns (user_name, user_email, customer_id, customer_name, kv_secret).
    """
    if "_auth_resolved" in st.session_state:
        return (
            st.session_state["_auth_user_name"],
            st.session_state["_auth_user_email"],
            st.session_state["_auth_customer_id"],
            st.session_state["_auth_customer_name"],
            st.session_state["_auth_kv_secret"],
        )

    identity = get_current_user()
    if identity is None:
        return None, None, None, None, None

    with get_session() as session:
        user = get_or_create_user(session, identity)
        customer = get_customer_for_user(session, user)

        st.session_state["_auth_user_name"] = user.display_name or user.email
        st.session_state["_auth_user_email"] = user.email
        st.session_state["_auth_customer_id"] = customer.id if customer else None
        st.session_state["_auth_customer_name"] = customer.name if customer else None
        st.session_state["_auth_kv_secret"] = (
            customer.key_vault_secret_name if customer else None
        )
        st.session_state["_auth_resolved"] = True

    return (
        st.session_state["_auth_user_name"],
        st.session_state["_auth_user_email"],
        st.session_state["_auth_customer_id"],
        st.session_state["_auth_customer_name"],
        st.session_state["_auth_kv_secret"],
    )


# ── Onboarding page ──────────────────────────────────────────────────────────

def _show_onboarding(customer_id: int, customer_name: str):
    """Prompt the user to enter and validate their LFM API key."""
    st.title("🔑 API Key Setup")
    st.markdown(
        f"Welcome, **{customer_name}**! To get started, enter your "
        "Local Food Marketplace API key below."
    )

    api_key_input = st.text_input(
        "LFM API Key",
        type="password",
        help="You can find this in your LFM account settings.",
    )

    if st.button("Validate & Save", type="primary"):
        if not api_key_input.strip():
            st.error("Please enter an API key.")
            return

        with st.spinner("Validating API key with LFM…"):
            if not validate_api_key(api_key_input.strip()):
                st.error(
                    "Invalid API key — the LFM API did not accept it. "
                    "Please check the key and try again."
                )
                return

        # Save to Key Vault and update customer record
        secret_name = f"lfm-apikey-{customer_id}"
        try:
            from app.services.keyvault import set_secret
            set_secret(secret_name, api_key_input.strip())

            with get_session() as session:
                customer = session.query(Customer).filter_by(id=customer_id).first()
                save_api_key_reference(session, customer, secret_name)

            # Clear auth cache so the next rerun picks up the new secret name
            for key in list(st.session_state.keys()):
                if key.startswith("_auth_"):
                    del st.session_state[key]

            st.success("API key saved successfully! Redirecting to dashboard…")
            st.rerun()
        except Exception as exc:
            st.error(f"Failed to save API key: {exc}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="Delivered Fresh · Analytics",
        layout="wide",
        page_icon="🌿",
    )

    user_name, user_email, customer_id, customer_name, kv_secret = _resolve_auth()

    # ── Not authenticated ────────────────────────────────────────────────
    if user_name is None:
        # On Azure, redirect straight to the Easy Auth login endpoint
        hostname = os.environ.get("WEBSITE_HOSTNAME", "")
        if hostname:
            login_url = f"https://{hostname}/.auth/login/aad?post_login_redirect_uri=/"
            st.markdown(
                f'<meta http-equiv="refresh" content="0;url={login_url}">',
                unsafe_allow_html=True,
            )
            st.title("🔒 Redirecting to sign-in…")
            st.markdown(
                f"If you are not redirected automatically, [click here]({login_url})."
            )
        else:
            st.title("🔒 Authentication Required")
            if os.environ.get("APP_ENV") == "development":
                st.warning(
                    "**Local dev mode:** Set `DEV_USER_OBJECT_ID`, `DEV_USER_EMAIL`, "
                    "and `DEV_USER_NAME` in your `.env` file to simulate a signed-in user."
                )
            else:
                st.info("Please sign in with your Microsoft account.")
        st.stop()

    # ── No customer mapping ──────────────────────────────────────────────
    if customer_id is None:
        st.title("🚫 Account Not Linked")
        st.warning(
            f"Your account (**{user_email}**) is not linked to a customer. "
            "Please contact your administrator to be added."
        )
        st.stop()

    # ── API key not configured — show onboarding ─────────────────────────
    if not kv_secret:
        _show_onboarding(customer_id, customer_name)
        return

    # ── Load API key from Key Vault (cached in session_state) ────────────
    if "_api_key" not in st.session_state:
        try:
            from app.services.keyvault import get_secret
            st.session_state["_api_key"] = get_secret(kv_secret)
        except Exception as exc:
            st.error(f"Failed to load API key from Key Vault: {exc}")
            st.stop()

    api_key = st.session_state["_api_key"]

    # ── Launch dashboard ─────────────────────────────────────────────────
    from src.dashboard import main as run_dashboard

    run_dashboard(api_key=api_key, user_display_name=user_name)


if __name__ == "__main__":
    main()
