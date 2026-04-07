"""SQLAlchemy ORM models for app metadata (customers and users)."""

from __future__ import annotations

from datetime import datetime, UTC

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    key_vault_secret_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC),
                        onupdate=lambda: datetime.now(UTC))

    users = relationship("User", back_populates="customer")
    pending_invites = relationship("PendingInvite", back_populates="customer")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entra_object_id = Column(String(255), nullable=False, unique=True)
    email = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    role = Column(String(50), nullable=False, default="viewer")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC),
                        onupdate=lambda: datetime.now(UTC))

    customer = relationship("Customer", back_populates="users")


class PendingInvite(Base):
    __tablename__ = "pending_invites"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    role = Column(String(50), nullable=False, default="viewer")
    invited_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))

    customer = relationship("Customer", back_populates="pending_invites")
