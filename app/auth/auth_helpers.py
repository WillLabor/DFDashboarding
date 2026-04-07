"""Direct OAuth 2.0 authentication with Microsoft Entra ID.

Easy Auth is incompatible with Streamlit's WebSocket architecture, so we handle
the OAuth authorization-code flow in Python:

1. Build a login URL pointing to Microsoft's authorize endpoint.
2. After sign-in, Microsoft redirects back with ?code=... in the URL.
3. We exchange the code for tokens server-to-server, then decode the ID token
   to extract user identity claims.

In local development, identity is simulated via DEV_USER_* environment variables.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.parse
import urllib.request

import streamlit as st

# ── Entra app registration constants ─────────────────────────────────────────
_TENANT_ID = "709dbb73-740c-4780-a412-181662fcce9f"
_CLIENT_ID = "8e73070c-b244-42d8-ae65-6337a1488421"
_AUTHORITY = f"https://login.microsoftonline.com/{_TENANT_ID}"
_SCOPES = "openid profile email"


def _get_redirect_uri() -> str:
    """Build the redirect URI based on the current environment."""
    hostname = os.environ.get("WEBSITE_HOSTNAME", "")
    if hostname:
        return f"https://{hostname}/"
    return "http://localhost:8501/"


def get_login_url() -> str:
    """Return the Microsoft Entra login URL for the authorization-code flow."""
    params = {
        "client_id": _CLIENT_ID,
        "response_type": "code",
        "redirect_uri": _get_redirect_uri(),
        "scope": _SCOPES,
        "response_mode": "query",
    }
    return f"{_AUTHORITY}/oauth2/v2.0/authorize?" + urllib.parse.urlencode(params)


def _exchange_code(code: str) -> dict | None:
    """Exchange an authorization code for user identity claims."""
    client_secret = os.environ.get("ENTRA_CLIENT_SECRET", "")
    data = urllib.parse.urlencode({
        "client_id": _CLIENT_ID,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": _get_redirect_uri(),
        "grant_type": "authorization_code",
        "scope": _SCOPES,
    }).encode()

    req = urllib.request.Request(
        f"{_AUTHORITY}/oauth2/v2.0/token",
        data=data,
        method="POST",
    )
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
    except Exception:
        return None

    id_token = result.get("id_token", "")
    if not id_token:
        return None

    # Decode JWT payload — safe because we received it directly from
    # Microsoft's token endpoint over HTTPS with our client secret.
    try:
        payload_b64 = id_token.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return None

    object_id = claims.get("oid", "")
    email = claims.get("preferred_username", claims.get("email", ""))
    display_name = claims.get("name", email.split("@")[0] if email else "")

    if object_id:
        return {
            "object_id": object_id,
            "email": email,
            "display_name": display_name,
        }
    return None


def get_current_user() -> dict | None:
    """Return the signed-in user's identity, or None if not authenticated.

    Returns a dict with keys: object_id, email, display_name.
    """
    # --- 1. Cached in session state ---
    if "_auth_user" in st.session_state:
        return st.session_state["_auth_user"]

    # --- 2. Authorization code in URL (redirect from Microsoft) ---
    code = st.query_params.get("code")
    if code:
        user = _exchange_code(code)
        if user:
            st.session_state["_auth_user"] = user
            st.query_params.clear()
            st.rerun()
        # Code exchange failed — clear params and fall through
        st.query_params.clear()

    # --- 3. Local development fallback ---
    if os.environ.get("APP_ENV") == "development":
        dev_oid = os.environ.get("DEV_USER_OBJECT_ID")
        if dev_oid:
            return {
                "object_id": dev_oid,
                "email": os.environ.get("DEV_USER_EMAIL", "dev@localhost"),
                "display_name": os.environ.get("DEV_USER_NAME", "Dev User"),
            }

    return None
