"""Project management API router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from marketior.persistence.engine import get_session_factory
from marketior.persistence.project.repo import ProjectRepository

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    instructions: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = None
    instructions: str | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    instructions: str
    created_at: str
    updated_at: str
    user_id: str


@router.post("", response_model=ProjectResponse)
async def create_project(req: ProjectCreate):
    sf = get_session_factory()
    if not sf:
        raise HTTPException(status_code=500, detail="Database not configured")
    repo = ProjectRepository(sf)
    try:
        project = await repo.create(name=req.name, instructions=req.instructions)
        return project
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=list[ProjectResponse])
async def list_projects():
    sf = get_session_factory()
    if not sf:
        raise HTTPException(status_code=500, detail="Database not configured")
    repo = ProjectRepository(sf)
    projects = await repo.list_by_user()
    return projects


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str):
    sf = get_session_factory()
    if not sf:
        raise HTTPException(status_code=500, detail="Database not configured")
    repo = ProjectRepository(sf)
    project = await repo.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: str, req: ProjectUpdate):
    sf = get_session_factory()
    if not sf:
        raise HTTPException(status_code=500, detail="Database not configured")
    repo = ProjectRepository(sf)
    project = await repo.update(project_id, name=req.name, instructions=req.instructions)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: str):
    sf = get_session_factory()
    if not sf:
        raise HTTPException(status_code=500, detail="Database not configured")
    repo = ProjectRepository(sf)
    success = await repo.delete(project_id)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found")
