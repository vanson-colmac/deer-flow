"""ORM models for Marketior Automations Engine."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from marketior.persistence.base import Base

class AutomationRow(Base):
    __tablename__ = "automations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False) # e.g. "cron", "webhook"
    trigger_config: Mapped[dict] = mapped_column(JSON, nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False) # e.g. "spawn_thread"
    action_config: Mapped[dict] = mapped_column(JSON, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
