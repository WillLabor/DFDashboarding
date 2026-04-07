"""Initialize the database schema and optionally seed pilot data.

Usage:
    # Create tables only:
    python -m app.db.init_db

    # Create tables + seed a pilot customer with an admin user:
    python -m app.db.init_db "Acme Farm Co-op" "admin@acme.com" "00000000-0000-0000-0000-000000000001"
"""

from __future__ import annotations

import os
import sys

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.db.models import Base, Customer, User
from app.db.session import get_engine, get_session


def init_schema():
    """Create all tables if they don't already exist."""
    engine = get_engine()
    Base.metadata.create_all(engine)
    print("Database schema created / verified.")


def seed_pilot_customer(name: str, admin_email: str, admin_object_id: str):
    """Create a customer and link an admin user to it (idempotent)."""
    with get_session() as session:
        customer = session.query(Customer).filter_by(name=name).first()
        if not customer:
            customer = Customer(name=name)
            session.add(customer)
            session.flush()
            print(f"Created customer: {name} (id={customer.id})")
        else:
            print(f"Customer already exists: {name} (id={customer.id})")

        user = session.query(User).filter_by(entra_object_id=admin_object_id).first()
        if not user:
            user = User(
                entra_object_id=admin_object_id,
                email=admin_email,
                display_name=admin_email.split("@")[0],
                customer_id=customer.id,
                role="admin",
            )
            session.add(user)
            print(f"Created admin user: {admin_email} -> customer '{name}'")
        else:
            if user.customer_id != customer.id:
                user.customer_id = customer.id
                print(f"Linked user {admin_email} -> customer '{name}'")
            else:
                print(f"User already linked: {admin_email} -> customer '{name}'")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    init_schema()

    if len(sys.argv) >= 4:
        seed_pilot_customer(
            name=sys.argv[1],
            admin_email=sys.argv[2],
            admin_object_id=sys.argv[3],
        )
    else:
        print("\nTo seed a pilot customer:")
        print("  python -m app.db.init_db <customer_name> <admin_email> <entra_object_id>")
