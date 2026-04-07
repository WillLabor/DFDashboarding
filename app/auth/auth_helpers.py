"""Read signed-in user identity from Azure App Service Easy Auth.

Uses multiple strategies:
1. Easy Auth headers (X-Ms-Client-Principal) — works on initial HTTP requests
2. /.auth/me endpoint — reliable fallback for WebSocket-based frameworks like Streamlit
3. DEV_USER_* env vars — local development

In local development, identity is simulated via DEV_USER_* environment variables.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.request

import streamlit as st


def _parse_principal_header(headers: dict) -> dict | None:
    """Extract user identity from the X-Ms-Client-Principal header."""
    principal = headers.get("X-Ms-Client-Principal")
    if principal:
        try:
            decoded = base64.b64decode(principal)
            payload = json.loads(decoded)
            claims = {c["typ"]: c["val"] for c in payload.get("claims", [])}

            object_id = claims.get(
                "http://schemas.microsoft.com/identity/claims/objectidentifier",
                claims.get("oid", ""),
            )
            email = claims.get(
                "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
                claims.get("preferred_username", claims.get("email", "")),
            )
            display_name = claims.get("name", email.split("@")[0] if email else "")

            if object_id:
                return {
                    "object_id": object_id,
                    "email": email,
                    "display_name": display_name,
                }
        except Exception:
            pass

    # Fallback: individual Easy Auth headers
    object_id = headers.get("X-Ms-Client-Principal-Id")
    if object_id:
        return {
            "object_id": object_id,
            "email": headers.get("X-Ms-Client-Principal-Name", ""),
            "display_name": headers.get("X-Ms-Client-Principal-Name", ""),
        }
    return None


def _call_auth_me() -> dict | None:
    """Call the /.auth/me endpoint from within the container (localhost).

    Easy Auth runs as a sidecar on the same host and injects an auth session
    cookie.  We call /.auth/me on the public hostname using the cookie from
    the current Streamlit request to retrieve claims reliably.
    """
    try:
        cookies = getattr(st.context, "cookies", {})
        # AppServiceAuthSession is the cookie set by Easy Auth after login
        auth_cookie = cookies.get("AppServiceAuthSession")
        if not auth_cookie:
            return None

        hostname = os.environ.get("WEBSITE_HOSTNAME", "")
        if not hostname:
            return None

        url = f"https://{hostname}/.auth/me"
        req = urllib.request.Request(url)
        req.add_header("Cookie", f"AppServiceAuthSession={auth_cookie}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())

        if not data or not isinstance(data, list) or len(data) == 0:
            return None

        user_claims = data[0].get("user_claims", [])
        claims = {c["typ"]: c["val"] for c in user_claims}

        object_id = claims.get(
            "http://schemas.microsoft.com/identity/claims/objectidentifier",
            claims.get("oid", ""),
        )
        email = claims.get(
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
            claims.get("preferred_username", claims.get("email", "")),
        )
        display_name = claims.get("name", email.split("@")[0] if email else "")

        if object_id:
            return {
                "object_id": object_id,
                "email": email,
                "display_name": display_name,
            }
    except Exception:
        pass
    return None


def get_current_user() -> dict | None:
    """Return the signed-in user's identity, or None if not authenticated.

    Returns a dict with keys: object_id, email, display_name.
    """
    # --- 1. Try Azure Easy Auth headers ---
    headers = getattr(st.context, "headers", {})
    result = _parse_principal_header(headers)
    if result:
        return result

    # --- 2. Call /.auth/me using the session cookie ---
    result = _call_auth_me()
    if result:
        return result

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
