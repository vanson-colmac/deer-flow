import asyncio
import logging
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from marketior.agents.thread_state import SandboxState, ThreadDataState
from marketior.sandbox import get_sandbox_provider
from marketior.config.paths import get_paths
from marketior.persistence.engine import get_session_factory
from marketior.persistence.thread_meta import ThreadMetaRepository
from marketior.persistence.project.repo import ProjectFileRepository

logger = logging.getLogger(__name__)


class SandboxMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    sandbox: NotRequired[SandboxState | None]
    thread_data: NotRequired[ThreadDataState | None]


class SandboxMiddleware(AgentMiddleware[SandboxMiddlewareState]):
    """Create a sandbox environment and assign it to an agent.

    Lifecycle Management:
    - With lazy_init=True (default): Sandbox is acquired on first tool call
    - With lazy_init=False: Sandbox is acquired on first agent invocation (before_agent)
    - Sandbox is reused across multiple turns within the same thread
    - Sandbox is NOT released after each agent call to avoid wasteful recreation
    - Cleanup happens at application shutdown via SandboxProvider.shutdown()
    """

    state_schema = SandboxMiddlewareState

    def __init__(self, lazy_init: bool = True):
        """Initialize sandbox middleware.

        Args:
            lazy_init: If True, defer sandbox acquisition until first tool call.
                      If False, acquire sandbox eagerly in before_agent().
                      Default is True for optimal performance.
        """
        super().__init__()
        self._lazy_init = lazy_init

    def _acquire_sandbox(self, thread_id: str) -> str:
        provider = get_sandbox_provider()
        sandbox_id = provider.acquire(thread_id)
        logger.info(f"Acquiring sandbox {sandbox_id}")
        return sandbox_id

    async def _acquire_sandbox_async(self, thread_id: str) -> str:
        provider = get_sandbox_provider()
        sandbox_id = await provider.acquire_async(thread_id)
        logger.info(f"Acquiring sandbox {sandbox_id}")
        return sandbox_id

    async def _release_sandbox_async(self, sandbox_id: str) -> None:
        await asyncio.to_thread(get_sandbox_provider().release, sandbox_id)

    def _destroy_sandbox(self, sandbox_id: str) -> None:
        get_sandbox_provider().destroy(sandbox_id)

    async def _destroy_sandbox_async(self, sandbox_id: str) -> None:
        await asyncio.to_thread(get_sandbox_provider().destroy, sandbox_id)

    async def _hydrate_workspace(self, thread_id: str) -> None:
        """Download files from ProjectFileRepository to the thread's workspace."""
        sf = get_session_factory()
        thread_repo = ThreadMetaRepository(sf)
        thread = await thread_repo.get(thread_id, user_id=None)
        thread_meta = thread.get("metadata", {}) if thread else {}
        if not thread_meta or not thread_meta.get("project_id"):
            return
            
        project_id = thread_meta["project_id"]
        file_repo = ProjectFileRepository(sf)
        files = await file_repo.list_by_project(project_id)
        
        workspace_dir = get_paths().thread_dir(thread_id) / "workspace"
        
        def write_files():
            workspace_dir.mkdir(parents=True, exist_ok=True)
            for f in files:
                file_path = workspace_dir / f["file_path"]
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(file_path, "wb") as out_f:
                    out_f.write(f["content"])
                    
        await asyncio.to_thread(write_files)
        logger.info(f"Hydrated {len(files)} files for project {project_id} to workspace {workspace_dir}")

    async def _sync_workspace(self, thread_id: str) -> None:
        """Upload modified files from the thread's workspace to ProjectFileRepository."""
        sf = get_session_factory()
        thread_repo = ThreadMetaRepository(sf)
        thread = await thread_repo.get(thread_id, user_id=None)
        thread_meta = thread.get("metadata", {}) if thread else {}
        if not thread_meta or not thread_meta.get("project_id"):
            return
            
        project_id = thread_meta["project_id"]
        workspace_dir = get_paths().thread_dir(thread_id) / "workspace"
        
        if not workspace_dir.exists():
            return
            
        def read_files():
            result = []
            for path in workspace_dir.rglob("*"):
                if path.is_file():
                    rel_path = str(path.relative_to(workspace_dir))
                    with open(path, "rb") as in_f:
                        result.append((rel_path, in_f.read()))
            return result
            
        file_list = await asyncio.to_thread(read_files)
        file_repo = ProjectFileRepository(sf)
        for rel_path, content in file_list:
            await file_repo.upsert(project_id, rel_path, content)
            
        logger.info(f"Synced {len(file_list)} files for project {project_id} from workspace {workspace_dir}")

    @override
    def before_agent(self, state: SandboxMiddlewareState, runtime: Runtime) -> dict | None:
        # Skip acquisition if lazy_init is enabled
        if self._lazy_init:
            return super().before_agent(state, runtime)

        # Eager initialization (original behavior)
        if "sandbox" not in state or state["sandbox"] is None:
            thread_id = (runtime.context or {}).get("thread_id")
            if thread_id is None:
                return super().before_agent(state, runtime)
            sandbox_id = self._acquire_sandbox(thread_id)
            logger.info(f"Assigned sandbox {sandbox_id} to thread {thread_id}")
            return {"sandbox": {"sandbox_id": sandbox_id}}
        return super().before_agent(state, runtime)

    @override
    async def abefore_agent(self, state: SandboxMiddlewareState, runtime: Runtime) -> dict | None:
        # Skip acquisition if lazy_init is enabled
        if self._lazy_init:
            thread_id = (runtime.context or {}).get("thread_id")
            if thread_id:
                await self._hydrate_workspace(thread_id)
            return await super().abefore_agent(state, runtime)

        # Eager initialization (original behavior), but use the async provider
        # hook so blocking sandbox startup/polling runs outside the event loop.
        if "sandbox" not in state or state["sandbox"] is None:
            thread_id = (runtime.context or {}).get("thread_id")
            if thread_id is None:
                return await super().abefore_agent(state, runtime)
            sandbox_id = await self._acquire_sandbox_async(thread_id)
            logger.info(f"Assigned sandbox {sandbox_id} to thread {thread_id}")
            await self._hydrate_workspace(thread_id)
            return {"sandbox": {"sandbox_id": sandbox_id}}
        return await super().abefore_agent(state, runtime)

    @override
    def after_agent(self, state: SandboxMiddlewareState, runtime: Runtime) -> dict | None:
        is_ephemeral = runtime.config.get("metadata", {}).get("ephemeral_sandbox") is True
        
        sandbox = state.get("sandbox")
        if sandbox is not None:
            sandbox_id = sandbox["sandbox_id"]
            if is_ephemeral:
                logger.info(f"Destroying ephemeral sandbox {sandbox_id}")
                self._destroy_sandbox(sandbox_id)
            else:
                logger.info(f"Releasing sandbox {sandbox_id}")
                get_sandbox_provider().release(sandbox_id)
            return None

        if (runtime.context or {}).get("sandbox_id") is not None:
            sandbox_id = runtime.context.get("sandbox_id")
            if is_ephemeral:
                logger.info(f"Destroying ephemeral sandbox {sandbox_id} from context")
                self._destroy_sandbox(sandbox_id)
            else:
                logger.info(f"Releasing sandbox {sandbox_id} from context")
                get_sandbox_provider().release(sandbox_id)
            return None

        # No sandbox to release
        return super().after_agent(state, runtime)

    @override
    async def aafter_agent(self, state: SandboxMiddlewareState, runtime: Runtime) -> dict | None:
        thread_id = (runtime.context or {}).get("thread_id")
        if thread_id:
            try:
                await self._sync_workspace(thread_id)
            except Exception as e:
                logger.error(f"Failed to sync workspace for thread {thread_id}: {e}")

        try:
            from langgraph.config import get_config
            runnable_config = get_config()
            is_ephemeral = runnable_config.get("metadata", {}).get("ephemeral_sandbox") is True
        except RuntimeError:
            # get_config() throws RuntimeError if not in a runnable context.
            is_ephemeral = False

        sandbox = state.get("sandbox")
        if sandbox is not None:
            sandbox_id = sandbox["sandbox_id"]
            if is_ephemeral:
                logger.info(f"Destroying ephemeral sandbox {sandbox_id}")
                await self._destroy_sandbox_async(sandbox_id)
            else:
                logger.info(f"Releasing sandbox {sandbox_id}")
                await self._release_sandbox_async(sandbox_id)
            return None

        if (runtime.context or {}).get("sandbox_id") is not None:
            sandbox_id = runtime.context.get("sandbox_id")
            if is_ephemeral:
                logger.info(f"Destroying ephemeral sandbox {sandbox_id} from context")
                await self._destroy_sandbox_async(sandbox_id)
            else:
                logger.info(f"Releasing sandbox {sandbox_id} from context")
                await self._release_sandbox_async(sandbox_id)
            return None

        # No sandbox to release
        return await super().aafter_agent(state, runtime)
