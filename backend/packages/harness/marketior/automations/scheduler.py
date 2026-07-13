"""Marketior Codex-style Automations Engine.

This module uses APScheduler to trigger background 'Cowork' sessions.
"""

import asyncio
import logging
from typing import Any

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.gateway.config import get_gateway_config
from app.gateway.internal_auth import create_internal_auth_headers
from marketior.persistence.engine import get_session_factory
from marketior.persistence.automation.repo import AutomationRepository

logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler: AsyncIOScheduler | None = None

def get_scheduler() -> AsyncIOScheduler:
    """Return the global APScheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler

async def start_scheduler() -> None:
    """Start the background automations scheduler."""
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("Marketior Automations Engine (APScheduler) started.")
        # Load all DB automations after starting
        await sync_automations_from_db()

async def sync_automations_from_db() -> None:
    """Reload all enabled automations from the database into APScheduler."""
    scheduler = get_scheduler()
    
    # Remove all existing jobs first
    scheduler.remove_all_jobs()
    
    sf = get_session_factory()
    repo = AutomationRepository(sf)
    try:
        enabled_automations = await repo.list_all_enabled()
    except Exception as e:
        logger.error(f"Failed to fetch automations: {e}")
        return

    count = 0
    for auto in enabled_automations:
        if auto["trigger_type"] == "cron":
            try:
                cron_expr = auto["trigger_config"].get("cron_expression")
                thread_id = auto["action_config"].get("thread_id")
                
                if not cron_expr or not thread_id:
                    continue
                    
                trigger = CronTrigger.from_crontab(cron_expr)
                
                # Default to lead_agent if not specified
                assistant_id = auto["action_config"].get("assistant_id", "lead_agent")
                
                scheduler.add_job(
                    trigger_background_automation,
                    trigger=trigger,
                    kwargs={"thread_id": thread_id, "assistant_id": assistant_id},
                    id=auto["id"],
                    name=auto["name"],
                    replace_existing=True
                )
                count += 1
            except Exception as e:
                logger.error(f"Failed to schedule automation {auto['id']}: {e}")
                
    logger.info(f"Loaded {count} enabled automations from DB.")


async def stop_scheduler() -> None:
    """Stop the background automations scheduler."""
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Marketior Automations Engine (APScheduler) stopped.")

async def trigger_background_automation(
    thread_id: str,
    assistant_id: str | None = "lead_agent",
    input_data: dict[str, Any] | None = None,
) -> None:
    """Trigger a LangGraph agent run in the background.
    
    This acts as a 'Cowork' session trigger. It uses the Gateway's internal
    authentication to bypass standard user auth and directly spawn a run via
    the HTTP API. This ensures all LangGraph dependencies (checkpointers, 
    memory, plugins) initialize perfectly.
    """
    config = get_gateway_config()
    url = f"http://127.0.0.1:{config.port}/api/threads/{thread_id}/runs"
    
    headers = create_internal_auth_headers()
    headers["Content-Type"] = "application/json"
    
    payload: dict[str, Any] = {
        "assistant_id": assistant_id,
        "input": input_data or {},
        "metadata": {"ephemeral_sandbox": True},
        "on_disconnect": "continue"  # Crucial: Let it run even if nobody is streaming it
    }
    
    logger.info(f"Triggering background Cowork automation for thread {thread_id}")
    
    try:
        # Use a short timeout for the POST since /runs returns immediately (run starts in background)
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=5.0)
            response.raise_for_status()
            logger.info(f"Successfully triggered automation run for {thread_id}: {response.json()}")
    except Exception as e:
        logger.error(f"Failed to trigger background automation for {thread_id}: {e}", exc_info=True)
