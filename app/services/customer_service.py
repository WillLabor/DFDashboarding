"""Business logic for user and customer account management."""

from __future__ import annotations

from datetime import datetime, UTC

from app.db.models import User, Customer


def get_or_create_user(session, identity: dict) -> User:
    """Find an existing user by Entra object ID, or create a new one."""
    user = session.query(User).filter_by(
        entra_object_id=identity["object_id"],
    ).first()

    if user is None:
        user = User(
            entra_object_id=identity["object_id"],
            email=identity["email"],
            display_name=identity.get("display_name", ""),
        )
        session.add(user)
        session.flush()
        return user

    # Update profile fields if they've changed in Entra
    changed = False
    if identity.get("email") and user.email != identity["email"]:
        user.email = identity["email"]
        changed = True
    if identity.get("display_name") and user.display_name != identity["display_name"]:
        user.display_name = identity["display_name"]
        changed = True
    if changed:
        user.updated_at = datetime.now(UTC)
        session.flush()

    return user


def get_customer_for_user(session, user: User) -> Customer | None:
    """Return the customer account linked to this user, or None."""
    if user.customer_id is None:
        return None
    return session.query(Customer).filter_by(id=user.customer_id).first()


def save_api_key_reference(session, customer: Customer, secret_name: str) -> None:
    """Update the customer's Key Vault secret reference in the database."""
    customer.key_vault_secret_name = secret_name
    customer.updated_at = datetime.now(UTC)
    session.flush()
