import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.gateway.deps import get_current_user
from marketior.automations.scheduler import sync_automations_from_db
from marketior.persistence.automation.repo import AutomationRepository
from marketior.persistence.engine import get_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/automations", tags=["automations"])

@router.post("")
async def create_automation(
    project_id: str,
    payload: dict[str, Any],
    user_id: str | None = Depends(get_current_user),
):
    """Create a new automation for a project."""
    name = payload.get("name")
    trigger_type = payload.get("trigger_type")
    trigger_config = payload.get("trigger_config")
    action_type = payload.get("action_type")
    action_config = payload.get("action_config")

    if name is None or trigger_type is None or trigger_config is None or action_type is None or action_config is None:
        raise HTTPException(status_code=400, detail="Missing required fields")

    sf = get_session_factory()
    repo = AutomationRepository(sf)
    result = await repo.create(
        project_id=project_id,
        name=name,
        trigger_type=trigger_type,
        trigger_config=trigger_config,
        action_type=action_type,
        action_config=action_config,
    )
    
    # Reload the scheduler
    await sync_automations_from_db()
    
    return result

@router.get("")
async def list_automations(
    project_id: str,
    user_id: str | None = Depends(get_current_user),
):
    """List automations for a project."""
    sf = get_session_factory()
    repo = AutomationRepository(sf)
    return await repo.list_by_project(project_id)

@router.post("/{automation_id}/toggle")
async def toggle_automation(
    project_id: str,
    automation_id: str,
    payload: dict[str, bool],
    user_id: str | None = Depends(get_current_user),
):
    """Toggle an automation on or off."""
    enabled = payload.get("enabled", False)
    sf = get_session_factory()
    repo = AutomationRepository(sf)
    success = await repo.toggle(automation_id, enabled)
    
    if success:
        await sync_automations_from_db()
        
    return {"success": success, "enabled": enabled}
