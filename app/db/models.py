"""Database models for jarvis-ocr-service."""

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class Setting(Base):
    """
    Settings table with multi-tenant cascade lookup.

    Lookup order: User > Node > Household > System Default
    """
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True)
    key = Column(String(255), nullable=False, index=True)
    value = Column(Text, nullable=True)  # JSON-encoded
    value_type = Column(String(50), nullable=False, default="string")
    category = Column(String(100), nullable=False, default="general", index=True)
    description = Column(Text, nullable=True)
    requires_reload = Column(Boolean, default=False)
    is_secret = Column(Boolean, default=False)
    env_fallback = Column(String(255), nullable=True)

    # Multi-tenant scoping
    household_id = Column(String(255), nullable=True, index=True)
    node_id = Column(String(255), nullable=True, index=True)
    user_id = Column(Integer, nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('key', 'household_id', 'node_id', 'user_id', name='uq_setting_scope'),
    )
