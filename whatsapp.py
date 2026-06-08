"""
WhatsApp platform adapter.

WhatsApp integration is more complex than Telegram/Discord because:
- No official bot API for personal accounts
- Business API requires Meta Business verification
- Most solutions use web-based automation

This adapter supports multiple backends:
1. WhatsApp Business API (requires Meta verification)
2. whatsapp-web.js (via Node.js subprocess) - for personal accounts
3. Baileys (via Node.js subprocess) - alternative for personal accounts

For simplicity, we'll implement a generic interface that can work
with different backends via a bridge pattern.
"""

import asyncio
import json
import logging
import os
import platform
import re
import shutil
import signal
import subprocess
import sqlite3

_IS_WINDOWS = platform.system() == "Windows"
from pathlib import Path
from typing import Dict, Optional, Any

from hermes_constants import get_hermes_dir

logger = logging.getLogger(__name__)


def _kill_port_process(port: int) -> None:
    """Kill any process listening on the given TCP port."""
    try:
        if _IS_WINDOWS:
            # Use netstat to find the PID bound to this port, then taskkill
            result = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[3] == "LISTENING":
                    local_addr = parts[1]
                    if local_addr.endswith(f":{port}"):
                        try:
                            subprocess.run(
                                ["taskkill", "/PID", parts[4], "/F"],
                                capture_output=True, timeout=5,
                            )
                        except subprocess.SubprocessError:
                            pass
        else:
            # Try fuser first (Linux), fall back to lsof (macOS / WSL2)
            killed = False
            try:
                result = subprocess.run(
                    ["fuser", f"{port}/tcp"],
                    capture_output=True, timeout=5,
                )
                if result.returncode == 0:
                    subprocess.run(
                        ["fuser", "-k", f"{port}/tcp"],
                        capture_output=True, timeout=5,
                    )
                    killed = True
            except FileNotFoundError:
                pass  # fuser not installed

            if not killed:
                try:
                    result = subprocess.run(
                        ["lsof", "-ti", f":{port}"],
                        capture_output=True, text=True, timeout=5,
                    )
                    for pid_str in result.stdout.strip().splitlines():
                        try:
                            os.kill(int(pid_str), signal.SIGTERM)
                        except (ValueError, ProcessLookupError, PermissionError):
                            pass
                except FileNotFoundError:
                    pass  # lsof not installed either
    except Exception:
        pass


