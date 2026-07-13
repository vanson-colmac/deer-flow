"""SQLAlchemy-backed Project repository."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from marketior.persistence.project.model import ProjectRow, ProjectFileRow
from marketior.runtime.user_context import AUTO, _AutoSentinel, resolve_user_id
from marketior.utils.time import coerce_iso

logger = logging.getLogger(__name__)


class ProjectRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: ProjectRow) -> dict[str, Any]:
        d = row.to_dict()
        for key in ("created_at", "updated_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                d[key] = coerce_iso(val)
        return d

    async def create(
        self,
        name: str,
        instructions: str = "",
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.create")
        if resolved_user_id is None:
            raise ValueError("user_id cannot be None for projects")
            
        now = datetime.now(UTC)
        row = ProjectRow(
            name=name,
            instructions=instructions,
            user_id=resolved_user_id,
            created_at=now,
            updated_at=now,
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get(
        self,
        project_id: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict | None:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.get")
        async with self._sf() as session:
            row = await session.get(ProjectRow, project_id)
            if row is None:
                return None
            if resolved_user_id is not None and row.user_id != resolved_user_id:
                return None
            return self._row_to_dict(row)

    async def list_by_user(
        self,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict[str, Any]]:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.list_by_user")
        if resolved_user_id is None:
            return []
            
        stmt = select(ProjectRow).where(ProjectRow.user_id == resolved_user_id).order_by(ProjectRow.updated_at.desc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def update(
        self,
        project_id: str,
        name: str | None = None,
        instructions: str | None = None,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict | None:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.update")
        async with self._sf() as session:
            row = await session.get(ProjectRow, project_id)
            if row is None or (resolved_user_id is not None and row.user_id != resolved_user_id):
                return None
                
            if name is not None:
                row.name = name
            if instructions is not None:
                row.instructions = instructions
                
            row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def delete(
        self,
        project_id: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> bool:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.delete")
        async with self._sf() as session:
            row = await session.get(ProjectRow, project_id)
            if row is None or (resolved_user_id is not None and row.user_id != resolved_user_id):
                return False
            await session.delete(row)
            await session.commit()
            return True


class ProjectFileRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: ProjectFileRow) -> dict[str, Any]:
        d = row.to_dict()
        for key in ("created_at", "updated_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                d[key] = coerce_iso(val)
        return d

    async def upsert(self, project_id: str, file_path: str, content: bytes) -> dict:
        now = datetime.now(UTC)
        async with self._sf() as session:
            stmt = select(ProjectFileRow).where(
                ProjectFileRow.project_id == project_id,
                ProjectFileRow.file_path == file_path
            )
            result = await session.execute(stmt)
            row = result.scalars().first()
            if row:
                row.content = content
                row.updated_at = now
            else:
                row = ProjectFileRow(
                    project_id=project_id,
                    file_path=file_path,
                    content=content,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def list_by_project(self, project_id: str) -> list[dict[str, Any]]:
        stmt = select(ProjectFileRow).where(ProjectFileRow.project_id == project_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def get(self, project_id: str, file_path: str) -> dict | None:
        stmt = select(ProjectFileRow).where(
            ProjectFileRow.project_id == project_id,
            ProjectFileRow.file_path == file_path
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                return None
            return self._row_to_dict(row)

    async def delete(self, project_id: str, file_path: str) -> bool:
        stmt = select(ProjectFileRow).where(
            ProjectFileRow.project_id == project_id,
            ProjectFileRow.file_path == file_path
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            row = result.scalars().first()
            if row:
                await session.delete(row)
                await session.commit()
                return True
            return False
