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

from app.auth.auth_helpers import get_current_user, get_login_url
from app.db.models import Base, Customer, User
from app.db.session import get_engine, get_session
from app.services.customer_service import (
    get_or_create_user,
    get_customer_for_user,
    save_api_key_reference,
    get_team_members,
    get_pending_invites,
    create_invite,
    delete_invite,
    update_user_role,
    remove_user_from_customer,
)
from app.services.lfm_client import validate_api_key

# Auto-create tables on startup (idempotent)
Base.metadata.create_all(get_engine())

# ── Seed pilot customer (idempotent, runs once) ──────────────────────────────
def _seed_pilot():
    with get_session() as session:
        cust = session.query(Customer).filter_by(name="Delivered Fresh").first()
        if not cust:
            cust = Customer(name="Delivered Fresh")
            session.add(cust)
            session.flush()
        # Ensure pilot user is linked
        from app.db.models import User
        u = session.query(User).filter_by(
            entra_object_id="7e3c6606-aaa6-4c7f-9c5a-f916216f014c"
        ).first()
        if u and u.customer_id != cust.id:
            u.customer_id = cust.id
        elif not u:
            session.add(User(
                entra_object_id="7e3c6606-aaa6-4c7f-9c5a-f916216f014c",
                email="william.labor.jr@outlook.com",
                display_name="William Labor",
                customer_id=cust.id,
                role="admin",
            ))

_seed_pilot()


# ── Auth resolution (cached in session_state) ────────────────────────────────