def _kill_stale_bridge_by_pidfile(session_path: Path) -> None:
    """Kill a bridge process recorded in a PID file from a previous run.

    The bridge writes ``bridge.pid`` into the session directory when it
    starts.  If the gateway crashed without a clean shutdown the old bridge
    process becomes orphaned — this helper finds and kills it.
    """
    pid_file = session_path / "bridge.pid"
    if not pid_file.exists():
        return
    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError, TypeError):
        try:
            pid_file.unlink()
        except OSError:
            pass
        return
    # ``os.kill(pid, 0)`` is NOT a no-op on Windows (bpo-14484) — use the
    # cross-platform existence check before sending a real signal.
    from gateway.status import _pid_exists
    if _pid_exists(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            logger.info("[whatsapp] Killed stale bridge PID %d from pidfile", pid)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        pid_file.unlink()
    except OSError:
        pass


def _write_bridge_pidfile(session_path: Path, pid: int) -> None:
    """Write the bridge PID to a file for later cleanup."""
    try:
        (session_path / "bridge.pid").write_text(str(pid))
    except OSError:
        pass


def _terminate_bridge_process(proc, *, force: bool = False) -> None:
    """Terminate the bridge process using process-tree semantics where possible."""
    if _IS_WINDOWS:
        cmd = ["taskkill", "/PID", str(proc.pid), "/T"]
        if force:
            cmd.append("/F")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except FileNotFoundError:
            if force:
                proc.kill()
            else:
                proc.terminate()
            return

        if result.returncode != 0:
            details = (result.stderr or result.stdout or "").strip()
            raise OSError(details or f"taskkill failed for PID {proc.pid}")
        return

    import psutil
    try:
        parent = psutil.Process(proc.pid)
        children = parent.children(recursive=True)
        if force:
            for child in children:
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            parent.kill()
        else:
            for child in children:
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            parent.terminate()
    except psutil.NoSuchProcess:
        return

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import (
    BasePlatformAdapter,
    MessageEvent,
    MessageType,
    SendResult,
    SUPPORTED_DOCUMENT_TYPES,
    cache_image_from_url,
    cache_audio_from_url,
)

APEX_PATCH_MODE_PROMPT = True

APEX_MODE_PROMPTS = {
    "general": "Apex runtime mode: General AI. Answer as a white-labeled general assistant. Do not mention Hermes, Claude, internal tools, providers, model names, context windows, or backend routing. If live facts are needed, use the available web search/extract tools instead of claiming source access is blocked.",
    "upsc": "Apex runtime mode: LBSNAA UPSC Mentor. Stay strictly in UPSC mentor mode. Use the UPSC teacher context and answer like a disciplined civil-services mentor. Prioritize syllabus relevance, exam utility, current-policy context, PYQ-style framing, and concise study guidance. Do not drift into general/god-mode behavior. If live facts are needed, use the available web search/extract tools instead of claiming source access is blocked.",
}

APEX_ONBOARDING_MENU_TEXT = "⚡ Apex AI Gateway\n\nChoose your mode:\n1. General AI — ask, research, write, code, plan\n2. UPSC Mentor — strict exam preparation mode\n\nReply with: 1, 2, general, or upsc.\nUse menu anytime to see this again."
APEX_RETURNING_MENU_TEMPLATE = "⚡ Apex AI Gateway\n\nCurrent mode: {mode_label}\n\nChoose your mode:\n1. General AI — ask, research, write, code, plan\n2. UPSC Mentor — strict exam preparation mode\n\nReply with: 1, 2, general, or upsc. Or keep chatting in your current mode."


def check_whatsapp_requirements() -> bool:
    """
    Check if WhatsApp dependencies are available.
    
    WhatsApp requires a Node.js bridge for most implementations.
    """
    # Check for Node.js.  Resolve via shutil.which so we respect PATHEXT
    # (node.exe vs node) and get a meaningful "not installed" signal
    # instead of spawning a cmd flash on Windows.
    _node = shutil.which("node")
    if not _node:
        return False
    try:
        result = subprocess.run(
            [_node, "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


class WhatsAppAdapter(BasePlatformAdapter):
    """
    WhatsApp adapter.
    
    This implementation uses a simple HTTP bridge pattern where:
    1. A Node.js process runs the WhatsApp Web client
    2. Messages are forwarded via HTTP/IPC to this Python adapter
    3. Responses are sent back through the bridge
    
    The actual Node.js bridge implementation can vary:
    - whatsapp-web.js based
    - Baileys based
    - Business API based
    
    Configuration:
    - bridge_script: Path to the Node.js bridge script
    - bridge_port: Port for HTTP communication (default: 3000)
    - session_path: Path to store WhatsApp session data
    - dm_policy: "open" | "allowlist" | "disabled" — how DMs are handled (default: "open")
    - allow_from: List of sender IDs allowed in DMs (when dm_policy="allowlist")
    - group_policy: "open" | "allowlist" | "disabled" — which groups are processed (default: "open")
    - group_allow_from: List of group JIDs allowed (when group_policy="allowlist")
    """
    
    # WhatsApp message limits — practical UX limit, not protocol max.
    # WhatsApp allows ~65K but long messages are unreadable on mobile.
    MAX_MESSAGE_LENGTH = 4096
    DEFAULT_REPLY_PREFIX = "⚕ *Hermes Agent*\n────────────\n"
    
    # Default bridge location relative to the hermes-agent install
    _DEFAULT_BRIDGE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "whatsapp-bridge"

    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform.WHATSAPP)
        self._bridge_process: Optional[subprocess.Popen] = None
        self._bridge_port: int = config.extra.get("bridge_port", 3000)
        self._bridge_script: Optional[str] = config.extra.get(
            "bridge_script",
            str(self._DEFAULT_BRIDGE_DIR / "bridge.js"),
        )
        self._session_path: Path = Path(config.extra.get(
            "session_path",
            get_hermes_dir("platforms/whatsapp/session", "whatsapp/session")
        ))
        self._reply_prefix: Optional[str] = config.extra.get("reply_prefix")
        self._dm_policy = str(config.extra.get("dm_policy") or os.getenv("WHATSAPP_DM_POLICY", "open")).strip().lower()
        self._allow_from = self._coerce_allow_list(config.extra.get("allow_from") or config.extra.get("allowFrom"))
        self._group_policy = str(config.extra.get("group_policy") or os.getenv("WHATSAPP_GROUP_POLICY", "open")).strip().lower()
        self._group_allow_from = self._coerce_allow_list(config.extra.get("group_allow_from") or config.extra.get("groupAllowFrom"))
        self._mention_patterns = self._compile_mention_patterns()
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._bridge_log_fh = None
        self._bridge_log: Optional[Path] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._http_session: Optional["aiohttp.ClientSession"] = None
        # Set to True by disconnect() before we SIGTERM our child bridge so
        # _check_managed_bridge_exit() can distinguish an intentional
        # shutdown-time exit (returncode -15 / -2 / 0) from a real crash.
        # Without this, every graceful gateway shutdown/restart would log
        # "Fatal whatsapp adapter error" plus dispatch a fatal-error
        # notification before the normal "✓ whatsapp disconnected" fires.
        self._shutting_down: bool = False
        self._apex_user_state_path = self._session_path.parent / "apex_users.sqlite3"
        self._apex_mode_state_path = self._session_path.parent / "apex_modes.json"
        self._apex_memory_message_limit = 1536
        self._apex_memory_summary_limit = 3072
        self._apex_ensure_user_state_db()

    def _apex_db_connection(self) -> sqlite3.Connection:
        self._apex_user_state_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._apex_user_state_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _apex_trim_memory_text(self, value: Optional[str], limit: int) -> str:
        text = (value or "").strip()
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 1)].rstrip() + "…"

    def _apex_extract_stable_memory(self, state: Optional[Dict[str, Any]], user_message: str, agent_reply: str) -> str:
        previous = (state or {}).get("stable_memory") or ""
        memory_map: Dict[str, str] = {}
        for line in previous.splitlines():
            line = line.strip()
            if ": " in line:
                key, value = line.split(": ", 1)
                if key and value:
                    memory_map[key] = value

        message = (user_message or "").strip()
        lowered = message.lower()

        def store(key: str, value: str) -> None:
            value = self._apex_trim_memory_text(value.strip(), 160)
            if value:
                memory_map[key] = value

        for prefix in ["my name is ", "call me "]:
            if lowered.startswith(prefix) and len(message) > len(prefix):
                store("Name", message[len(prefix):].strip(" .,!"))
                break

        if "optional subject" in lowered:
            candidate = message
            if ":" in candidate:
                candidate = candidate.split(":", 1)[1]
            for prefix in ["my optional subject is ", "optional subject is ", "optional subject "]:
                if lowered.startswith(prefix):
                    candidate = message[len(prefix):]
                    break
            store("Optional subject", candidate.strip(" .,!"))

        if "answer in hindi" in lowered or "respond in hindi" in lowered or "hindi medium" in lowered:
            store("Language preference", "Hindi")
        elif "answer in english" in lowered or "respond in english" in lowered or "english medium" in lowered:
            store("Language preference", "English")
        elif "bilingual" in lowered or "both hindi and english" in lowered:
            store("Language preference", "Bilingual")

        for prefix in ["i am preparing for ", "i'm preparing for ", "preparing for "]:
            if prefix in lowered:
                start = lowered.index(prefix) + len(prefix)
                store("UPSC target", message[start:].strip(" .,!"))
                break

        ordered_keys = ["Name", "Language preference", "UPSC target", "Optional subject"]
        lines = [f"{key}: {memory_map[key]}" for key in ordered_keys if key in memory_map and memory_map[key]]
        extra_keys = [key for key in memory_map.keys() if key not in ordered_keys]
        for key in sorted(extra_keys):
            if memory_map[key]:
                lines.append(f"{key}: {memory_map[key]}")
        return self._apex_trim_memory_text("\\n".join(lines[:6]), 720)

    def _apex_build_summary(self, state: Optional[Dict[str, Any]], user_message: str, agent_reply: str, mode: str) -> str:
        parts = []
        if mode:
            parts.append(f"Current mode: {mode}")
        stable_memory = (state or {}).get("stable_memory") or ""
        for line in stable_memory.splitlines():
            line = line.strip()
            if line and line not in parts:
                parts.append(line)
        if user_message:
            parts.append("Latest user message: " + self._apex_trim_memory_text(user_message, 360))
        if agent_reply:
            parts.append("Latest assistant reply: " + self._apex_trim_memory_text(agent_reply, 360))
        seen = set()
        compact = []
        for part in parts:
            if part and part not in seen:
                seen.add(part)
                compact.append(part)
        return self._apex_trim_memory_text("\\n".join(compact), self._apex_memory_summary_limit)

    def _apex_compose_memory_context(self, state: Optional[Dict[str, Any]]) -> str:
        if not state:
            return ""
        parts = []
        if state.get("conversation_summary"):
            parts.append("Persistent user context:\\n" + state["conversation_summary"])
        if state.get("last_user_message"):
            parts.append("Previous user message:\\n" + state["last_user_message"])
        if state.get("last_agent_reply"):
            parts.append("Previous assistant reply:\\n" + state["last_agent_reply"])
        return "\\n\\n".join(parts).strip()

    def _apex_ensure_user_state_db(self) -> None:
        try:
            with self._apex_db_connection() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS apex_users (
                        chat_id TEXT PRIMARY KEY,
                        current_mode TEXT NOT NULL DEFAULT 'general',
                        onboarded INTEGER NOT NULL DEFAULT 0,
                        first_seen TEXT NOT NULL,
                        last_seen TEXT NOT NULL,
                        message_count INTEGER NOT NULL DEFAULT 0,
                        last_user_message TEXT NOT NULL DEFAULT '',
                        last_agent_reply TEXT NOT NULL DEFAULT '',
                        conversation_summary TEXT NOT NULL DEFAULT '',
                        last_interaction_at TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                existing = {row[1] for row in conn.execute("PRAGMA table_info(apex_users)").fetchall()}
                for ddl in [
                    ("last_user_message", "ALTER TABLE apex_users ADD COLUMN last_user_message TEXT NOT NULL DEFAULT ''"),
                    ("last_agent_reply", "ALTER TABLE apex_users ADD COLUMN last_agent_reply TEXT NOT NULL DEFAULT ''"),
                    ("conversation_summary", "ALTER TABLE apex_users ADD COLUMN conversation_summary TEXT NOT NULL DEFAULT ''"),
                    ("last_interaction_at", "ALTER TABLE apex_users ADD COLUMN last_interaction_at TEXT NOT NULL DEFAULT ''"),
                    ("stable_memory", "ALTER TABLE apex_users ADD COLUMN stable_memory TEXT NOT NULL DEFAULT ''"),
                    ("mode_switch_count", "ALTER TABLE apex_users ADD COLUMN mode_switch_count INTEGER NOT NULL DEFAULT 0"),
                    ("menu_request_count", "ALTER TABLE apex_users ADD COLUMN menu_request_count INTEGER NOT NULL DEFAULT 0"),
                    ("last_mode_switch_at", "ALTER TABLE apex_users ADD COLUMN last_mode_switch_at TEXT NOT NULL DEFAULT ''"),
                    ("phone_number", "ALTER TABLE apex_users ADD COLUMN phone_number TEXT NOT NULL DEFAULT ''"),
                    ("chat_phone", "ALTER TABLE apex_users ADD COLUMN chat_phone TEXT NOT NULL DEFAULT ''"),
                    ("sender_id", "ALTER TABLE apex_users ADD COLUMN sender_id TEXT NOT NULL DEFAULT ''"),
                    ("sender_phone", "ALTER TABLE apex_users ADD COLUMN sender_phone TEXT NOT NULL DEFAULT ''"),
                    ("chat_name", "ALTER TABLE apex_users ADD COLUMN chat_name TEXT NOT NULL DEFAULT ''"),
                    ("sender_name", "ALTER TABLE apex_users ADD COLUMN sender_name TEXT NOT NULL DEFAULT ''"),
                    ("display_name", "ALTER TABLE apex_users ADD COLUMN display_name TEXT NOT NULL DEFAULT ''"),
                    ("chat_jid_kind", "ALTER TABLE apex_users ADD COLUMN chat_jid_kind TEXT NOT NULL DEFAULT ''"),
                    ("sender_jid_kind", "ALTER TABLE apex_users ADD COLUMN sender_jid_kind TEXT NOT NULL DEFAULT ''"),
                    ("is_group", "ALTER TABLE apex_users ADD COLUMN is_group INTEGER NOT NULL DEFAULT 0"),
                    ("identity_source", "ALTER TABLE apex_users ADD COLUMN identity_source TEXT NOT NULL DEFAULT ''"),
                    ("identity_refreshed_at", "ALTER TABLE apex_users ADD COLUMN identity_refreshed_at TEXT NOT NULL DEFAULT ''"),
                ]:
                    if ddl[0] not in existing:
                        conn.execute(ddl[1])
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS apex_usage_ledger (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        mode TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        units INTEGER NOT NULL DEFAULT 1,
                        metadata TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_apex_usage_ledger_chat_time ON apex_usage_ledger(chat_id, created_at)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_apex_usage_ledger_event_time ON apex_usage_ledger(event_type, created_at)")
        except Exception as exc:
            logger.debug("Failed to ensure Apex user-state DB: %s", exc)

    def _apex_get_user_state(self, chat_id: str) -> Optional[Dict[str, Any]]:
        try:
            with self._apex_db_connection() as conn:
                row = conn.execute(
                    "SELECT chat_id, current_mode, onboarded, first_seen, last_seen, message_count, last_user_message, last_agent_reply, conversation_summary, last_interaction_at, stable_memory, mode_switch_count, menu_request_count, last_mode_switch_at, phone_number, chat_phone, sender_id, sender_phone, chat_name, sender_name, display_name, chat_jid_kind, sender_jid_kind, is_group, identity_source, identity_refreshed_at FROM apex_users WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()
                if row:
                    return {
                        "chat_id": str(row["chat_id"]),
                        "current_mode": str(row["current_mode"]),
                        "onboarded": bool(row["onboarded"]),
                        "first_seen": str(row["first_seen"]),
                        "last_seen": str(row["last_seen"]),
                        "message_count": int(row["message_count"]),
                        "last_user_message": str(row["last_user_message"] or ""),
                        "last_agent_reply": str(row["last_agent_reply"] or ""),
                        "conversation_summary": str(row["conversation_summary"] or ""),
                        "last_interaction_at": str(row["last_interaction_at"] or ""),
                        "stable_memory": str(row["stable_memory"] or ""),
                        "mode_switch_count": int(row["mode_switch_count"] or 0),
                        "menu_request_count": int(row["menu_request_count"] or 0),
                        "last_mode_switch_at": str(row["last_mode_switch_at"] or ""),
                        "phone_number": str(row["phone_number"] or ""),
                        "chat_phone": str(row["chat_phone"] or ""),
                        "sender_id": str(row["sender_id"] or ""),
                        "sender_phone": str(row["sender_phone"] or ""),
                        "chat_name": str(row["chat_name"] or ""),
                        "sender_name": str(row["sender_name"] or ""),
                        "display_name": str(row["display_name"] or ""),
                        "chat_jid_kind": str(row["chat_jid_kind"] or ""),
                        "sender_jid_kind": str(row["sender_jid_kind"] or ""),
                        "is_group": bool(row["is_group"]),
                        "identity_source": str(row["identity_source"] or ""),
                        "identity_refreshed_at": str(row["identity_refreshed_at"] or ""),
                    }
        except Exception as exc:
            logger.debug("Failed to load Apex user state: %s", exc)
        return None

    def _apex_upsert_user_state(
        self,
        chat_id: str,
        *,
        current_mode: Optional[str] = None,
        onboarded: Optional[bool] = None,
        increment_message_count: bool = False,
        last_user_message: Optional[str] = None,
        last_agent_reply: Optional[str] = None,
        conversation_summary: Optional[str] = None,
        stable_memory: Optional[str] = None,
        increment_mode_switch_count: bool = False,
        increment_menu_request_count: bool = False,
        touch_interaction: bool = False,
        touch_mode_switch: bool = False,
        identity: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from datetime import datetime
        now = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
        identity_data = {k: v for k, v in (identity or {}).items() if v not in (None, "")}
        try:
            with self._apex_db_connection() as conn:
                row = conn.execute(
                    "SELECT chat_id, current_mode, onboarded, first_seen, last_seen, message_count, last_user_message, last_agent_reply, conversation_summary, last_interaction_at, stable_memory, mode_switch_count, menu_request_count, last_mode_switch_at, phone_number, chat_phone, sender_id, sender_phone, chat_name, sender_name, display_name, chat_jid_kind, sender_jid_kind, is_group, identity_source, identity_refreshed_at FROM apex_users WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()
                if row is None:
                    mode = current_mode if current_mode in APEX_MODE_PROMPTS else "general"
                    onboarded_value = 1 if onboarded else 0
                    message_count = 1 if increment_message_count else 0
                    mode_switch_count = 1 if increment_mode_switch_count else 0
                    menu_request_count = 1 if increment_menu_request_count else 0
                    phone_number = str(identity_data.get("phone_number") or "")
                    chat_phone = str(identity_data.get("chat_phone") or "")
                    sender_id = str(identity_data.get("sender_id") or "")
                    sender_phone = str(identity_data.get("sender_phone") or "")
                    chat_name = str(identity_data.get("chat_name") or "")
                    sender_name = str(identity_data.get("sender_name") or "")
                    display_name = str(identity_data.get("display_name") or sender_name or chat_name or "")
                    chat_jid_kind = str(identity_data.get("chat_jid_kind") or "")
                    sender_jid_kind = str(identity_data.get("sender_jid_kind") or "")
                    is_group = 1 if bool(identity_data.get("is_group")) else 0
                    identity_source = str(identity_data.get("identity_source") or "")
                    identity_refreshed_at = now if identity_data else ""
                    conn.execute(
                        """
                        INSERT INTO apex_users (
                            chat_id, current_mode, onboarded, first_seen, last_seen, message_count,
                            last_user_message, last_agent_reply, conversation_summary, last_interaction_at,
                            stable_memory, mode_switch_count, menu_request_count, last_mode_switch_at,
                            phone_number, chat_phone, sender_id, sender_phone, chat_name, sender_name,
                            display_name, chat_jid_kind, sender_jid_kind, is_group, identity_source, identity_refreshed_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            chat_id,
                            mode,
                            onboarded_value,
                            now,
                            now,
                            message_count,
                            self._apex_trim_memory_text(last_user_message, self._apex_memory_message_limit),
                            self._apex_trim_memory_text(last_agent_reply, self._apex_memory_message_limit),
                            self._apex_trim_memory_text(conversation_summary, self._apex_memory_summary_limit),
                            now if touch_interaction else "",
                            self._apex_trim_memory_text(stable_memory, 720),
                            mode_switch_count,
                            menu_request_count,
                            now if touch_mode_switch else "",
                            phone_number,
                            chat_phone,
                            sender_id,
                            sender_phone,
                            chat_name,
                            sender_name,
                            display_name,
                            chat_jid_kind,
                            sender_jid_kind,
                            is_group,
                            identity_source,
                            identity_refreshed_at,
                        ),
                    )
                else:
                    mode = current_mode if current_mode in APEX_MODE_PROMPTS else str(row["current_mode"])
                    onboarded_value = int(row["onboarded"]) if onboarded is None else (1 if onboarded else 0)
                    message_count = int(row["message_count"]) + (1 if increment_message_count else 0)
                    mode_switch_count = int(row["mode_switch_count"] or 0) + (1 if increment_mode_switch_count else 0)
                    menu_request_count = int(row["menu_request_count"] or 0) + (1 if increment_menu_request_count else 0)
                    stored_last_user_message = str(row["last_user_message"] or "") if last_user_message is None else self._apex_trim_memory_text(last_user_message, self._apex_memory_message_limit)
                    stored_last_agent_reply = str(row["last_agent_reply"] or "") if last_agent_reply is None else self._apex_trim_memory_text(last_agent_reply, self._apex_memory_message_limit)
                    stored_summary = str(row["conversation_summary"] or "") if conversation_summary is None else self._apex_trim_memory_text(conversation_summary, self._apex_memory_summary_limit)
                    stored_stable_memory = str(row["stable_memory"] or "") if stable_memory is None else self._apex_trim_memory_text(stable_memory, 720)
                    last_interaction_at = str(row["last_interaction_at"] or "")
                    last_mode_switch_at = str(row["last_mode_switch_at"] or "")
                    phone_number = str(identity_data.get("phone_number") or row["phone_number"] or "")
                    chat_phone = str(identity_data.get("chat_phone") or row["chat_phone"] or "")
                    sender_id = str(identity_data.get("sender_id") or row["sender_id"] or "")
                    sender_phone = str(identity_data.get("sender_phone") or row["sender_phone"] or "")
                    chat_name = str(identity_data.get("chat_name") or row["chat_name"] or "")
                    sender_name = str(identity_data.get("sender_name") or row["sender_name"] or "")
                    display_name = str(identity_data.get("display_name") or row["display_name"] or sender_name or chat_name or "")
                    chat_jid_kind = str(identity_data.get("chat_jid_kind") or row["chat_jid_kind"] or "")
                    sender_jid_kind = str(identity_data.get("sender_jid_kind") or row["sender_jid_kind"] or "")
                    is_group = 1 if bool(identity_data.get("is_group")) else int(row["is_group"] or 0)
                    identity_source = str(identity_data.get("identity_source") or row["identity_source"] or "")
                    identity_refreshed_at = str(row["identity_refreshed_at"] or "")
                    if identity_data:
                        identity_refreshed_at = now
                    if touch_interaction:
                        last_interaction_at = now
                    if touch_mode_switch:
                        last_mode_switch_at = now
                    conn.execute(
                        """
                        UPDATE apex_users
                        SET current_mode = ?, onboarded = ?, last_seen = ?, message_count = ?,
                            last_user_message = ?, last_agent_reply = ?, conversation_summary = ?, last_interaction_at = ?,
                            stable_memory = ?, mode_switch_count = ?, menu_request_count = ?, last_mode_switch_at = ?,
                            phone_number = ?, chat_phone = ?, sender_id = ?, sender_phone = ?, chat_name = ?, sender_name = ?,
                            display_name = ?, chat_jid_kind = ?, sender_jid_kind = ?, is_group = ?, identity_source = ?, identity_refreshed_at = ?
                        WHERE chat_id = ?
                        """,
                        (
                            mode,
                            onboarded_value,
                            now,
                            message_count,
                            stored_last_user_message,
                            stored_last_agent_reply,
                            stored_summary,
                            last_interaction_at,
                            stored_stable_memory,
                            mode_switch_count,
                            menu_request_count,
                            last_mode_switch_at,
                            phone_number,
                            chat_phone,
                            sender_id,
                            sender_phone,
                            chat_name,
                            sender_name,
                            display_name,
                            chat_jid_kind,
                            sender_jid_kind,
                            is_group,
                            identity_source,
                            identity_refreshed_at,
                            chat_id,
                        ),
                    )
                row = conn.execute(
                    "SELECT chat_id, current_mode, onboarded, first_seen, last_seen, message_count, last_user_message, last_agent_reply, conversation_summary, last_interaction_at, stable_memory, mode_switch_count, menu_request_count, last_mode_switch_at, phone_number, chat_phone, sender_id, sender_phone, chat_name, sender_name, display_name, chat_jid_kind, sender_jid_kind, is_group, identity_source, identity_refreshed_at FROM apex_users WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()
                return {
                    "chat_id": str(row["chat_id"]),
                    "current_mode": str(row["current_mode"]),
                    "onboarded": bool(row["onboarded"]),
                    "first_seen": str(row["first_seen"]),
                    "last_seen": str(row["last_seen"]),
                    "message_count": int(row["message_count"]),
                    "last_user_message": str(row["last_user_message"] or ""),
                    "last_agent_reply": str(row["last_agent_reply"] or ""),
                    "conversation_summary": str(row["conversation_summary"] or ""),
                    "last_interaction_at": str(row["last_interaction_at"] or ""),
                    "stable_memory": str(row["stable_memory"] or ""),
                    "mode_switch_count": int(row["mode_switch_count"] or 0),
                    "menu_request_count": int(row["menu_request_count"] or 0),
                    "last_mode_switch_at": str(row["last_mode_switch_at"] or ""),
                }
        except Exception as exc:
            logger.debug("Failed to upsert Apex user state: %s", exc)
        return {
            "chat_id": chat_id,
            "current_mode": current_mode if current_mode in APEX_MODE_PROMPTS else "general",
            "onboarded": bool(onboarded),
            "first_seen": now,
            "last_seen": now,
            "message_count": 1 if increment_message_count else 0,
            "last_user_message": self._apex_trim_memory_text(last_user_message, self._apex_memory_message_limit),
            "last_agent_reply": self._apex_trim_memory_text(last_agent_reply, self._apex_memory_message_limit),
            "conversation_summary": self._apex_trim_memory_text(conversation_summary, self._apex_memory_summary_limit),
            "last_interaction_at": now if touch_interaction else "",
            "stable_memory": self._apex_trim_memory_text(stable_memory, 720),
            "mode_switch_count": 1 if increment_mode_switch_count else 0,
            "menu_request_count": 1 if increment_menu_request_count else 0,
            "last_mode_switch_at": now if touch_mode_switch else "",
            "phone_number": str(identity_data.get("phone_number") or ""),
            "chat_phone": str(identity_data.get("chat_phone") or ""),
            "sender_id": str(identity_data.get("sender_id") or ""),
            "sender_phone": str(identity_data.get("sender_phone") or ""),
            "chat_name": str(identity_data.get("chat_name") or ""),
            "sender_name": str(identity_data.get("sender_name") or ""),
            "display_name": str(identity_data.get("display_name") or ""),
            "chat_jid_kind": str(identity_data.get("chat_jid_kind") or ""),
            "sender_jid_kind": str(identity_data.get("sender_jid_kind") or ""),
            "is_group": bool(identity_data.get("is_group")),
            "identity_source": str(identity_data.get("identity_source") or ""),
            "identity_refreshed_at": now if identity_data else "",
        }

    def _apex_record_agent_reply(self, chat_id: str, content: str) -> None:
        state = self._apex_get_user_state(chat_id)
        if not state:
            return
        stable_memory = self._apex_extract_stable_memory(
            state,
            state.get("last_user_message", ""),
            content,
        )
        state_with_stable = dict(state)
        state_with_stable["stable_memory"] = stable_memory
        summary = self._apex_build_summary(
            state_with_stable,
            state.get("last_user_message", ""),
            content,
            state.get("current_mode", "general"),
        )
        updated_state = self._apex_upsert_user_state(
            chat_id,
            last_agent_reply=content,
            conversation_summary=summary,
            stable_memory=stable_memory,
            touch_interaction=True,
        )
        self._apex_record_usage_event(chat_id, "outbound", updated_state.get("current_mode", "general"))

    def _apex_record_usage_event(self, chat_id: str, event_type: str, mode: str = "", units: int = 1, metadata: str = "") -> None:
        from datetime import datetime
        safe_event_type = re.sub(r"[^a-z0-9_:-]+", "_", (event_type or "").strip().lower())[:64]
        if not safe_event_type:
            return
        safe_mode = mode if mode in APEX_MODE_PROMPTS else ""
        safe_units = max(1, min(int(units or 1), 1000))
        safe_metadata = self._apex_trim_memory_text(metadata, 240)
        created_at = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
        try:
            with self._apex_db_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO apex_usage_ledger (chat_id, event_type, mode, created_at, units, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (chat_id, safe_event_type, safe_mode, created_at, safe_units, safe_metadata),
                )
        except Exception as exc:
            logger.debug("Failed to record Apex usage event: %s", exc)

    def _apex_load_modes(self) -> Dict[str, str]:
        states = {}
        try:
            with self._apex_db_connection() as conn:
                rows = conn.execute("SELECT chat_id, current_mode FROM apex_users").fetchall()
                for row in rows:
                    mode = str(row["current_mode"])
                    if mode in APEX_MODE_PROMPTS:
                        states[str(row["chat_id"])] = mode
                if states:
                    return states
        except Exception as exc:
            logger.debug("Failed to load Apex mode state from DB: %s", exc)
        try:
            if self._apex_mode_state_path.exists():
                data = json.loads(self._apex_mode_state_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    legacy = {str(k): str(v) for k, v in data.items() if str(v) in APEX_MODE_PROMPTS}
                    if legacy:
                        for legacy_chat_id, legacy_mode in legacy.items():
                            self._apex_upsert_user_state(legacy_chat_id, current_mode=legacy_mode, onboarded=True)
                        return legacy
        except Exception as exc:
            logger.debug("Failed to load legacy Apex mode state: %s", exc)
        return {}

    def _apex_save_modes(self, modes: Dict[str, str]) -> None:
        try:
            for saved_chat_id, saved_mode in modes.items():
                if str(saved_mode) in APEX_MODE_PROMPTS:
                    self._apex_upsert_user_state(str(saved_chat_id), current_mode=str(saved_mode), onboarded=True)
            self._apex_mode_state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._apex_mode_state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(modes, indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(self._apex_mode_state_path)
        except Exception as exc:
            logger.debug("Failed to save Apex mode state: %s", exc)

    def _apex_mode_for_inbound_text(self, chat_id: str, body: str, data: Optional[Dict[str, Any]] = None) -> tuple[str, bool, bool, bool, Dict[str, Any]]:
        identity = self._apex_identity_from_message(data)
        state = self._apex_get_user_state(chat_id)
        if state is None:
            state = self._apex_upsert_user_state(chat_id, identity=identity)
        text = (body or "").strip().lower()
        normalized = re.sub(r"[^a-z0-9]+", " ", text).strip()
        words = set(normalized.split())
        selected = None
        is_new_user = not state.get("onboarded", False)
        show_onboarding_menu = is_new_user
        show_returning_menu = False
        is_menu_request = normalized in {"", "menu", "start", "help", "hi", "hello", "hey", "new"} or normalized.startswith("new ")
        if is_menu_request:
            if is_new_user:
                show_onboarding_menu = True
            else:
                show_returning_menu = True
        general_aliases = {"1", "general", "general ai", "ai", "assistant", "mode 1", "option 1", "switch general", "switch to general"}
        upsc_aliases = {"2", "upsc", "mentor", "upsc mentor", "lbsnaa", "lbsnaa mentor", "lbsnaa upsc mentor", "mode 2", "option 2", "switch upsc", "switch to upsc"}
        if normalized in general_aliases or ("general" in words and "upsc" not in words):
            selected = "general"
        elif normalized in upsc_aliases or "upsc" in words or "lbsnaa" in words:
            selected = "upsc"
        stable_memory = self._apex_extract_stable_memory(state, body or "", "")
        state_with_stable = dict(state or {})
        state_with_stable["stable_memory"] = stable_memory
        if selected:
            changed = state.get("current_mode") != selected
            summary = self._apex_build_summary(state_with_stable, body or "", "", selected)
            state = self._apex_upsert_user_state(
                chat_id,
                current_mode=selected,
                onboarded=True,
                increment_message_count=True,
                last_user_message=body,
                conversation_summary=summary,
                stable_memory=stable_memory,
                increment_mode_switch_count=changed,
                increment_menu_request_count=is_menu_request,
                touch_interaction=True,
                touch_mode_switch=changed,
                identity=identity,
            )
            modes = self._apex_load_modes()
            modes[chat_id] = selected
            self._apex_save_modes(modes)
            self._apex_record_usage_event(chat_id, "inbound", selected)
            if changed:
                self._apex_record_usage_event(chat_id, "mode_switch", selected)
            return selected, changed, False, False, state
        summary = self._apex_build_summary(state_with_stable, body or "", "", state.get("current_mode", "general"))
        state = self._apex_upsert_user_state(
            chat_id,
            increment_message_count=True,
            last_user_message=body,
            conversation_summary=summary,
            stable_memory=stable_memory,
            increment_menu_request_count=is_menu_request,
            touch_interaction=True,
            identity=identity,
        )
        current_mode = state.get("current_mode", "general")
        self._apex_record_usage_event(chat_id, "inbound", current_mode)
        if is_menu_request:
            self._apex_record_usage_event(chat_id, "menu", current_mode)
        return current_mode, False, show_onboarding_menu, show_returning_menu, state

    def _effective_reply_prefix(self) -> str:
        """Return the prefix the Node bridge will add in self-chat mode."""
        whatsapp_mode = os.getenv("WHATSAPP_MODE", "self-chat")
        if whatsapp_mode != "self-chat":
            return ""
        if self._reply_prefix is not None:
            return self._reply_prefix.replace("\\n", "\n")
        env_prefix = os.getenv("WHATSAPP_REPLY_PREFIX")
        if env_prefix is not None:
            return env_prefix.replace("\\n", "\n")
        return self.DEFAULT_REPLY_PREFIX

    def _outgoing_chunk_limit(self) -> int:
        """Reserve room for the bridge-side prefix so final WhatsApp text fits."""
        prefix_len = len(self._effective_reply_prefix())
        # Keep enough space for truncate_message's pagination indicator and
        # code-fence repair even if a user configures a very long prefix.
        return max(1024, self.MAX_MESSAGE_LENGTH - prefix_len)

    def _whatsapp_require_mention(self) -> bool:
        configured = self.config.extra.get("require_mention")
        if configured is not None:
            if isinstance(configured, str):
                return configured.lower() in {"true", "1", "yes", "on"}
            return bool(configured)
        return os.getenv("WHATSAPP_REQUIRE_MENTION", "false").lower() in {"true", "1", "yes", "on"}

    def _whatsapp_free_response_chats(self) -> set[str]:
        raw = self.config.extra.get("free_response_chats")
        if raw is None:
            raw = os.getenv("WHATSAPP_FREE_RESPONSE_CHATS", "")
        if isinstance(raw, list):
            return {str(part).strip() for part in raw if str(part).strip()}
        return {part.strip() for part in str(raw).split(",") if part.strip()}

    @staticmethod
    def _coerce_allow_list(raw) -> set[str]:
        """Parse allow_from / group_allow_from from config or env var."""
        if raw is None:
            return set()
        if isinstance(raw, list):
            return {str(part).strip() for part in raw if str(part).strip()}
        return {part.strip() for part in str(raw).split(",") if part.strip()}

    @staticmethod
    def _is_broadcast_chat(chat_id: str) -> bool:
        """True for WhatsApp pseudo-chats that aren't real conversations.

        Covers Status updates (Stories) and Channel/Newsletter broadcasts.
        These show up as inbound messages on Baileys but the agent should
        never reply — answering a Story update spams the contact's status
        feed, and Channel posts aren't addressable in the first place.
        """
        if not chat_id:
            return False
        cid = chat_id.strip().lower()
        if cid == "status@broadcast":
            return True
        # @broadcast suffix covers status@broadcast plus any future
        # broadcast-list variants. @newsletter is the Channel JID suffix.
        if cid.endswith("@broadcast") or cid.endswith("@newsletter"):
            return True
        return False

    def _is_dm_allowed(self, sender_id: str) -> bool:
        """Check whether a DM from the given sender should be processed."""
        if self._dm_policy == "disabled":
            return False
        if self._dm_policy == "allowlist":
            return sender_id in self._allow_from
        # "open" — all DMs allowed
        return True

    def _is_group_allowed(self, chat_id: str) -> bool:
        """Check whether a group chat should be processed."""
        if self._group_policy == "disabled":
            return False
        if self._group_policy == "allowlist":
            return chat_id in self._group_allow_from
        # "open" — all groups allowed
        return True

    def _compile_mention_patterns(self):
        patterns = self.config.extra.get("mention_patterns")
        if patterns is None:
            raw = os.getenv("WHATSAPP_MENTION_PATTERNS", "").strip()
            if raw:
                try:
                    patterns = json.loads(raw)
                except Exception:
                    patterns = [part.strip() for part in raw.splitlines() if part.strip()]
                    if not patterns:
                        patterns = [part.strip() for part in raw.split(",") if part.strip()]
        if patterns is None:
            return []
        if isinstance(patterns, str):
            patterns = [patterns]
        if not isinstance(patterns, list):
            logger.warning("[%s] whatsapp mention_patterns must be a list or string; got %s", self.name, type(patterns).__name__)
            return []

        compiled = []
        for pattern in patterns:
            if not isinstance(pattern, str) or not pattern.strip():
                continue
            try:
                compiled.append(re.compile(pattern, re.IGNORECASE))
            except re.error as exc:
                logger.warning("[%s] Invalid WhatsApp mention pattern %r: %s", self.name, pattern, exc)
        if compiled:
            logger.info("[%s] Loaded %d WhatsApp mention pattern(s)", self.name, len(compiled))
        return compiled

    @staticmethod
    def _normalize_whatsapp_id(value: Optional[str]) -> str:
        if not value:
            return ""
        normalized = str(value).strip()
        if ":" in normalized and "@" in normalized:
            normalized = normalized.replace(":", "@", 1)
        return normalized

    def _bot_ids_from_message(self, data: Dict[str, Any]) -> set[str]:
        bot_ids = set()
        for candidate in data.get("botIds") or []:
            normalized = self._normalize_whatsapp_id(candidate)
            if normalized:
                bot_ids.add(normalized)
        return bot_ids

    def _message_is_reply_to_bot(self, data: Dict[str, Any]) -> bool:
        quoted_participant = self._normalize_whatsapp_id(data.get("quotedParticipant"))
        if not quoted_participant:
            return False
        return quoted_participant in self._bot_ids_from_message(data)

    def _message_mentions_bot(self, data: Dict[str, Any]) -> bool:
        bot_ids = self._bot_ids_from_message(data)
        if not bot_ids:
            return False
        mentioned_ids = {
            nid
            for candidate in (data.get("mentionedIds") or [])
            if (nid := self._normalize_whatsapp_id(candidate))
        }
        if mentioned_ids & bot_ids:
            return True

        body = str(data.get("body") or "")
        lower_body = body.lower()
        for bot_id in bot_ids:
            bare_id = bot_id.split("@", 1)[0].lower()
            if bare_id and (f"@{bare_id}" in lower_body or bare_id in lower_body):
                return True
        return False

    def _message_matches_mention_patterns(self, data: Dict[str, Any]) -> bool:
        if not self._mention_patterns:
            return False
        body = str(data.get("body") or "")
        return any(pattern.search(body) for pattern in self._mention_patterns)

    def _clean_bot_mention_text(self, text: str, data: Dict[str, Any]) -> str:
        if not text:
            return text
        bot_ids = self._bot_ids_from_message(data)
        cleaned = text
        for bot_id in bot_ids:
            bare_id = bot_id.split("@", 1)[0]
            if bare_id:
                cleaned = re.sub(rf"@{re.escape(bare_id)}\b[,:\-]*\s*", "", cleaned)
        return cleaned.strip() or text

    def _should_process_message(self, data: Dict[str, Any]) -> bool:
        chat_id_raw = str(data.get("chatId") or "")
        # WhatsApp uses pseudo-chats for Status updates (Stories) and
        # Channel/Newsletter broadcasts. These are not real conversations
        # and the agent should never reply to them — even in self-chat mode
        # where the bridge may surface them as "fromMe" events.
        if self._is_broadcast_chat(chat_id_raw):
            return False
        is_group = data.get("isGroup", False)
        if is_group:
            chat_id = chat_id_raw
            if not self._is_group_allowed(chat_id):
                return False
        else:
            sender_id = str(data.get("senderId") or data.get("from") or "")
            if not self._is_dm_allowed(sender_id):
                return False
            # DMs that pass the policy gate are always processed
            return True
        # Group messages: check mention / free-response settings
        chat_id = str(data.get("chatId") or "")
        if chat_id in self._whatsapp_free_response_chats():
            return True
        if not self._whatsapp_require_mention():
            return True
        body = str(data.get("body") or "").strip()
        if body.startswith("/"):
            return True
        if self._message_is_reply_to_bot(data):
            return True
        if self._message_mentions_bot(data):
            return True
        return self._message_matches_mention_patterns(data)
    
    async def connect(self) -> bool:
        """
        Start the WhatsApp bridge.
        
        This launches the Node.js bridge process and waits for it to be ready.
        """
        if not check_whatsapp_requirements():
            logger.warning("[%s] Node.js not found. WhatsApp requires Node.js.", self.name)
            self._set_fatal_error(
                "whatsapp_node_missing",
                "Node.js is not installed — install Node.js and re-run `hermes gateway`.",
                retryable=False,
            )
            return False
        
        bridge_path = Path(self._bridge_script)
        if not bridge_path.exists():
            logger.warning("[%s] Bridge script not found: %s", self.name, bridge_path)
            self._set_fatal_error(
                "whatsapp_bridge_missing",
                f"WhatsApp bridge script missing at {bridge_path}.",
                retryable=False,
            )
            return False

        # Pre-flight: skip the 30s bridge bootstrap entirely if the user
        # never finished pairing.  Without creds.json the bridge prints
        # QR codes to its log file and never reaches status:connected,
        # so every gateway restart paid the 30s timeout + queued WhatsApp
        # for indefinite retries.  Mark non-retryable so the user gets a
        # clear "run hermes whatsapp" message instead of the watcher
        # silently hammering an unconfigured platform.
        creds_path = self._session_path / "creds.json"
        if not creds_path.exists():
            logger.warning(
                "[%s] WhatsApp is enabled but not paired (no creds.json at %s). "
                "Run `hermes whatsapp` to pair, or remove WHATSAPP_ENABLED from "
                "your .env to disable.",
                self.name, creds_path,
            )
            self._set_fatal_error(
                "whatsapp_not_paired",
                "WhatsApp enabled but not paired — run `hermes whatsapp` to pair.",
                retryable=False,
            )
            return False

        logger.info("[%s] Bridge found at %s", self.name, bridge_path)
        
        # Acquire scoped lock to prevent duplicate sessions
        lock_acquired = False
        try:
            if not self._acquire_platform_lock('whatsapp-session', str(self._session_path), 'WhatsApp session'):
                return False
            lock_acquired = True
        except Exception as e:
            logger.warning("[%s] Could not acquire session lock (non-fatal): %s", self.name, e)

        try:
            # Auto-install npm dependencies if node_modules doesn't exist
            bridge_dir = bridge_path.parent
            if not (bridge_dir / "node_modules").exists():
                print(f"[{self.name}] Installing WhatsApp bridge dependencies...")
                # Resolve npm path so Windows can execute the .cmd shim.
                # shutil.which honours PATHEXT; on POSIX it returns the
                # plain executable path.
                _npm_bin = shutil.which("npm") or "npm"
                try:
                    # Read timeout from environment variable, default to 300 seconds (5 minutes)
                    # to accommodate slower systems like Unraid NAS
                    npm_install_timeout = int(os.environ.get("WHATSAPP_NPM_INSTALL_TIMEOUT", "300"))
                    install_result = subprocess.run(
                        [_npm_bin, "install", "--silent"],
                        cwd=str(bridge_dir),
                        capture_output=True,
                        text=True,
                        timeout=npm_install_timeout,
                    )
                    if install_result.returncode != 0:
                        print(f"[{self.name}] npm install failed: {install_result.stderr}")
                        return False
                    print(f"[{self.name}] Dependencies installed")
                except Exception as e:
                    print(f"[{self.name}] Failed to install dependencies: {e}")
                    return False

            # Ensure session directory exists
            self._session_path.mkdir(parents=True, exist_ok=True)
            
            # Check if bridge is already running and connected
            import aiohttp
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"http://127.0.0.1:{self._bridge_port}/health",
                        timeout=aiohttp.ClientTimeout(total=2)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            bridge_status = data.get("status", "unknown")
                            if bridge_status == "connected":
                                print(f"[{self.name}] Using existing bridge (status: {bridge_status})")
                                self._mark_connected()
                                self._bridge_process = None  # Not managed by us
                                self._http_session = aiohttp.ClientSession()
                                self._poll_task = asyncio.create_task(self._poll_messages())
                                return True
                            else:
                                print(f"[{self.name}] Bridge found but not connected (status: {bridge_status}), restarting")
            except Exception:
                pass  # Bridge not running, start a new one
            
            # Kill any orphaned bridge from a previous gateway run
            _kill_stale_bridge_by_pidfile(self._session_path)
            _kill_port_process(self._bridge_port)
            await asyncio.sleep(1)
            
            # Start the bridge process in its own process group.
            # Route output to a log file so QR codes, errors, and reconnection
            # messages are preserved for troubleshooting.
            whatsapp_mode = os.getenv("WHATSAPP_MODE", "self-chat")
            self._bridge_log = self._session_path.parent / "bridge.log"
            bridge_log_fh = open(self._bridge_log, "a", encoding="utf-8")
            self._bridge_log_fh = bridge_log_fh

            # Build bridge subprocess environment.
            # Pass WHATSAPP_REPLY_PREFIX from config.yaml so the Node bridge
            # can use it without the user needing to set a separate env var.
            bridge_env = os.environ.copy()
            if self._reply_prefix is not None:
                bridge_env["WHATSAPP_REPLY_PREFIX"] = self._reply_prefix

            self._bridge_process = subprocess.Popen(
                [
                    "node",
                    str(bridge_path),
                    "--port", str(self._bridge_port),
                    "--session", str(self._session_path),
                    "--mode", whatsapp_mode,
                ],
                stdout=bridge_log_fh,
                stderr=bridge_log_fh,
                preexec_fn=None if _IS_WINDOWS else os.setsid,
                env=bridge_env,
            )
            _write_bridge_pidfile(self._session_path, self._bridge_process.pid)
            
            # Wait for the bridge to connect to WhatsApp.
            # Phase 1: wait for the HTTP server to come up (up to 15s).
            # Phase 2: wait for WhatsApp status: connected (up to 15s more).
            import aiohttp
            http_ready = False
            data = {}
            for attempt in range(15):
                await asyncio.sleep(1)
                if self._bridge_process.poll() is not None:
                    print(f"[{self.name}] Bridge process died (exit code {self._bridge_process.returncode})")
                    print(f"[{self.name}] Check log: {self._bridge_log}")
                    self._close_bridge_log()
                    return False
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            f"http://127.0.0.1:{self._bridge_port}/health",
                            timeout=aiohttp.ClientTimeout(total=2)
                        ) as resp:
                            if resp.status == 200:
                                http_ready = True
                                data = await resp.json()
                                if data.get("status") == "connected":
                                    print(f"[{self.name}] Bridge ready (status: connected)")
                                    break
                except Exception:
                    continue

            if not http_ready:
                print(f"[{self.name}] Bridge HTTP server did not start in 15s")
                print(f"[{self.name}] Check log: {self._bridge_log}")
                self._close_bridge_log()
                return False
            
            # Phase 2: HTTP is up but WhatsApp may still be connecting.
            # Give it more time to authenticate with saved credentials.
            if data.get("status") != "connected":
                print(f"[{self.name}] Bridge HTTP ready, waiting for WhatsApp connection...")
                for attempt in range(15):
                    await asyncio.sleep(1)
                    if self._bridge_process.poll() is not None:
                        print(f"[{self.name}] Bridge process died during connection")
                        print(f"[{self.name}] Check log: {self._bridge_log}")
                        self._close_bridge_log()
                        return False
                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.get(
                                f"http://127.0.0.1:{self._bridge_port}/health",
                                timeout=aiohttp.ClientTimeout(total=2)
                            ) as resp:
                                if resp.status == 200:
                                    data = await resp.json()
                                    if data.get("status") == "connected":
                                        print(f"[{self.name}] Bridge ready (status: connected)")
                                        break
                    except Exception:
                        continue
                else:
                    # Still not connected — warn but proceed (bridge may
                    # auto-reconnect later, e.g. after a code 515 restart).
                    print(f"[{self.name}] ⚠ WhatsApp not connected after 30s")
                    print(f"[{self.name}]   Bridge log: {self._bridge_log}")
                    print(f"[{self.name}]   If session expired, re-pair: hermes whatsapp")
            
            # Create a persistent HTTP session for all bridge communication
            self._http_session = aiohttp.ClientSession()

            # Start message polling task
            self._poll_task = asyncio.create_task(self._poll_messages())
            
            self._mark_connected()
            print(f"[{self.name}] Bridge started on port {self._bridge_port}")
            return True
            
        except Exception as e:
            logger.error("[%s] Failed to start bridge: %s", self.name, e, exc_info=True)
            return False
        finally:
            if not self._running:
                if lock_acquired:
                    self._release_platform_lock()
                self._close_bridge_log()
    
    def _close_bridge_log(self) -> None:
        """Close the bridge log file handle if open."""
        if self._bridge_log_fh:
            try:
                self._bridge_log_fh.close()
            except Exception:
                pass
            self._bridge_log_fh = None

    async def _check_managed_bridge_exit(self) -> Optional[str]:
        """Return a fatal error message if the managed bridge child exited."""
        if self._bridge_process is None:
            return None

        returncode = self._bridge_process.poll()
        if returncode is None:
            return None

        # Planned shutdown: disconnect() sets _shutting_down before it sends
        # SIGTERM to the bridge, so a returncode of -15 (SIGTERM), -2 (SIGINT),
        # or 0 (clean exit) at that point is expected, not a crash. Treat it
        # as informational and skip the fatal-error path.
        # getattr-with-default keeps tests that construct the adapter via
        # ``WhatsAppAdapter.__new__`` (bypassing __init__) working without
        # every _make_adapter() helper having to seed the attribute.
        if getattr(self, "_shutting_down", False) and returncode in {0, -2, -15}:
            logger.info(
                "[%s] Bridge exited during shutdown (code %d).",
                self.name,
                returncode,
            )
            return None

        message = f"WhatsApp bridge process exited unexpectedly (code {returncode})."
        if not self.has_fatal_error:
            logger.error("[%s] %s", self.name, message)
            self._set_fatal_error("whatsapp_bridge_exited", message, retryable=True)
            self._close_bridge_log()
            await self._notify_fatal_error()
        return self.fatal_error_message or message

    async def disconnect(self) -> None:
        """Stop the WhatsApp bridge and clean up any orphaned processes."""
        # Flip the shutdown flag BEFORE signalling the child so the exit-check
        # path (which runs from other tasks like send() and the poll loop)
        # doesn't race us and report the intentional termination as fatal.
        self._shutting_down = True
        if self._bridge_process:
            try:
                try:
                    _terminate_bridge_process(self._bridge_process, force=False)
                except (ProcessLookupError, PermissionError):
                    self._bridge_process.terminate()
                await asyncio.sleep(1)
                if self._bridge_process.poll() is None:
                    try:
                        _terminate_bridge_process(self._bridge_process, force=True)
                    except (ProcessLookupError, PermissionError):
                        self._bridge_process.kill()
            except Exception as e:
                print(f"[{self.name}] Error stopping bridge: {e}")
        else:
            # Bridge was not started by us, don't kill it
            print(f"[{self.name}] Disconnecting (external bridge left running)")

        # Clean up PID file
        try:
            (self._session_path / "bridge.pid").unlink(missing_ok=True)
        except OSError:
            pass

        # Cancel the poll task explicitly
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except (asyncio.CancelledError, Exception):
                pass
        self._poll_task = None

        # Close the persistent HTTP session
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
        self._http_session = None

        self._release_platform_lock()

        self._mark_disconnected()
        self._bridge_process = None
        self._close_bridge_log()
        print(f"[{self.name}] Disconnected")
    
    def format_message(self, content: str) -> str:
        """Convert standard markdown to WhatsApp-compatible formatting.

        WhatsApp supports: *bold*, _italic_, ~strikethrough~, ```code```,
        and monospaced `inline`. Standard markdown uses different syntax
        for bold/italic/strikethrough, so we convert here.

        Code blocks (``` fenced) and inline code (`) are protected from
        conversion via placeholder substitution.
        """
        if not content:
            return content

        # --- 1. Protect fenced code blocks from formatting changes ---
        _FENCE_PH = "\x00FENCE"
        fences: list[str] = []

        def _save_fence(m: re.Match) -> str:
            fences.append(m.group(0))
            return f"{_FENCE_PH}{len(fences) - 1}\x00"

        result = re.sub(r"```[\s\S]*?```", _save_fence, content)

        # --- 2. Protect inline code ---
        _CODE_PH = "\x00CODE"
        codes: list[str] = []

        def _save_code(m: re.Match) -> str:
            codes.append(m.group(0))
            return f"{_CODE_PH}{len(codes) - 1}\x00"

        result = re.sub(r"`[^`\n]+`", _save_code, result)

        # --- 3. Convert markdown formatting to WhatsApp syntax ---
        # Bold: **text** or __text__ → *text*
        result = re.sub(r"\*\*(.+?)\*\*", r"*\1*", result)
        result = re.sub(r"__(.+?)__", r"*\1*", result)
        # Strikethrough: ~~text~~ → ~text~
        result = re.sub(r"~~(.+?)~~", r"~\1~", result)
        # Italic: *text* is already WhatsApp italic — leave as-is
        # _text_ is already WhatsApp italic — leave as-is

        # --- 4. Convert markdown headers to bold text ---
        # # Header → *Header*
        result = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", result, flags=re.MULTILINE)

        # --- 5. Convert markdown links: [text](url) → text (url) ---
        result = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", result)

        # --- 6. Restore protected sections ---
        for i, fence in enumerate(fences):
            result = result.replace(f"{_FENCE_PH}{i}\x00", fence)
        for i, code in enumerate(codes):
            result = result.replace(f"{_CODE_PH}{i}\x00", code)

        return result

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> SendResult:
        """Send a message via the WhatsApp bridge.

        Formats markdown for WhatsApp, splits long messages into chunks
        that preserve code block boundaries, and sends each chunk sequentially.
        """
        if not self._running or not self._http_session:
            return SendResult(success=False, error="Not connected")
        bridge_exit = await self._check_managed_bridge_exit()
        if bridge_exit:
            return SendResult(success=False, error=bridge_exit)

        if not content or not content.strip():
            return SendResult(success=True, message_id=None)

        try:
            import aiohttp

            interactive_payload = None
            if isinstance(metadata, dict) and os.getenv("APEX_EXPERIMENTAL_WHATSAPP_INTERACTIVE", "false").lower() in {"1", "true", "yes", "on"}:
                interactive_payload = metadata.get("whatsapp_payload")
            if isinstance(interactive_payload, dict):
                payload: Dict[str, Any] = {
                    "chatId": chat_id,
                    "message": content,
                    "payload": interactive_payload,
                }
                if reply_to:
                    payload["replyTo"] = reply_to
                async with self._http_session.post(
                    f"http://127.0.0.1:{self._bridge_port}/send",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self._apex_record_agent_reply(chat_id, content)
                        return SendResult(success=True, message_id=data.get("messageId"))
                    error = await resp.text()
                    logger.warning("WhatsApp interactive send failed, falling back to text: %s", error)

            # Format and chunk the message
            formatted = self.format_message(content)
            chunks = self.truncate_message(formatted, self._outgoing_chunk_limit())

            last_message_id = None
            for chunk in chunks:
                payload: Dict[str, Any] = {
                    "chatId": chat_id,
                    "message": chunk,
                }
                if reply_to and last_message_id is None:
                    # Only reply-to on the first chunk
                    payload["replyTo"] = reply_to

                async with self._http_session.post(
                    f"http://127.0.0.1:{self._bridge_port}/send",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        last_message_id = data.get("messageId")
                    else:
                        error = await resp.text()
                        return SendResult(success=False, error=error)

                # Small delay between chunks to avoid rate limiting
                if len(chunks) > 1:
                    await asyncio.sleep(0.3)

            self._apex_record_agent_reply(chat_id, formatted)
            return SendResult(
                success=True,
                message_id=last_message_id,
            )
        except Exception as e:
            return SendResult(success=False, error=str(e))


            return SendResult(
                success=True,
                message_id=last_message_id,
            )
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_slash_confirm(
        self,
        chat_id: str,
        title: str,
        message: str,
        session_key: str,
        confirm_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        payload = {
            "type": "buttons",
            "text": message,
            "footer": title,
            "buttons": [
                {"id": f"/approve {confirm_id}", "text": "Approve Once"},
                {"id": f"/always {confirm_id}", "text": "Always Approve"},
                {"id": f"/cancel {confirm_id}", "text": "Cancel"},
            ],
        }
        send_metadata = dict(metadata or {})
        send_metadata["whatsapp_payload"] = payload
        return await self.send(chat_id, message, metadata=send_metadata)

    async def edit_message(
        self,
        chat_id: str,
        message_id: str,
        content: str,
        *,
        finalize: bool = False,
    ) -> SendResult:
        """Edit a previously sent message via the WhatsApp bridge."""
        if not self._running or not self._http_session:
            return SendResult(success=False, error="Not connected")
        bridge_exit = await self._check_managed_bridge_exit()
        if bridge_exit:
            return SendResult(success=False, error=bridge_exit)
        try:
            import aiohttp
            async with self._http_session.post(
                f"http://127.0.0.1:{self._bridge_port}/edit",
                json={
                    "chatId": chat_id,
                    "messageId": message_id,
                    "message": content,
                },
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    return SendResult(success=True, message_id=message_id)
                else:
                    error = await resp.text()
                    return SendResult(success=False, error=error)
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def _send_media_to_bridge(
        self,
        chat_id: str,
        file_path: str,
        media_type: str,
        caption: Optional[str] = None,
        file_name: Optional[str] = None,
    ) -> SendResult:
        """Send any media file via bridge /send-media endpoint."""
        if not self._running or not self._http_session:
            return SendResult(success=False, error="Not connected")
        bridge_exit = await self._check_managed_bridge_exit()
        if bridge_exit:
            return SendResult(success=False, error=bridge_exit)
        try:
            import aiohttp

            if not os.path.exists(file_path):
                return SendResult(success=False, error=f"File not found: {file_path}")

            payload: Dict[str, Any] = {
                "chatId": chat_id,
                "filePath": file_path,
                "mediaType": media_type,
            }
            if caption:
                payload["caption"] = caption
            if file_name:
                payload["fileName"] = file_name

            async with self._http_session.post(
                f"http://127.0.0.1:{self._bridge_port}/send-media",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return SendResult(
                        success=True,
                        message_id=data.get("messageId"),
                        raw_response=data,
                    )
                else:
                    error = await resp.text()
                    return SendResult(success=False, error=error)

        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_image(
        self,
        chat_id: str,
        image_url: str,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> SendResult:
        """Download image URL to cache, send natively via bridge."""
        try:
            local_path = await cache_image_from_url(image_url)
            return await self._send_media_to_bridge(chat_id, local_path, "image", caption)
        except Exception:
            return await super().send_image(chat_id, image_url, caption, reply_to)

    async def send_image_file(
        self,
        chat_id: str,
        image_path: str,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
        **kwargs,
    ) -> SendResult:
        """Send a local image file natively via bridge."""
        return await self._send_media_to_bridge(chat_id, image_path, "image", caption)

    async def send_video(
        self,
        chat_id: str,
        video_path: str,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
        **kwargs,
    ) -> SendResult:
        """Send a video natively via bridge — plays inline in WhatsApp."""
        return await self._send_media_to_bridge(chat_id, video_path, "video", caption)

    async def send_voice(
        self,
        chat_id: str,
        audio_path: str,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
        **kwargs,
    ) -> SendResult:
        """Send an audio file as a WhatsApp voice message via bridge."""
        return await self._send_media_to_bridge(chat_id, audio_path, "audio", caption)

    async def send_document(
        self,
        chat_id: str,
        file_path: str,
        caption: Optional[str] = None,
        file_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        **kwargs,
    ) -> SendResult:
        """Send a document/file as a downloadable attachment via bridge."""
        return await self._send_media_to_bridge(
            chat_id, file_path, "document", caption,
            file_name or os.path.basename(file_path),
        )

    async def send_typing(self, chat_id: str, metadata=None) -> None:
        """Send typing indicator via bridge."""
        if not self._running or not self._http_session:
            return
        if await self._check_managed_bridge_exit():
            return
        
        try:
            import aiohttp

            # Must wrap in `async with` — a bare `await session.post(...)`
            # leaves the response object alive until GC, holding its TCP
            # socket in CLOSE_WAIT. See #18451.
            async with self._http_session.post(
                f"http://127.0.0.1:{self._bridge_port}/typing",
                json={"chatId": chat_id},
                timeout=aiohttp.ClientTimeout(total=5)
            ):
                pass
        except Exception:
            pass  # Ignore typing indicator failures
    
    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        """Get information about a WhatsApp chat."""
        if not self._running or not self._http_session:
            return {"name": "Unknown", "type": "dm"}
        if await self._check_managed_bridge_exit():
            return {"name": chat_id, "type": "dm"}
        
        try:
            import aiohttp

            async with self._http_session.get(
                f"http://127.0.0.1:{self._bridge_port}/chat/{chat_id}",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        "name": data.get("name", chat_id),
                        "type": "group" if data.get("isGroup") else "dm",
                        "participants": data.get("participants", []),
                    }
        except Exception as e:
            logger.debug("Could not get WhatsApp chat info for %s: %s", chat_id, e)
        
        return {"name": chat_id, "type": "dm"}
    
    async def _poll_messages(self) -> None:
        """Poll the bridge for incoming messages."""
        import aiohttp

        while self._running:
            if not self._http_session:
                break
            bridge_exit = await self._check_managed_bridge_exit()
            if bridge_exit:
                print(f"[{self.name}] {bridge_exit}")
                break
            try:
                async with self._http_session.get(
                    f"http://127.0.0.1:{self._bridge_port}/messages",
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 200:
                        messages = await resp.json()
                        for msg_data in messages:
                            event = await self._build_message_event(msg_data)
                            if event:
                                await self.handle_message(event)
            except asyncio.CancelledError:
                break
            except Exception as e:
                bridge_exit = await self._check_managed_bridge_exit()
                if bridge_exit:
                    print(f"[{self.name}] {bridge_exit}")
                    break
                print(f"[{self.name}] Poll error: {e}")
                await asyncio.sleep(5)
            
            await asyncio.sleep(1)  # Poll interval
    
    async def _build_message_event(self, data: Dict[str, Any]) -> Optional[MessageEvent]:
        """Build a MessageEvent from bridge message data, downloading images to cache."""
        try:
            if not self._should_process_message(data):
                return None

            # Determine message type
            msg_type = MessageType.TEXT
            if data.get("hasMedia"):
                media_type = data.get("mediaType", "")
                if "image" in media_type:
                    msg_type = MessageType.PHOTO
                elif "video" in media_type:
                    msg_type = MessageType.VIDEO
                elif "audio" in media_type or "ptt" in media_type:  # ptt = voice note
                    msg_type = MessageType.VOICE
                else:
                    msg_type = MessageType.DOCUMENT
            
            # Determine chat type
            is_group = data.get("isGroup", False)
            chat_type = "group" if is_group else "dm"
            
            # Build source
            source = self.build_source(
                chat_id=data.get("chatId", ""),
                chat_name=data.get("chatName"),
                chat_type=chat_type,
                user_id=data.get("senderId"),
                user_name=data.get("senderName"),
            )
            
            # Download media URLs to the local cache so agent tools
            # can access them reliably regardless of URL expiration.
            raw_urls = data.get("mediaUrls", [])
            cached_urls = []
            media_types = []
            for url in raw_urls:
                if msg_type == MessageType.PHOTO and url.startswith(("http://", "https://")):
                    try:
                        cached_path = await cache_image_from_url(url, ext=".jpg")
                        cached_urls.append(cached_path)
                        media_types.append("image/jpeg")
                        print(f"[{self.name}] Cached user image: {cached_path}", flush=True)
                    except Exception as e:
                        print(f"[{self.name}] Failed to cache image: {e}", flush=True)
                        cached_urls.append(url)
                        media_types.append("image/jpeg")
                elif msg_type == MessageType.PHOTO and os.path.isabs(url):
                    # Local file path — bridge already downloaded the image
                    cached_urls.append(url)
                    media_types.append("image/jpeg")
                    print(f"[{self.name}] Using bridge-cached image: {url}", flush=True)
                elif msg_type == MessageType.VOICE and url.startswith(("http://", "https://")):
                    try:
                        cached_path = await cache_audio_from_url(url, ext=".ogg")
                        cached_urls.append(cached_path)
                        media_types.append("audio/ogg")
                        print(f"[{self.name}] Cached user voice: {cached_path}", flush=True)
                    except Exception as e:
                        print(f"[{self.name}] Failed to cache voice: {e}", flush=True)
                        cached_urls.append(url)
                        media_types.append("audio/ogg")
                elif msg_type == MessageType.VOICE and os.path.isabs(url):
                    # Local file path — bridge already downloaded the audio
                    cached_urls.append(url)
                    media_types.append("audio/ogg")
                    print(f"[{self.name}] Using bridge-cached audio: {url}", flush=True)
                elif msg_type == MessageType.DOCUMENT and os.path.isabs(url):
                    # Local file path — bridge already downloaded the document
                    cached_urls.append(url)
                    ext = Path(url).suffix.lower()
                    mime = SUPPORTED_DOCUMENT_TYPES.get(ext, "application/octet-stream")
                    media_types.append(mime)
                    print(f"[{self.name}] Using bridge-cached document: {url}", flush=True)
                elif msg_type == MessageType.VIDEO and os.path.isabs(url):
                    cached_urls.append(url)
                    media_types.append("video/mp4")
                    print(f"[{self.name}] Using bridge-cached video: {url}", flush=True)
                else:
                    cached_urls.append(url)
                    media_types.append("unknown")

            # For text-readable documents, inject file content directly into
            # the message text so the agent can read it inline.
            # Cap at 100KB to match Telegram/Discord/Slack behaviour.
            body = data.get("body", "")
            if data.get("isGroup"):
                body = self._clean_bot_mention_text(body, data)
            MAX_TEXT_INJECT_BYTES = 100 * 1024
            if msg_type == MessageType.DOCUMENT and cached_urls:
                for doc_path in cached_urls:
                    ext = Path(doc_path).suffix.lower()
                    if ext in {".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml", ".log", ".py", ".js", ".ts", ".html", ".css"}:
                        try:
                            file_size = Path(doc_path).stat().st_size
                            if file_size > MAX_TEXT_INJECT_BYTES:
                                print(f"[{self.name}] Skipping text injection for {doc_path} ({file_size} bytes > {MAX_TEXT_INJECT_BYTES})", flush=True)
                                continue
                            content = Path(doc_path).read_text(encoding="utf-8", errors="replace")
                            fname = Path(doc_path).name
                            # Remove the doc_<hex>_ prefix for display
                            display_name = fname
                            if "_" in fname:
                                parts = fname.split("_", 2)
                                if len(parts) >= 3:
                                    display_name = parts[2]
                            injection = f"[Content of {display_name}]:\n{content}"
                            if body:
                                body = f"{injection}\n\n{body}"
                            else:
                                body = injection
                            print(f"[{self.name}] Injected text content from: {doc_path}", flush=True)
                        except Exception as e:
                            print(f"[{self.name}] Failed to read document text: {e}", flush=True)

            apex_mode, apex_changed, apex_show_onboarding_menu, apex_show_returning_menu, apex_state = self._apex_mode_for_inbound_text(str(source.chat_id), body)
            apex_memory_context = self._apex_compose_memory_context(apex_state)
            apex_prompt = APEX_MODE_PROMPTS.get(apex_mode, APEX_MODE_PROMPTS["general"])
            if apex_memory_context:
                apex_prompt = apex_prompt + "\n\n" + apex_memory_context
            if apex_show_onboarding_menu:
                body = APEX_ONBOARDING_MENU_TEXT
            elif apex_show_returning_menu:
                mode_label = "UPSC Mentor" if apex_mode == "upsc" else "General AI"
                body = APEX_RETURNING_MENU_TEMPLATE.format(mode_label=mode_label)
            elif apex_changed:
                if apex_mode == "upsc":
                    body = "Mode: UPSC Mentor. Ask your next question."
                else:
                    body = "Mode: General AI. Ask your next question."


        except Exception as e:
            print(f"[{self.name}] Error building event: {e}")
            return None
