"""SQLAlchemy-backed Automations repository."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from marketior.persistence.automation.model import AutomationRow
from marketior.utils.time import coerce_iso

logger = logging.getLogger(__name__)

class AutomationRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: AutomationRow) -> dict[str, Any]:
        d = row.to_dict()
        for key in ("created_at", "updated_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                d[key] = coerce_iso(val)
        return d

    async def create(self, project_id: str, name: str, trigger_type: str, trigger_config: dict, action_type: str, action_config: dict) -> dict:
        now = datetime.now(UTC)
        auto = AutomationRow(
            project_id=project_id,
            name=name,
            trigger_type=trigger_type,
            trigger_config=trigger_config,
            action_type=action_type,
            action_config=action_config,
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        async with self._sf() as session:
            session.add(auto)
            await session.commit()
            await session.refresh(auto)
            return self._row_to_dict(auto)

    async def list_by_project(self, project_id: str) -> list[dict[str, Any]]:
        stmt = select(AutomationRow).where(AutomationRow.project_id == project_id).order_by(AutomationRow.created_at.desc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def list_all_enabled(self) -> list[dict[str, Any]]:
        stmt = select(AutomationRow).where(AutomationRow.enabled.is_(True))
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def toggle(self, automation_id: str, enabled: bool) -> bool:
        stmt = update(AutomationRow).where(AutomationRow.id == automation_id).values(enabled=enabled, updated_at=datetime.now(UTC))
        async with self._sf() as session:
            res = await session.execute(stmt)
            await session.commit()
            return res.rowcount > 0