def _resolve_auth():
    """Authenticate the user and resolve their customer account.

    Returns (user_name, user_email, customer_id, customer_name, kv_secret,
             user_role, user_id).
    """
    if "_auth_resolved" in st.session_state:
        return (
            st.session_state["_auth_user_name"],
            st.session_state["_auth_user_email"],
            st.session_state["_auth_customer_id"],
            st.session_state["_auth_customer_name"],
            st.session_state["_auth_kv_secret"],
            st.session_state["_auth_user_role"],
            st.session_state["_auth_user_id"],
        )

    identity = get_current_user()
    if identity is None:
        return None, None, None, None, None, None, None

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
        st.session_state["_auth_user_role"] = user.role
        st.session_state["_auth_user_id"] = user.id
        st.session_state["_auth_resolved"] = True

    return (
        st.session_state["_auth_user_name"],
        st.session_state["_auth_user_email"],
        st.session_state["_auth_customer_id"],
        st.session_state["_auth_customer_name"],
        st.session_state["_auth_kv_secret"],
        st.session_state["_auth_user_role"],
        st.session_state["_auth_user_id"],
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
            _clear_auth_cache()

            st.success("API key saved successfully! Redirecting to dashboard…")
            st.rerun()
        except Exception as exc:
            st.error(f"Failed to save API key: {exc}")


# ── Admin Panel ───────────────────────────────────────────────────────────────

def _show_admin_panel(customer_id: int, customer_name: str, current_user_email: str):
    """Admin panel for managing team members and invitations."""
    import pandas as pd

    st.title("👥 Team Management")
    st.markdown(f"Manage users for **{customer_name}**.")

    tab_members, tab_invite = st.tabs(["Current Members", "Invite New User"])

    # ── Current Members tab ──────────────────────────────────────────────
    with tab_members:
        with get_session() as session:
            members = get_team_members(session, customer_id)
            if members:
                rows = []
                for m in members:
                    rows.append({
                        "Name": m.display_name or "—",
                        "Email": m.email,
                        "Role": m.role,
                        "Joined": m.created_at.strftime("%Y-%m-%d") if m.created_at else "—",
                        "_id": m.id,
                        "_is_self": m.email.lower() == current_user_email.lower(),
                    })
                df = pd.DataFrame(rows)
                st.dataframe(
                    df[["Name", "Email", "Role", "Joined"]],
                    use_container_width=True,
                    hide_index=True,
                )

                # Role changes / removal (skip self)
                st.markdown("---")
                st.subheader("Edit Member")
                editable = [r for r in rows if not r["_is_self"]]
                if editable:
                    edit_options = {f"{r['Name']} ({r['Email']})": r for r in editable}
                    selected_label = st.selectbox(
                        "Select a member",
                        options=list(edit_options.keys()),
                        key="edit_member_select",
                    )
                    selected = edit_options[selected_label]
                    col1, col2 = st.columns(2)
                    with col1:
                        new_role = st.selectbox(
                            "Role",
                            options=["admin", "viewer"],
                            index=0 if selected["Role"] == "admin" else 1,
                            key="edit_role",
                        )
                        if st.button("Update Role", key="btn_update_role"):
                            with get_session() as s:
                                update_user_role(s, selected["_id"], customer_id, new_role)
                            _clear_auth_cache()
                            st.success(f"Updated {selected['Email']} to **{new_role}**.")
                            st.rerun()
                    with col2:
                        st.write("")  # spacing
                        st.write("")
                        if st.button("🗑 Remove from team", key="btn_remove_member", type="secondary"):
                            with get_session() as s:
                                remove_user_from_customer(s, selected["_id"], customer_id)
                            st.success(f"Removed {selected['Email']}.")
                            st.rerun()
                else:
                    st.info("You are the only member — invite others below.")

            # Pending invites
            invites = get_pending_invites(session, customer_id)
            if invites:
                st.markdown("---")
                st.subheader("Pending Invitations")
                for inv in invites:
                    col_email, col_role, col_del = st.columns([3, 1, 1])
                    col_email.write(inv.email)
                    col_role.write(inv.role)
                    if col_del.button("Cancel", key=f"cancel_inv_{inv.id}"):
                        with get_session() as s:
                            delete_invite(s, inv.id, customer_id)
                        st.rerun()

    # ── Invite New User tab ──────────────────────────────────────────────
    with tab_invite:
        st.markdown(
            "Enter the email address of the person you want to invite. "
            "When they sign in with Microsoft, they'll be automatically "
            "linked to your team."
        )
        st.info(
            "💡 **Gmail / non-Outlook users:** You'll need to invite them "
            "as external users in the "
            "[Azure Portal → Entra ID → Users → Invite external user]"
            "(https://portal.azure.com/#view/Microsoft_AAD_UsersAndTenants/UserManagementMenuBlade/~/AllUsers) "
            "first. They'll get an email to accept, then they can sign in here."
        )

        invite_email = st.text_input("Email address", key="invite_email_input")
        invite_role = st.selectbox("Role", ["viewer", "admin"], key="invite_role_input")

        if st.button("Send Invitation", type="primary", key="btn_invite"):
            if not invite_email or "@" not in invite_email:
                st.error("Please enter a valid email address.")
            else:
                with get_session() as session:
                    result = create_invite(
                        session, customer_id, invite_email, invite_role,
                        invited_by=current_user_email,
                    )
                if result is None:
                    st.success(
                        f"**{invite_email}** already has access or was just linked!"
                    )
                else:
                    st.success(
                        f"Invitation created for **{invite_email}**. "
                        f"They'll be auto-linked when they sign in."
                    )
                st.rerun()


def _clear_auth_cache():
    """Clear cached auth state so next rerun re-resolves."""
    for key in list(st.session_state.keys()):
        if key.startswith("_auth_"):
            del st.session_state[key]


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="Delivered Fresh · Analytics",
        layout="wide",
        page_icon="🌿",
    )

    user_name, user_email, customer_id, customer_name, kv_secret, user_role, user_id = _resolve_auth()

    # ── Not authenticated ────────────────────────────────────────────────
    if user_name is None:
        st.title("🔒 Sign In Required")
        login_url = get_login_url()
        st.markdown(
            f'<a href="{login_url}" target="_self" style="display:inline-block;'
            f'padding:0.6rem 1.2rem;background:#0078d4;color:white;'
            f'border-radius:6px;text-decoration:none;font-weight:600;">'
            f'Sign in with Microsoft</a>',
            unsafe_allow_html=True,
        )
        if os.environ.get("APP_ENV") == "development":
            st.warning(
                "**Local dev mode:** Set `DEV_USER_OBJECT_ID`, `DEV_USER_EMAIL`, "
                "and `DEV_USER_NAME` in your `.env` file to simulate a signed-in user."
            )
        st.stop()

    # ── No customer mapping ──────────────────────────────────────────────
    if customer_id is None:
        st.title("⏳ Account Pending")
        st.warning(
            f"Your account (**{user_email}**) is not yet linked to a team.\n\n"
            "Your administrator needs to invite you from their **Team Management** page. "
            "Once they add your email, simply refresh this page and you'll be connected automatically."
        )
        # Let them sign out and try a different account
        if st.button("Sign out"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
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

    # ── Sidebar navigation ───────────────────────────────────────────────
    with st.sidebar:
        st.markdown(f"**{customer_name}**")
        st.caption(f"Signed in as {user_name}")
        pages = ["📊 Dashboard"]
        if user_role == "admin":
            pages.append("👥 Team Management")
        pages.append("🚪 Sign Out")
        nav = st.radio("Navigate", pages, label_visibility="collapsed", key="nav")

    if nav == "🚪 Sign Out":
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

    if nav == "👥 Team Management":
        _show_admin_panel(customer_id, customer_name, user_email)
        return

    # ── Launch dashboard ─────────────────────────────────────────────────
    from src.dashboard import main as run_dashboard

    run_dashboard(api_key=api_key, user_display_name=user_name)


if __name__ == "__main__":
    main()
