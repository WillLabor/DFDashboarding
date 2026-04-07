"""Read signed-in user identity from Azure App Service Easy Auth headers.

In production (Azure App Service with Authentication enabled), user identity
is injected via HTTP headers before the request reaches the application.

In local development, identity is simulated via DEV_USER_* environment variables.
"""

from __future__ import annotations

import base64
import json
import os

import streamlit as st


def get_current_user() -> dict | None:
    """Return the signed-in user's identity, or None if not authenticated.

    Returns a dict with keys: object_id, email, display_name.
    """
    # --- 1. Try Azure Easy Auth headers ---
    headers = getattr(st.context, "headers", {})

    # X-Ms-Client-Principal is a base64-encoded JSON blob with all claims
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

    # --- 2. Local development fallback ---
    if os.environ.get("APP_ENV") == "development":
        dev_oid = os.environ.get("DEV_USER_OBJECT_ID")
        if dev_oid:
            return {
                "object_id": dev_oid,
                "email": os.environ.get("DEV_USER_EMAIL", "dev@localhost"),
                "display_name": os.environ.get("DEV_USER_NAME", "Dev User"),
            }

    return None
