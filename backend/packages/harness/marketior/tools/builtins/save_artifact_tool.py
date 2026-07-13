import json
from typing import Annotated, Optional
import logging

from langchain.tools import tool, InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from marketior.tools.types import Runtime
from marketior.persistence.artifact.repo import ArtifactRepository
from marketior.persistence.thread_meta import ThreadMetaRepository
from marketior.persistence import get_session_factory

logger = logging.getLogger(__name__)

async def _save_artifact_async(
    runtime: Runtime,
    name: str,
    type: str,
    content: str,
    description: str = "",
    commit_message: str = "",
    artifact_id: Optional[str] = None,
) -> str:
    """Save an artifact to the persistent Artifacts database."""
    thread_id = runtime.context.get("thread_id") if runtime.context else None
    if not thread_id:
        # Fallback to runtime config
        runtime_config = getattr(runtime, "config", None) or {}
        thread_id = runtime_config.get("configurable", {}).get("thread_id")

    if not thread_id:
        return "Error: Cannot determine thread_id from context."

    sf = get_session_factory()
    thread_repo = ThreadMetaRepository(sf)
    thread_meta = await thread_repo.get(thread_id)
    
    if not thread_meta or not thread_meta.get("metadata", {}).get("project_id"):
        return "Error: No project_id associated with the current thread."
        
    project_id = thread_meta["metadata"]["project_id"]
    repo = ArtifactRepository(sf)

    try:
        if artifact_id:
            logger.info(f"Updating artifact {artifact_id} for project {project_id}")
            result = await repo.create_version(
                artifact_id=artifact_id,
                content=content,
                commit_message=commit_message or f"Update {name}"
            )
            if not result:
                return f"Error: Artifact with ID {artifact_id} not found."
            return f"Successfully updated artifact {name} (ID: {artifact_id}). New version: {result['version']}"
        else:
            logger.info(f"Creating new artifact {name} for project {project_id}")
            result = await repo.create_artifact(
                project_id=project_id,
                name=name,
                type=type,
                description=description,
                content=content,
                commit_message=commit_message or "Initial draft"
            )
            return f"Successfully created artifact {name} (ID: {result['id']})."
    except Exception as e:
        logger.error(f"Failed to save artifact: {e}")
        return f"Error saving artifact: {str(e)}"

@tool("save_artifact", parse_docstring=True)
def save_artifact_tool(
    runtime: Runtime,
    name: str,
    type: str,
    content: str,
    description: str = "",
    commit_message: str = "",
    artifact_id: Optional[str] = None,
) -> str:
    """Save generated data, code, or results to the persistent Artifacts database.
    This is critical when running in ephemeral sandboxes, as local files will be destroyed.
    
    Args:
        name: The name of the artifact (e.g. 'marketing_copy.md', 'analysis_results.json').
        type: The type of artifact ('document', 'code', 'data', 'image', etc.).
        content: The actual content of the artifact to save.
        description: A short description of what this artifact contains.
        commit_message: A brief message describing this specific version or change.
        artifact_id: (Optional) If updating an existing artifact, provide its ID. Leave empty for new artifacts.
    """
    # Langchain expects a synchronous function by default, but we attach the coroutine below
    return "Error: This tool must be run asynchronously."

save_artifact_tool.coroutine = _save_artifact_async
