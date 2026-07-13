"""SQLAlchemy-backed Artifact repository."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from marketior.persistence.artifact.model import ArtifactRow, ArtifactVersionRow
from marketior.utils.time import coerce_iso

logger = logging.getLogger(__name__)

class ArtifactRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: ArtifactRow | ArtifactVersionRow) -> dict[str, Any]:
        d = row.to_dict()
        for key in ("created_at", "updated_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                d[key] = coerce_iso(val)
        return d

    async def create_artifact(self, project_id: str, name: str, type: str, description: str = "", content: str = "", commit_message: str = "Initial draft") -> dict:
        now = datetime.now(UTC)
        artifact = ArtifactRow(
            project_id=project_id,
            name=name,
            type=type,
            description=description,
            created_at=now,
            updated_at=now,
        )
        async with self._sf() as session:
            session.add(artifact)
            await session.commit()
            await session.refresh(artifact)
            
            version = ArtifactVersionRow(
                artifact_id=artifact.id,
                version=1,
                content=content,
                commit_message=commit_message,
                created_at=now,
            )
            session.add(version)
            await session.commit()
            
            res = self._row_to_dict(artifact)
            res["latest_version"] = self._row_to_dict(version)
            return res

    async def create_version(self, artifact_id: str, content: str, commit_message: str = "") -> dict | None:
        now = datetime.now(UTC)
        async with self._sf() as session:
            artifact = await session.get(ArtifactRow, artifact_id)
            if not artifact:
                return None
                
            stmt = select(ArtifactVersionRow).where(ArtifactVersionRow.artifact_id == artifact_id).order_by(ArtifactVersionRow.version.desc())
            result = await session.execute(stmt)
            latest = result.scalars().first()
            next_v = (latest.version + 1) if latest else 1
            
            version = ArtifactVersionRow(
                artifact_id=artifact_id,
                version=next_v,
                content=content,
                commit_message=commit_message,
                created_at=now,
            )
            session.add(version)
            
            artifact.updated_at = now
            await session.commit()
            await session.refresh(version)
            return self._row_to_dict(version)

    async def get_artifact(self, artifact_id: str, include_versions: bool = False) -> dict | None:
        async with self._sf() as session:
            artifact = await session.get(ArtifactRow, artifact_id)
            if not artifact:
                return None
            res = self._row_to_dict(artifact)
            
            if include_versions:
                stmt = select(ArtifactVersionRow).where(ArtifactVersionRow.artifact_id == artifact_id).order_by(ArtifactVersionRow.version.desc())
                result = await session.execute(stmt)
                res["versions"] = [self._row_to_dict(v) for v in result.scalars()]
            return res

    async def list_by_project(self, project_id: str) -> list[dict[str, Any]]:
        stmt = select(ArtifactRow).where(ArtifactRow.project_id == project_id).order_by(ArtifactRow.updated_at.desc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]
