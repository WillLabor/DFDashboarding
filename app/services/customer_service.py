"""Business logic for user and customer account management."""

from __future__ import annotations

from datetime import datetime, UTC

from app.db.models import User, Customer, PendingInvite


def get_or_create_user(session, identity: dict) -> User:
    """Find an existing user by Entra object ID, or create a new one.

    If the user's email matches a pending invite, automatically link them
    to that customer on first sign-in.
    """
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

        # Check for a pending invite by email (case-insensitive)
        _try_claim_invite(session, user)
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

    # If still unlinked, try to claim an invite (admin may have added one
    # after the user's first sign-in)
    if user.customer_id is None:
        _try_claim_invite(session, user)

    return user


def _try_claim_invite(session, user: User) -> None:
    """If a PendingInvite exists for this email, link the user and delete it."""
    invite = (
        session.query(PendingInvite)
        .filter(PendingInvite.email.ilike(user.email))
        .first()
    )
    if invite:
        user.customer_id = invite.customer_id
        user.role = invite.role
        user.updated_at = datetime.now(UTC)
        session.delete(invite)
        session.flush()


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


def create_customer_with_admin(session, org_name: str, user: User) -> Customer:
    """Create a new customer (organization) and set the user as its admin."""
    customer = Customer(name=org_name.strip())
    session.add(customer)
    session.flush()

    user.customer_id = customer.id
    user.role = "admin"
    user.updated_at = datetime.now(UTC)
    session.flush()
    return customer


def get_team_members(session, customer_id: int) -> list[User]:
    """Return all users linked to a customer."""
    return session.query(User).filter_by(customer_id=customer_id).all()


def get_pending_invites(session, customer_id: int) -> list[PendingInvite]:
    """Return all pending invites for a customer."""
    return (
        session.query(PendingInvite)
        .filter_by(customer_id=customer_id)
        .all()
    )


def create_invite(session, customer_id: int, email: str, role: str,
                   invited_by: str) -> PendingInvite | None:
    """Create a pending invite. Returns None if email already has access."""
    email_lower = email.strip().lower()

    # Already a user with this email linked to this customer?
    existing = (
        session.query(User)
        .filter(User.email.ilike(email_lower), User.customer_id == customer_id)
        .first()
    )
    if existing:
        return None

    # Already an unlinked user? Link them directly
    unlinked = (
        session.query(User)
        .filter(User.email.ilike(email_lower), User.customer_id.is_(None))
        .first()
    )
    if unlinked:
        unlinked.customer_id = customer_id
        unlinked.role = role
        unlinked.updated_at = datetime.now(UTC)
        session.flush()
        return None  # No pending invite needed — linked immediately

    # Already a pending invite for this email + customer?
    dup = (
        session.query(PendingInvite)
        .filter(PendingInvite.email.ilike(email_lower),
                PendingInvite.customer_id == customer_id)
        .first()
    )
    if dup:
        return dup  # Return existing invite

    invite = PendingInvite(
        email=email_lower,
        customer_id=customer_id,
        role=role,
        invited_by=invited_by,
    )
    session.add(invite)
    session.flush()
    return invite


def delete_invite(session, invite_id: int, customer_id: int) -> bool:
    """Delete a pending invite. Returns True if found and deleted."""
    invite = (
        session.query(PendingInvite)
        .filter_by(id=invite_id, customer_id=customer_id)
        .first()
    )
    if invite:
        session.delete(invite)
        session.flush()
        return True
    return False


def update_user_role(session, user_id: int, customer_id: int,
                     new_role: str) -> bool:
    """Update a user's role. Returns True if successful."""
    user = (
        session.query(User)
        .filter_by(id=user_id, customer_id=customer_id)
        .first()
    )
    if user:
        user.role = new_role
        user.updated_at = datetime.now(UTC)
        session.flush()
        return True
    return False


def remove_user_from_customer(session, user_id: int,
                               customer_id: int) -> bool:
    """Unlink a user from a customer. Returns True if successful."""
    user = (
        session.query(User)
        .filter_by(id=user_id, customer_id=customer_id)
        .first()
    )
    if user:
        user.customer_id = None
        user.role = "viewer"
        user.updated_at = datetime.now(UTC)
        session.flush()
        return True
    return False
