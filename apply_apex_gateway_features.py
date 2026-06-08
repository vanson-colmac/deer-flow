#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path('/home/market/.hermes/hermes-agent')
WHATSAPP = ROOT / 'gateway/platforms/whatsapp.py'
BRIDGE = ROOT / 'scripts/whatsapp-bridge/bridge.js'
URL_SAFETY = ROOT / 'tools/url_safety.py'
WEB_TOOLS = ROOT / 'tools/web_tools.py'
WEB_SERVER = ROOT / 'hermes_cli/web_server.py'
WEB_APP = ROOT / 'web/src/App.tsx'
AUTO_UPDATE = Path('/home/market/.hermes/auto-update.sh')


def read(path):
    return path.read_text(encoding='utf-8')


def write(path, text):
    path.write_text(text, encoding='utf-8')


def patch_whatsapp_adapter():
    path = WHATSAPP
    text = read(path)
    original = text
    changes = 0

    if 'import json\n' not in text:
        text = text.replace('import asyncio\n', 'import asyncio\nimport json\n', 1)
        changes += 1

    if 'APEX_MODE_PROMPTS = {' not in text:
        anchor = '    SUPPORTED_DOCUMENT_TYPES,\n    cache_image_from_url,\n    cache_audio_from_url,\n)\n'
        injected = (
            '    SUPPORTED_DOCUMENT_TYPES,\n    cache_image_from_url,\n    cache_audio_from_url,\n)\n\n'
            'APEX_PATCH_MODE_PROMPT = True\n\n'
            'APEX_MODE_PROMPTS = {\n'
            '    "general": "Apex runtime mode: General AI. Answer as a white-labeled general assistant. Do not mention Hermes, Claude, internal tools, providers, model names, context windows, or backend routing. If live facts are needed, use the available web search/extract tools instead of claiming source access is blocked.",\n'
            '    "upsc": "Apex runtime mode: LBSNAA UPSC Mentor. Stay strictly in UPSC mentor mode. Use the UPSC teacher context and answer like a disciplined civil-services mentor. Prioritize syllabus relevance, exam utility, current-policy context, PYQ-style framing, and concise study guidance. Do not drift into general/god-mode behavior. If live facts are needed, use the available web search/extract tools instead of claiming source access is blocked.",\n'
            '}\n\n'
            'APEX_ONBOARDING_MENU_TEXT = "⚡ Apex AI Gateway\\n\\nChoose your mode:\\n1. General AI — ask, research, write, code, plan\\n2. UPSC Mentor — strict exam preparation mode\\n\\nReply with: 1, 2, general, or upsc.\\nUse menu anytime to see this again."\n'
            'APEX_RETURNING_MENU_TEMPLATE = "⚡ Apex AI Gateway\\n\\nCurrent mode: {mode_label}\\n\\nChoose your mode:\\n1. General AI — ask, research, write, code, plan\\n2. UPSC Mentor — strict exam preparation mode\\n\\nReply with: 1, 2, general, or upsc. Or keep chatting in your current mode."\n'
        )
        if anchor not in text:
            raise RuntimeError('whatsapp.py import anchor for Apex constants not found')
        text = text.replace(anchor, injected, 1)
        changes += 1

    if 'self._apex_memory_message_limit' not in text:
        text = text.replace(
            '        self._shutting_down: bool = False\n',
            '        self._shutting_down: bool = False\n'
            '        self._apex_user_state_path = self._session_path.parent / "apex_users.sqlite3"\n'
            '        self._apex_mode_state_path = self._session_path.parent / "apex_modes.json"\n'
            '        self._apex_memory_message_limit = 1536\n'
            '        self._apex_memory_summary_limit = 3072\n'
            '        self._apex_ensure_user_state_db()\n',
            1,
        )
        changes += 1

    helper_marker = '    def _apex_db_connection(self) -> sqlite3.Connection:'
    if helper_marker not in text:
        insert_before = '    def _effective_reply_prefix(self) -> str:\n'
        helpers = '''    def _apex_db_connection(self) -> sqlite3.Connection:
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
        return self._apex_trim_memory_text("\n".join(lines[:6]), 720)

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
        return self._apex_trim_memory_text("\n".join(compact), self._apex_memory_summary_limit)

    def _apex_compose_memory_context(self, state: Optional[Dict[str, Any]]) -> str:
        if not state:
            return ""
        parts = []
        if state.get("conversation_summary"):
            parts.append("Persistent user context:\n" + state["conversation_summary"])
        if state.get("last_user_message"):
            parts.append("Previous user message:\n" + state["last_user_message"])
        if state.get("last_agent_reply"):
            parts.append("Previous assistant reply:\n" + state["last_agent_reply"])
        return "\n\n".join(parts).strip()

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

'''
        if insert_before not in text:
            raise RuntimeError('whatsapp.py insert point for Apex helpers not found')
        text = text.replace(insert_before, helpers + insert_before, 1)
        changes += 1

    old_return = '''            return MessageEvent(
                text=body,
                message_type=msg_type,
                source=source,
                raw_message=data,
                message_id=data.get("messageId"),
                media_urls=cached_urls,
                media_types=media_types,
            )'''
    new_return = '''            apex_mode, apex_changed, apex_show_onboarding_menu, apex_show_returning_menu, apex_state = self._apex_mode_for_inbound_text(str(source.chat_id), body)
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

'''
    if 'apex_show_returning_menu' not in text:
        if old_return not in text:
            raise RuntimeError('whatsapp.py MessageEvent return pattern not found')
        text = text.replace(old_return, new_return, 1)
        changes += 1

    old_send = '''            # Format and chunk the message
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
'''
    new_send = '''            interactive_payload = None
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

'''
    if 'self._apex_record_agent_reply(chat_id, formatted)' not in text:
        if old_send not in text:
            raise RuntimeError('whatsapp.py send chunk pattern not found')
        text = text.replace(old_send, new_send, 1)
        changes += 1

    if 'async def send_slash_confirm(' not in text:
        insert_before = '    async def edit_message(\n'
        method = '''    async def send_slash_confirm(
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

'''
        if insert_before not in text:
            raise RuntimeError('whatsapp.py insert point for send_slash_confirm not found')
        text = text.replace(insert_before, method + insert_before, 1)
        changes += 1


    aux_target = '        effective_model = model or _get_default_summarizer_model()\n        auxiliary_available = check_auxiliary_model()\n        \n        # Process each result with LLM if enabled\n        if use_llm_processing and auxiliary_available:\n'
    aux_replacement = '        effective_model = (model or _get_default_summarizer_model()) if use_llm_processing else None\n        auxiliary_available = check_auxiliary_model() if use_llm_processing else False\n        \n        # Process each result with LLM if enabled\n        if use_llm_processing and auxiliary_available:\n'
    if aux_target in text:
        text = text.replace(aux_target, aux_replacement, 1)
        changes += 1
    if text != original:
        write(path, text)
    print(f"  [whatsapp] {'applied ' + str(changes) + ' change(s)' if changes else 'already patched'}")


def patch_bridge():
    path = BRIDGE
    text = read(path)
    original = text
    changes = 0

    import_old = "import { makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion, downloadMediaMessage } from '@whiskeysockets/baileys';"
    import_new = "import { makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion, downloadMediaMessage, generateWAMessageFromContent, proto } from '@whiskeysockets/baileys';"
    if 'generateWAMessageFromContent, proto' not in text:
        if import_old not in text:
            raise RuntimeError('bridge.js Baileys import pattern not found')
        text = text.replace(import_old, import_new, 1)
        changes += 1

    helper_marker = 'async function sendNativeInteractiveMessage(chatId, input, fallbackText) {'
    if helper_marker not in text:
        insert_before = 'function buildAllowedInteractivePayload(input, fallbackText) {'
        helper = "async function sendNativeInteractiveMessage(chatId, input, fallbackText) {\n  if (!input || typeof input !== 'object') return null;\n  const type = input.type || input.kind;\n\n  let rows = [];\n  if (type === 'list' && Array.isArray(input.sections)) {\n    for (const section of input.sections.slice(0, 10)) {\n      for (const row of (section.rows || []).slice(0, 10)) {\n        rows.push({\n          header: String(section.title || '').slice(0, 60),\n          title: String(row.title || row.text || 'Option').slice(0, 60),\n          description: row.description ? String(row.description).slice(0, 72) : '',\n          id: String(row.id || row.rowId || row.title || `apex_${rows.length + 1}`).slice(0, 256),\n        });\n      }\n    }\n  } else if (type === 'buttons' && Array.isArray(input.buttons)) {\n    rows = input.buttons.slice(0, 10).map((button, idx) => ({\n      header: 'Apex mode',\n      title: String(button.text || button.displayText || `Option ${idx + 1}`).slice(0, 60),\n      description: idx === 0 ? 'General assistant mode' : 'UPSC preparation mentor mode',\n      id: String(button.id || button.buttonId || `apex_${idx + 1}`).slice(0, 256),\n    }));\n  }\n  if (!rows.length) return null;\n\n  const content = {\n    viewOnceMessage: {\n      message: {\n        messageContextInfo: {\n          deviceListMetadata: {},\n          deviceListMetadataVersion: 2,\n        },\n        interactiveMessage: proto.Message.InteractiveMessage.create({\n          body: proto.Message.InteractiveMessage.Body.create({\n            text: String(input.text || fallbackText || '').slice(0, 4096),\n          }),\n          footer: proto.Message.InteractiveMessage.Footer.create({\n            text: input.footer ? String(input.footer).slice(0, 120) : '',\n          }),\n          nativeFlowMessage: proto.Message.InteractiveMessage.NativeFlowMessage.create({\n            buttons: [{\n              name: 'single_select',\n              buttonParamsJson: JSON.stringify({\n                title: String(input.buttonText || 'Choose mode').slice(0, 20),\n                sections: [{\n                  title: String(input.title || 'Apex AI Gateway').slice(0, 60),\n                  rows,\n                }],\n              }),\n            }],\n          }),\n        }),\n      },\n    },\n  };\n\n  const waMessage = generateWAMessageFromContent(chatId, content, { userJid: sock.user?.id });\n  await sock.relayMessage(chatId, waMessage.message, { messageId: waMessage.key.id });\n  trackSentMessageId(waMessage);\n  return waMessage;\n}\n\n"
        if insert_before not in text:
            raise RuntimeError('bridge.js helper insert point not found')
        text = text.replace(insert_before, helper + insert_before, 1)
        changes += 1

    old_send = '    const interactivePayload = buildAllowedInteractivePayload(payload, message);\n    if (interactivePayload) {\n      const sent = await sock.sendMessage(chatId, interactivePayload);\n      trackSentMessageId(sent);\n      return res.json({ success: true, messageId: sent?.key?.id, messageIds: sent?.key?.id ? [sent.key.id] : [] });\n    }\n'
    new_send = '    const nativeInteractive = await sendNativeInteractiveMessage(chatId, payload, message);\n    if (nativeInteractive) {\n      return res.json({ success: true, messageId: nativeInteractive?.key?.id, messageIds: nativeInteractive?.key?.id ? [nativeInteractive.key.id] : [] });\n    }\n\n    const interactivePayload = buildAllowedInteractivePayload(payload, message);\n    if (interactivePayload) {\n      const sent = await sock.sendMessage(chatId, interactivePayload);\n      trackSentMessageId(sent);\n      return res.json({ success: true, messageId: sent?.key?.id, messageIds: sent?.key?.id ? [sent.key.id] : [] });\n    }\n'
    if 'const nativeInteractive = await sendNativeInteractiveMessage(chatId, payload, message);' not in text:
        if old_send not in text:
            raise RuntimeError('bridge.js interactive send branch not found')
        text = text.replace(old_send, new_send, 1)
        changes += 1

    if text != original:
        write(path, text)
    print(f"  [bridge] {'applied ' + str(changes) + ' change(s)' if changes else 'already patched'}")


def patch_url_safety():
    path = URL_SAFETY
    text = read(path)
    original = text
    changes = 0
    target = '''        except socket.gaierror:
            # DNS resolution failed — fail closed. If DNS can't resolve it,
            # the HTTP client will also fail, so blocking loses nothing.
            logger.warning("Blocked request — DNS resolution failed for: %s", hostname)
            return False
'''
    replacement = '''        except socket.gaierror:
            logger.warning("URL safety DNS preflight failed for public hostname, allowing HTTP client to decide: %s", hostname)
            return True
'''
    if 'allowing HTTP client to decide' not in text:
        if target not in text:
            raise RuntimeError('url_safety.py DNS failure pattern not found')
        text = text.replace(target, replacement, 1)
        changes += 1
    if text != original:
        write(path, text)
    print(f"  [url_safety] {'applied ' + str(changes) + ' change(s)' if changes else 'already patched'}")


def patch_web_tools():
    path = WEB_TOOLS
    text = read(path)
    original = text
    changes = 0

    target = '''            elif backend in {"searxng", "brave-free", "ddgs"}:
                # These backends are search-only — they cannot extract URL content
                _label = {"searxng": "SearXNG", "brave-free": "Brave Search (free tier)", "ddgs": "DuckDuckGo (ddgs)"}[backend]
                return json.dumps({
                    "success": False,
                    "error": f"{_label} is a search-only backend and cannot extract URL content. "
                             "Set web.extract_backend to firecrawl, tavily, exa, or parallel.",
                }, ensure_ascii=False)
'''
    replacement = '''            elif backend in {"searxng", "brave-free", "ddgs"}:
                logger.info("Using local HTTP extraction fallback for search-only backend %s", backend)
                from tools.interrupt import is_interrupted as _is_interrupted
                from html.parser import HTMLParser
                from urllib.parse import urljoin
                import requests

                class _ApexHTMLTextExtractor(HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self.in_title = False
                        self.skip_depth = 0
                        self.title_parts = []
                        self.text_parts = []

                    def handle_starttag(self, tag, attrs):
                        tag = tag.lower()
                        if tag == "title":
                            self.in_title = True
                        if tag in {"script", "style", "noscript"}:
                            self.skip_depth += 1
                        if tag in {"p", "div", "section", "article", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "br"}:
                            self.text_parts.append("
")
                        if tag == "a":
                            href = dict(attrs).get("href")
                            if href:
                                self.text_parts.append(" ")

                    def handle_endtag(self, tag):
                        tag = tag.lower()
                        if tag == "title":
                            self.in_title = False
                        if tag in {"script", "style", "noscript"} and self.skip_depth:
                            self.skip_depth -= 1
                        if tag in {"p", "div", "section", "article", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6"}:
                            self.text_parts.append("
")

                    def handle_data(self, data):
                        if self.skip_depth:
                            return
                        cleaned = " ".join(data.split())
                        if not cleaned:
                            return
                        if self.in_title:
                            self.title_parts.append(cleaned)
                        self.text_parts.append(cleaned)

                    def as_result(self):
                        title = " ".join(self.title_parts).strip()
                        content = "
".join(line.strip() for line in " ".join(self.text_parts).splitlines() if line.strip())
                        return title, content.strip()

                requested_no_llm = format == "html"
                results = []
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://www.google.com/",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                }
                for url in safe_urls:
                    if _is_interrupted():
                        results.append({"url": url, "error": "Interrupted", "title": ""})
                        continue
                    blocked = check_website_access(url)
                    if blocked:
                        results.append({"url": url, "title": "", "content": "", "error": blocked["message"], "blocked_by_policy": {"host": blocked["host"], "rule": blocked["rule"], "source": blocked["source"]}})
                        continue
                    try:
                        response = await asyncio.wait_for(asyncio.to_thread(requests.get, url, headers=headers, timeout=30, allow_redirects=True), timeout=45)
                    except asyncio.TimeoutError:
                        results.append({"url": url, "title": "", "content": "", "raw_content": "", "error": "Local extract timed out after 45s — page may be too large or unresponsive. Try browser_navigate instead."})
                        continue
                    except Exception as fetch_err:
                        results.append({"url": url, "title": "", "content": "", "raw_content": "", "error": str(fetch_err)})
                        continue
                    try:
                        response.raise_for_status()
                    except Exception as http_err:
                        results.append({"url": url, "title": "", "content": "", "raw_content": "", "error": str(http_err)})
                        continue
                    final_url = response.url or url
                    final_blocked = check_website_access(final_url)
                    if final_blocked:
                        results.append({"url": final_url, "title": "", "content": "", "raw_content": "", "error": final_blocked["message"], "blocked_by_policy": {"host": final_blocked["host"], "rule": final_blocked["rule"], "source": final_blocked["source"]}})
                        continue
                    content_type = response.headers.get("Content-Type", "")
                    body = response.text or ""
                    if "html" not in content_type.lower() and "<html" not in body.lower():
                        cleaned = body.strip()
                        if not cleaned:
                            results.append({"url": final_url, "title": "", "content": "", "raw_content": "", "error": "Local extract received non-HTML content without readable text"})
                            continue
                        results.append({"url": final_url, "title": "", "content": cleaned, "raw_content": cleaned, "metadata": {"content_type": content_type}})
                        continue
                    parser = _ApexHTMLTextExtractor()
                    try:
                        parser.feed(body)
                    except Exception as parse_err:
                        results.append({"url": final_url, "title": "", "content": "", "raw_content": "", "error": str(parse_err)})
                        continue
                    title, extracted = parser.as_result()
                    if requested_no_llm:
                        chosen = body
                    else:
                        chosen = extracted
                    if not chosen:
                        results.append({"url": final_url, "title": title, "content": "", "raw_content": "", "error": "Local extract could not parse page content"})
                        continue
                    results.append({"url": final_url, "title": title, "content": chosen, "raw_content": chosen, "metadata": {"title": title, "content_type": content_type}})
'''
    if 'Using local HTTP extraction fallback for search-only backend' in text and 'compatible; ApexGatewayBot/1.0' in text:
        legacy_start = text.index('            elif backend in {"searxng", "brave-free", "ddgs"}:')
        firecrawl_start = text.index('            else:\n                # ── Firecrawl extraction ──', legacy_start)
        text = text[:legacy_start] + replacement + text[firecrawl_start:]
        changes += 1
    elif 'Using local HTTP extraction fallback for search-only backend' not in text:
        if target not in text:
            raise RuntimeError('web_tools.py search-only extract branch not found')
        text = text.replace(target, replacement, 1)
        changes += 1
    if text != original:
        write(path, text)
    status = 'applied ' + str(changes) + ' change(s)' if changes else 'already patched'
    print('  [web_tools] ' + status)


def patch_web_server():
    path = WEB_SERVER
    text = read(path)
    if '@app.get("/api/apex/summary")' in text and '@app.get("/api/apex/timeline")' in text and 'restore_default_mode' in text and 'reset_user_scoped' in text and '@app.get("/api/apex/export/operator-summary")' in text:
        print(f'no changes needed for {path}')
        return
    anchor = '# ---------------------------------------------------------------------------\n# Token / cost analytics endpoint\n# ---------------------------------------------------------------------------\n'
    replacement = '# ---------------------------------------------------------------------------\n# Apex WhatsApp dashboard endpoints\n# ---------------------------------------------------------------------------\n\nclass ApexUserAction(BaseModel):\n    chat_id: str\n\nclass ApexUserRecoveryAction(BaseModel):\n    chat_id: str\n    action: str = ""\n\nclass ApexContextSimulationRequest(BaseModel):\n    chat_id: str\n    proposed_mode: str = ""\n    proposed_stable_memory: str = ""\n    proposed_conversation_summary: str = ""\n\ndef _apex_db_path() -> Path:\n    configured = os.getenv("APEX_USERS_DB")\n    if configured:\n        return Path(configured).expanduser()\n    primary = get_hermes_home() / "profiles" / "whatsapp-god" / "whatsapp" / "apex_users.sqlite3"\n    if primary.exists():\n        return primary\n    fallback = Path("/home/market/.hermes/profiles/whatsapp-god/whatsapp/apex_users.sqlite3")\n    return fallback if fallback.exists() else primary\n\ndef _apex_connect():\n    import sqlite3\n    conn = sqlite3.connect(_apex_db_path())\n    conn.row_factory = sqlite3.Row\n    return conn\n\ndef _apex_table_exists(conn, name: str) -> bool:\n    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name=?", (name,)).fetchone()\n    return bool(row)\n\ndef _apex_scalar(conn, sql: str, params: tuple = ()) -> int:\n    row = conn.execute(sql, params).fetchone()\n    if not row:\n        return 0\n    return int(row[0] or 0)\n\ndef _apex_ensure_admin_audit_log(conn) -> None:\n    conn.execute(\n        """\n        CREATE TABLE IF NOT EXISTS apex_admin_audit_log (\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            chat_id TEXT NOT NULL,\n            action TEXT NOT NULL,\n            created_at TEXT NOT NULL,\n            before_json TEXT NOT NULL DEFAULT \'\',\n            after_json TEXT NOT NULL DEFAULT \'\',\n            status TEXT NOT NULL DEFAULT \'ok\'\n        )\n        """\n    )\n    conn.execute("CREATE INDEX IF NOT EXISTS idx_apex_admin_audit_log_chat_time ON apex_admin_audit_log(chat_id, created_at)")\n\ndef _apex_user_snapshot(conn, chat_id: str) -> dict:\n    row = conn.execute("SELECT * FROM apex_users WHERE chat_id = ?", (chat_id,)).fetchone()\n    return dict(row) if row else {}\n\ndef _apex_insert_audit(conn, chat_id: str, action: str, before: dict, after: dict, status: str = "ok") -> None:\n    import json\n    from datetime import datetime\n    _apex_ensure_admin_audit_log(conn)\n    conn.execute(\n        """\n        INSERT INTO apex_admin_audit_log (chat_id, action, created_at, before_json, after_json, status)\n        VALUES (?, ?, ?, ?, ?, ?)\n        """,\n        (chat_id, action, datetime.utcnow().replace(microsecond=0).isoformat() + \'Z\', json.dumps(before, sort_keys=True, default=str), json.dumps(after, sort_keys=True, default=str), status),\n    )\n\ndef _apex_refresh_identity_from_session(conn, chat_id: str) -> dict:\n    from datetime import datetime\n    session_dir = _apex_db_path().parent / "session"\n    lid_to_phone = {}\n    for path in session_dir.glob("lid-mapping-*.json"):\n        phone = path.name[len("lid-mapping-"):-len(".json")]\n        try:\n            lid = path.read_text(encoding="utf-8").strip().strip(\'"\')\n        except Exception:\n            continue\n        if lid:\n            lid_to_phone[str(lid)] = phone\n    base = chat_id.split("@", 1)[0] if "@" in chat_id else chat_id\n    phone = lid_to_phone.get(base, "")\n    jid_kind = chat_id.split("@", 1)[1] if "@" in chat_id else ""\n    if phone or jid_kind:\n        conn.execute(\n            """\n            UPDATE apex_users\n            SET phone_number = COALESCE(NULLIF(phone_number, \'\'), ?),\n                chat_phone = COALESCE(NULLIF(chat_phone, \'\'), ?),\n                sender_id = COALESCE(NULLIF(sender_id, \'\'), ?),\n                sender_phone = COALESCE(NULLIF(sender_phone, \'\'), ?),\n                chat_jid_kind = COALESCE(NULLIF(chat_jid_kind, \'\'), ?),\n                sender_jid_kind = COALESCE(NULLIF(sender_jid_kind, \'\'), ?),\n                identity_source = ?,\n                identity_refreshed_at = ?\n            WHERE chat_id = ?\n            """,\n            (phone, phone, chat_id, phone, jid_kind, jid_kind, "session_lid_mapping" if phone else "jid_derivation", datetime.utcnow().replace(microsecond=0).isoformat() + \'Z\', chat_id),\n        )\n    return {"phone": phone, "jid_kind": jid_kind, "source": "session_lid_mapping" if phone else "jid_derivation"}\n\ndef _apex_identity_confidence(user: dict) -> dict:\n    source = str(user.get("identity_source") or "").strip()\n    phone = str(user.get("phone_number") or user.get("chat_phone") or user.get("sender_phone") or "").strip()\n    jid_kind = str(user.get("chat_jid_kind") or user.get("sender_jid_kind") or "").strip()\n    display = str(user.get("display_name") or user.get("chat_name") or user.get("sender_name") or "").strip()\n    refreshed = str(user.get("identity_refreshed_at") or "").strip()\n    score = 20\n    reasons = []\n    if phone:\n        score += 35\n        reasons.append("phone mapped")\n    else:\n        reasons.append("phone missing")\n    if jid_kind:\n        score += 15\n        reasons.append("jid classified")\n    else:\n        reasons.append("jid kind missing")\n    if display:\n        score += 15\n        reasons.append("display name present")\n    else:\n        reasons.append("display name missing")\n    if source == "live_bridge_payload":\n        score += 15\n        label = "high"\n    elif source == "session_lid_mapping":\n        score += 10\n        label = "good"\n    elif source == "jid_derivation":\n        score += 5\n        label = "derived"\n    else:\n        label = "low"\n        reasons.append("provenance missing")\n    if not refreshed:\n        reasons.append("never refreshed")\n    score = max(0, min(score, 100))\n    if score >= 80:\n        label = "high"\n    elif score >= 60:\n        label = "good"\n    elif score >= 35:\n        label = "partial"\n    else:\n        label = "low"\n    return {"score": score, "label": label, "source": source or "unknown", "reasons": reasons, "phone": phone, "jid_kind": jid_kind, "display_name": display, "refreshed_at": refreshed}\n\ndef _apex_attach_identity_confidence(user: dict) -> dict:\n    user["identity_confidence"] = _apex_identity_confidence(user)\n    if "_apex_memory_qa" in globals():\n        user["memory_qa"] = _apex_memory_qa(user)\n    return user\n\ndef _apex_memory_qa(user: dict) -> dict:\n    stable = str(user.get("stable_memory") or "").strip()\n    summary = str(user.get("conversation_summary") or "").strip()\n    last_user = str(user.get("last_user_message") or "").strip()\n    last_reply = str(user.get("last_agent_reply") or "").strip()\n    mode = str(user.get("current_mode") or "general").strip().lower()\n    score = 100\n    findings = []\n    warnings = []\n    if not stable:\n        score -= 25\n        findings.append({"severity": "warning", "label": "Stable memory missing", "detail": "No durable preference/profile memory is stored for this user."})\n    if not summary:\n        score -= 25\n        findings.append({"severity": "warning", "label": "Continuity summary missing", "detail": "Conversation summary is empty, so continuity depends only on latest exchange."})\n    if not last_user:\n        score -= 15\n        findings.append({"severity": "info", "label": "Latest user message missing", "detail": "No latest inbound message is captured."})\n    if not last_reply:\n        score -= 15\n        findings.append({"severity": "info", "label": "Latest assistant reply missing", "detail": "No latest outbound reply is captured."})\n    if stable and summary:\n        stable_lines = [line.strip().lower() for line in stable.splitlines() if line.strip()]\n        summary_l = summary.lower()\n        overlap = sum(1 for line in stable_lines if line[:40] and line[:40] in summary_l)\n        if overlap == 0:\n            score -= 15\n            findings.append({"severity": "warning", "label": "Stable memory not reflected in summary", "detail": "Stable profile facts do not appear in the compact continuity summary."})\n    if mode == "upsc" and "upsc" not in (stable + "\\n" + summary).lower():\n        score -= 10\n        findings.append({"severity": "info", "label": "UPSC mode has weak profile context", "detail": "UPSC mode is active but stored memory has little exam-prep context."})\n    combined = (stable + "\\n" + summary).lower()\n    for field in ["name", "language", "optional", "subject", "target"]:\n        if field in combined:\n            warnings.append(field)\n    score = max(0, min(score, 100))\n    if score >= 85:\n        label = "healthy"\n    elif score >= 60:\n        label = "watch"\n    elif score >= 35:\n        label = "fragile"\n    else:\n        label = "poor"\n    if not findings:\n        findings.append({"severity": "ok", "label": "Memory looks coherent", "detail": "Stable memory, summary, and latest exchange are populated."})\n    return {"score": score, "label": label, "findings": findings, "profile_signals": warnings}\n\ndef _apex_prompt_context(user: dict, proposed_mode: str = "", proposed_stable_memory: str = "", proposed_conversation_summary: str = "") -> dict:\n    mode = (proposed_mode or str(user.get("current_mode") or "general")).strip().lower() or "general"\n    stable = proposed_stable_memory if proposed_stable_memory else str(user.get("stable_memory") or "")\n    summary = proposed_conversation_summary if proposed_conversation_summary else str(user.get("conversation_summary") or "")\n    latest_user = str(user.get("last_user_message") or "")\n    latest_reply = str(user.get("last_agent_reply") or "")\n    sections = [f"Mode: {mode}"]\n    if stable.strip():\n        sections.append("Stable memory:\\n" + stable.strip())\n    if summary.strip():\n        sections.append("Continuity summary:\\n" + summary.strip())\n    if latest_user.strip() or latest_reply.strip():\n        sections.append("Latest exchange:\\nUser: " + latest_user[:800] + "\\nAssistant: " + latest_reply[:800])\n    return {"chat_id": user.get("chat_id", ""), "mode": mode, "stable_memory": stable, "conversation_summary": summary, "latest_user_message": latest_user, "latest_agent_reply": latest_reply, "prompt_context": "\\n\\n".join(sections)[:6000], "memory_qa": _apex_memory_qa({**user, "current_mode": mode, "stable_memory": stable, "conversation_summary": summary})}\n\ndef _apex_export_payloads(conn) -> dict:\n    users = []\n    if _apex_table_exists(conn, "apex_users"):\n        users = [_apex_attach_identity_confidence(_apex_attach_memory_qa(dict(row))) for row in conn.execute("SELECT * FROM apex_users ORDER BY COALESCE(NULLIF(last_seen,\'\'), first_seen) DESC").fetchall()]\n    segments = _apex_segment_users(conn) if "_apex_segment_users" in globals() else {"counts": {}, "segments": {}, "recommendations": []}\n    alerts = _apex_evaluate_alerts(conn) if "_apex_evaluate_alerts" in globals() else []\n    identity_coverage = {\n        "total_users": len(users),\n        "mapped_users": sum(1 for user in users if str(user.get("phone_number") or user.get("chat_phone") or user.get("sender_phone") or "").strip()),\n        "high_confidence_users": sum(1 for user in users if int((user.get("identity_confidence") or {}).get("score") or 0) >= 80),\n        "needs_refresh": sum(1 for user in users if not str(user.get("identity_refreshed_at") or "").strip()),\n    }\n    memory_health = {\n        "total_users": len(users),\n        "healthy": sum(1 for user in users if str((user.get("memory_qa") or {}).get("label") or "") == "healthy"),\n        "watch": sum(1 for user in users if str((user.get("memory_qa") or {}).get("label") or "") == "watch"),\n        "fragile": sum(1 for user in users if str((user.get("memory_qa") or {}).get("label") or "") == "fragile"),\n        "poor": sum(1 for user in users if str((user.get("memory_qa") or {}).get("label") or "") == "poor"),\n    }\n    usage_summary = {\n        "total_users": len(users),\n        "total_messages": sum(int(user.get("message_count") or 0) for user in users),\n        "total_mode_switches": sum(int(user.get("mode_switch_count") or 0) for user in users),\n        "total_menu_requests": sum(int(user.get("menu_request_count") or 0) for user in users),\n        "alerts": len(alerts),\n        "recommendations": len(segments.get("recommendations", [])),\n    }\n    compact_users = []\n    for user in users:\n        compact_users.append({\n            "chat_id": user.get("chat_id", ""),\n            "mode": user.get("current_mode", "general"),\n            "onboarded": user.get("onboarded", 0),\n            "first_seen": user.get("first_seen", ""),\n            "last_seen": user.get("last_seen", ""),\n            "message_count": int(user.get("message_count") or 0),\n            "mode_switch_count": int(user.get("mode_switch_count") or 0),\n            "menu_request_count": int(user.get("menu_request_count") or 0),\n            "phone_number": user.get("phone_number", ""),\n            "identity_source": user.get("identity_source", ""),\n            "identity_confidence": (user.get("identity_confidence") or {}).get("score", 0),\n            "memory_qa": (user.get("memory_qa") or {}).get("score", 0),\n        })\n    return {\n        "users": compact_users,\n        "usage_summary": usage_summary,\n        "identity_coverage": identity_coverage,\n        "memory_health": memory_health,\n        "segments": segments,\n        "alerts": alerts,\n    }\n\ndef _apex_operator_summary(conn) -> dict:\n    from datetime import datetime, timezone\n    payload = _apex_export_payloads(conn)\n    segments = payload.get("segments", {}) or {}\n    alerts = payload.get("alerts", []) or []\n    recommendations = segments.get("recommendations", []) or []\n    compact_recommendations = []\n    for item in recommendations[:10]:\n        compact_recommendations.append({\n            "chat_id": item.get("chat_id", ""),\n            "title": item.get("title", ""),\n            "detail": item.get("detail", ""),\n            "suggested_mode": item.get("suggested_mode", ""),\n        })\n    alert_counts = {"critical": 0, "warning": 0, "info": 0}\n    for alert in alerts:\n        severity = str(alert.get("severity") or "info")\n        alert_counts[severity] = alert_counts.get(severity, 0) + 1\n    return {\n        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),\n        "usage_summary": payload.get("usage_summary", {}),\n        "identity_coverage": payload.get("identity_coverage", {}),\n        "memory_health": payload.get("memory_health", {}),\n        "segment_counts": segments.get("counts", {}),\n        "alert_counts": alert_counts,\n        "top_recommendations": compact_recommendations,\n        "report_notes": [\n            "Apex operator summary is generated from compact dashboard aggregates.",\n            "Raw transcript history, latest-message fields, assistant-reply fields, and event replay payloads are excluded.",\n        ],\n    }\n\n\ndef _apex_segment_users(conn) -> dict:\n    from datetime import datetime, timedelta, timezone\n    result = {\n        "counts": {\n            "new_users": 0,\n            "dormant_users": 0,\n            "frequent_switchers": 0,\n            "menu_loop_users": 0,\n            "power_users": 0,\n            "upsc_heavy": 0,\n            "general_heavy": 0,\n            "retained_1d": 0,\n            "retained_7d": 0,\n            "retained_30d": 0,\n        },\n        "segments": {\n            "new_users": [],\n            "dormant_users": [],\n            "frequent_switchers": [],\n            "menu_loop_users": [],\n            "power_users": [],\n        },\n        "recommendations": [],\n    }\n    if not _apex_table_exists(conn, "apex_users"):\n        return result\n    now = datetime.now(timezone.utc)\n    users = [dict(row) for row in conn.execute("SELECT * FROM apex_users ORDER BY COALESCE(NULLIF(last_seen,\'\'), first_seen) DESC").fetchall()]\n    def parse_ts(value: str):\n        value = str(value or "").strip()\n        if not value:\n            return None\n        try:\n            if value.endswith(\'Z\'):\n                value = value[:-1] + \'+00:00\'\n            return datetime.fromisoformat(value)\n        except Exception:\n            return None\n    for user in users:\n        chat_id = str(user.get("chat_id") or "")\n        first_seen = parse_ts(user.get("first_seen"))\n        last_seen = parse_ts(user.get("last_seen")) or parse_ts(user.get("last_interaction_at"))\n        mode = str(user.get("current_mode") or "general")\n        message_count = int(user.get("message_count") or 0)\n        menu_requests = int(user.get("menu_request_count") or 0)\n        mode_switches = int(user.get("mode_switch_count") or 0)\n        memory = _apex_memory_qa(user) if "_apex_memory_qa" in globals() else {"score": 100, "label": "healthy"}\n        item = {\n            "chat_id": chat_id,\n            "mode": mode,\n            "message_count": message_count,\n            "menu_request_count": menu_requests,\n            "mode_switch_count": mode_switches,\n            "last_seen": user.get("last_seen", ""),\n            "memory_score": int(memory.get("score") or 0),\n            "identity_source": user.get("identity_source", ""),\n        }\n        if first_seen and now - first_seen <= timedelta(days=2):\n            result["counts"]["new_users"] += 1\n            result["segments"]["new_users"].append(item)\n        if last_seen and now - last_seen >= timedelta(days=7):\n            result["counts"]["dormant_users"] += 1\n            result["segments"]["dormant_users"].append(item)\n        if mode_switches >= 3:\n            result["counts"]["frequent_switchers"] += 1\n            result["segments"]["frequent_switchers"].append(item)\n        if menu_requests >= max(3, mode_switches + 2):\n            result["counts"]["menu_loop_users"] += 1\n            result["segments"]["menu_loop_users"].append(item)\n        if message_count >= 15:\n            result["counts"]["power_users"] += 1\n            result["segments"]["power_users"].append(item)\n        if mode == \'upsc\':\n            result["counts"]["upsc_heavy"] += 1\n        else:\n            result["counts"]["general_heavy"] += 1\n        if first_seen and last_seen:\n            delta = last_seen - first_seen\n            if delta >= timedelta(days=1):\n                result["counts"]["retained_1d"] += 1\n            if delta >= timedelta(days=7):\n                result["counts"]["retained_7d"] += 1\n            if delta >= timedelta(days=30):\n                result["counts"]["retained_30d"] += 1\n        if menu_requests >= max(2, mode_switches + 2):\n            result["recommendations"].append({\n                "chat_id": chat_id,\n                "title": "User may need clearer mode guidance",\n                "detail": f"Menu requests {menu_requests} outpace mode switches {mode_switches}.",\n                "suggested_mode": mode,\n            })\n        elif memory.get("score", 100) < 70:\n            result["recommendations"].append({\n                "chat_id": chat_id,\n                "title": "Memory repair recommended",\n                "detail": f"Memory QA score is {memory.get(\'score\', 0)}.",\n                "suggested_mode": mode,\n            })\n    result["recommendations"] = result["recommendations"][:20]\n    for key in list(result["segments"].keys()):\n        result["segments"][key] = result["segments"][key][:20]\n    return result\n\ndef _apex_evaluate_alerts(conn) -> list[dict]:\n    alerts = []\n    if not _apex_table_exists(conn, "apex_users"):\n        return alerts\n    users = [dict(row) for row in conn.execute("SELECT * FROM apex_users ORDER BY COALESCE(NULLIF(last_seen,\'\'), first_seen) DESC").fetchall()]\n    ledger_exists = _apex_table_exists(conn, "apex_usage_ledger")\n    event_counts = {}\n    if ledger_exists:\n        for row in conn.execute("SELECT chat_id, event_type, COUNT(*) AS count FROM apex_usage_ledger GROUP BY chat_id, event_type").fetchall():\n            event_counts[(row[0], row[1])] = int(row[2] or 0)\n    for user in users:\n        chat_id = str(user.get("chat_id") or "")\n        inbound = event_counts.get((chat_id, "inbound"), 0)\n        outbound = event_counts.get((chat_id, "outbound"), 0)\n        menu_requests = int(user.get("menu_request_count") or 0)\n        mode_switches = int(user.get("mode_switch_count") or 0)\n        message_count = int(user.get("message_count") or 0)\n        memory = _apex_memory_qa(user) if "_apex_memory_qa" in globals() else {"score": 100, "label": "healthy"}\n        if inbound > outbound + 2:\n            alerts.append({"id": f"reply-gap:{chat_id}", "severity": "critical", "kind": "reply_gap", "chat_id": chat_id, "title": "Inbound exceeds outbound replies", "detail": f"Inbound events {inbound} vs outbound {outbound}.", "value": inbound - outbound})\n        if menu_requests > max(2, mode_switches + 2):\n            alerts.append({"id": f"menu-churn:{chat_id}", "severity": "warning", "kind": "menu_churn", "chat_id": chat_id, "title": "Menu churn detected", "detail": f"Menu requests {menu_requests} outpace mode switches {mode_switches}.", "value": menu_requests - mode_switches})\n        if mode_switches >= 4 and mode_switches > max(1, message_count // 3):\n            alerts.append({"id": f"mode-thrash:{chat_id}", "severity": "warning", "kind": "mode_thrash", "chat_id": chat_id, "title": "Mode thrashing detected", "detail": f"Mode switches {mode_switches} across {message_count} messages.", "value": mode_switches})\n        if int(memory.get("score") or 0) < 60:\n            alerts.append({"id": f"memory-fragile:{chat_id}", "severity": "warning", "kind": "memory_fragile", "chat_id": chat_id, "title": "Memory quality is fragile", "detail": f"Memory QA score is {memory.get(\'score\', 0)}.", "value": int(memory.get("score") or 0)})\n        if not str(user.get("identity_refreshed_at") or "").strip():\n            alerts.append({"id": f"identity-stale:{chat_id}", "severity": "info", "kind": "identity_refresh_needed", "chat_id": chat_id, "title": "Identity refresh recommended", "detail": "No identity refresh timestamp is stored.", "value": 0})\n    alerts.sort(key=lambda item: ({"critical": 0, "warning": 1, "info": 2}.get(item.get("severity", "info"), 3), str(item.get("chat_id") or ""), str(item.get("kind") or "")))\n    return alerts[:50]\n\ndef _apex_attach_memory_qa(user: dict) -> dict:\n    user["memory_qa"] = _apex_memory_qa(user)\n    return user\n\ndef _apex_rebuild_summary(user: dict) -> str:\n    parts = []\n    for key, label in (("current_mode", "Current mode: "), ("stable_memory", ""), ("last_user_message", "Latest user message: "), ("last_agent_reply", "Latest assistant reply: ")):\n        value = str(user.get(key) or "").strip()\n        if not value:\n            continue\n        if key == "stable_memory":\n            parts.extend([line.strip() for line in value.splitlines() if line.strip()])\n        else:\n            parts.append(label + value[:360])\n    compact = []\n    seen = set()\n    for part in parts:\n        if part not in seen:\n            seen.add(part)\n            compact.append(part)\n    return "\\n".join(compact)[:3072]\n\ndef _apex_backfill_identities_from_session(conn) -> dict:\n    if not _apex_table_exists(conn, "apex_users"):\n        return {"updated": 0, "total": 0}\n    rows = [dict(row) for row in conn.execute("SELECT chat_id FROM apex_users").fetchall()]\n    updated = 0\n    for row in rows:\n        before = _apex_user_snapshot(conn, row.get("chat_id", ""))\n        result = _apex_refresh_identity_from_session(conn, row.get("chat_id", ""))\n        after = _apex_user_snapshot(conn, row.get("chat_id", ""))\n        if before != after or result.get("phone") or result.get("jid_kind"):\n            updated += 1\n            _apex_insert_audit(conn, row.get("chat_id", ""), "refresh_identity", before, after)\n    return {"updated": updated, "total": len(rows)}\n\ndef _apex_menu_text_for_user(user: dict) -> str:\n    mode = str(user.get("current_mode") or "general").strip().lower()\n    if not user.get("onboarded"):\n        return "Apex AI Gateway\\n\\nChoose your mode:\\n1. General AI — ask, research, write, code, plan\\n2. UPSC Mentor — strict exam preparation mode\\n\\nReply with: 1, 2, general, or upsc.\\nUse menu anytime to see this again."\n    mode_label = "UPSC Mentor" if mode == "upsc" else "General AI"\n    return f"Apex AI Gateway\\n\\nCurrent mode: {mode_label}\\n\\nChoose your mode:\\n1. General AI — ask, research, write, code, plan\\n2. UPSC Mentor — strict exam preparation mode\\n\\nReply with: 1, 2, general, or upsc. Or keep chatting in your current mode."\n\ndef _apex_bridge_send(chat_id: str, message: str) -> dict:\n    import urllib.error\n    req = urllib.request.Request("http://127.0.0.1:3000/send", data=json.dumps({"chatId": chat_id, "message": message}).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")\n    try:\n        with urllib.request.urlopen(req, timeout=20) as resp:\n            body = resp.read().decode("utf-8")\n            return json.loads(body) if body else {"success": True}\n    except urllib.error.HTTPError as e:\n        detail = e.read().decode("utf-8", errors="ignore")\n        raise HTTPException(status_code=502, detail=f"Bridge send failed: {detail or e.reason}")\n    except Exception as e:\n        raise HTTPException(status_code=502, detail=f"Bridge send failed: {e}")\n\n@app.get("/api/apex/summary")\nasync def get_apex_summary():\n    try:\n        today = time.strftime("%Y-%m-%d")\n        with _apex_connect() as conn:\n            if not _apex_table_exists(conn, "apex_users"):\n                return {"overview": {}, "recent_users": [], "recent_events": []}\n            overview = {\n                "total_users": _apex_scalar(conn, "SELECT COUNT(*) FROM apex_users"),\n                "active_users": _apex_scalar(conn, "SELECT COUNT(*) FROM apex_users WHERE last_seen != \'\'"),\n                "new_users_today": _apex_scalar(conn, "SELECT COUNT(*) FROM apex_users WHERE substr(first_seen,1,10)=?", (today,)),\n                "general_users": _apex_scalar(conn, "SELECT COUNT(*) FROM apex_users WHERE current_mode=\'general\'"),\n                "upsc_users": _apex_scalar(conn, "SELECT COUNT(*) FROM apex_users WHERE current_mode=\'upsc\'"),\n                "onboarded_users": _apex_scalar(conn, "SELECT COUNT(*) FROM apex_users WHERE onboarded=1"),\n                "identity_mapped_users": _apex_scalar(conn, "SELECT COUNT(*) FROM apex_users WHERE COALESCE(NULLIF(phone_number, \'\'), NULLIF(chat_phone, \'\'), NULLIF(sender_phone, \'\')) IS NOT NULL"),\n                "identity_high_confidence": _apex_scalar(conn, "SELECT COUNT(*) FROM apex_users WHERE identity_source IN (\'live_bridge_payload\', \'session_lid_mapping\')"),\n                "identity_refresh_needed": _apex_scalar(conn, "SELECT COUNT(*) FROM apex_users WHERE COALESCE(identity_refreshed_at, \'\') = \'\'"),\n                "active_alerts": len(_apex_evaluate_alerts(conn)),\n                "segment_recommendations": len(_apex_segment_users(conn).get("recommendations", [])),\n                "exportable_reports": 4,\n                "menu_requests": _apex_scalar(conn, "SELECT COALESCE(SUM(menu_request_count),0) FROM apex_users"),\n                "mode_switches": _apex_scalar(conn, "SELECT COALESCE(SUM(mode_switch_count),0) FROM apex_users"),\n                "inbound_today": 0,\n                "outbound_today": 0,\n            }\n            if _apex_table_exists(conn, "apex_usage_ledger"):\n                overview["inbound_today"] = _apex_scalar(conn, "SELECT COALESCE(SUM(units),0) FROM apex_usage_ledger WHERE event_type=\'inbound\' AND substr(created_at,1,10)=?", (today,))\n                overview["outbound_today"] = _apex_scalar(conn, "SELECT COALESCE(SUM(units),0) FROM apex_usage_ledger WHERE event_type=\'outbound\' AND substr(created_at,1,10)=?", (today,))\n                recent_events = [dict(row) for row in conn.execute("SELECT chat_id, event_type, mode, created_at, units, metadata FROM apex_usage_ledger ORDER BY id DESC LIMIT 20").fetchall()]\n            else:\n                recent_events = []\n            recent_users = [_apex_attach_identity_confidence(dict(row)) for row in conn.execute("SELECT * FROM apex_users ORDER BY COALESCE(NULLIF(last_seen,\'\'), first_seen) DESC LIMIT 12").fetchall()]\n            return {"overview": overview, "recent_users": recent_users, "recent_events": recent_events}\n    except Exception as e:\n        _log.exception("GET /api/apex/summary failed")\n        raise HTTPException(status_code=500, detail=str(e))\n\n@app.get("/api/apex/users")\nasync def get_apex_users(q: str = "", limit: int = 100):\n    try:\n        limit = max(1, min(limit, 500))\n        with _apex_connect() as conn:\n            if not _apex_table_exists(conn, "apex_users"):\n                return {"users": []}\n            params = []\n            where = ""\n            if q:\n                like = f"%{q}%"\n                where = "WHERE chat_id LIKE ? OR phone_number LIKE ? OR sender_id LIKE ? OR chat_name LIKE ? OR sender_name LIKE ? OR display_name LIKE ?"\n                params.extend([like, like, like, like, like, like])\n            rows = [_apex_attach_identity_confidence(dict(row)) for row in conn.execute(f"SELECT * FROM apex_users {where} ORDER BY COALESCE(NULLIF(last_seen,\'\'), first_seen) DESC LIMIT ?", tuple(params + [limit])).fetchall()]\n            return {"users": rows}\n    except Exception as e:\n        _log.exception("GET /api/apex/users failed")\n        raise HTTPException(status_code=500, detail=str(e))\n\n@app.post("/api/apex/users/clear-memory")\nasync def clear_apex_user_memory(body: ApexUserAction):\n    try:\n        with _apex_connect() as conn:\n            conn.execute("UPDATE apex_users SET last_user_message=\'\', last_agent_reply=\'\', conversation_summary=\'\', stable_memory=\'\', last_interaction_at=\'\' WHERE chat_id=?", (body.chat_id,))\n            conn.commit()\n        return {"ok": True}\n    except Exception as e:\n        _log.exception("POST /api/apex/users/clear-memory failed")\n        raise HTTPException(status_code=500, detail=str(e))\n\n@app.post("/api/apex/users/recovery-action")\nasync def apex_user_recovery_action(body: ApexUserRecoveryAction):\n    try:\n        action = (body.action or "").strip()\n        allowed = {"clear_continuity", "clear_stable_memory", "refresh_identity", "backfill_identities", "clear_onboarding", "rebuild_summary", "force_mode_sync", "set_mode_general", "set_mode_upsc", "resend_menu", "restore_default_mode", "reset_user_scoped"}\n        if action not in allowed:\n            raise HTTPException(status_code=400, detail="Unsupported recovery action")\n        with _apex_connect() as conn:\n            if action == "backfill_identities":\n                result = _apex_backfill_identities_from_session(conn)\n                conn.commit()\n                return {"ok": True, "action": action, "result": result, "audit_recorded": False, "scope": "global"}\n            before = _apex_user_snapshot(conn, body.chat_id)\n            if not before:\n                raise HTTPException(status_code=404, detail="Apex user not found")\n            result = {}\n            if action == "clear_continuity":\n                conn.execute("UPDATE apex_users SET last_user_message=\'\', last_agent_reply=\'\', conversation_summary=\'\', last_interaction_at=\'\' WHERE chat_id=?", (body.chat_id,))\n                result = {"cleared_fields": ["last_user_message", "last_agent_reply", "conversation_summary", "last_interaction_at"]}\n            elif action == "clear_stable_memory":\n                conn.execute("UPDATE apex_users SET stable_memory=\'\' WHERE chat_id=?", (body.chat_id,))\n                result = {"cleared_fields": ["stable_memory"]}\n            elif action == "refresh_identity":\n                result = _apex_refresh_identity_from_session(conn, body.chat_id)\n            elif action == "clear_onboarding":\n                conn.execute("UPDATE apex_users SET onboarded=0 WHERE chat_id=?", (body.chat_id,))\n                result = {"cleared_fields": ["onboarded"]}\n            elif action == "rebuild_summary":\n                rebuilt = _apex_rebuild_summary(before)\n                conn.execute("UPDATE apex_users SET conversation_summary=? WHERE chat_id=?", (rebuilt, body.chat_id))\n                result = {"conversation_summary": rebuilt}\n            elif action == "force_mode_sync":\n                mode = str(before.get("current_mode") or "general")\n                conn.execute("UPDATE apex_users SET current_mode=?, onboarded=1 WHERE chat_id=?", (mode, body.chat_id))\n                result = {"mode": mode, "status": "state_aligned"}\n            elif action == "set_mode_general":\n                conn.execute("UPDATE apex_users SET current_mode=\'general\', onboarded=1, mode_switch_count=mode_switch_count+1, last_mode_switch_at=strftime(\'%Y-%m-%dT%H:%M:%fZ\',\'now\') WHERE chat_id=?", (body.chat_id,))\n                result = {"mode": "general"}\n            elif action == "set_mode_upsc":\n                conn.execute("UPDATE apex_users SET current_mode=\'upsc\', onboarded=1, mode_switch_count=mode_switch_count+1, last_mode_switch_at=strftime(\'%Y-%m-%dT%H:%M:%fZ\',\'now\') WHERE chat_id=?", (body.chat_id,))\n                result = {"mode": "upsc"}\n            elif action == "restore_default_mode":\n                config = _apex_load_config(conn) if \'_apex_load_config\' in globals() else {}\n                mode = config.get("default_mode") if isinstance(config, dict) else "general"\n                if mode not in {"general", "upsc"}:\n                    mode = "general"\n                conn.execute("UPDATE apex_users SET current_mode=?, onboarded=1, mode_switch_count=mode_switch_count+1, last_mode_switch_at=strftime(\'%Y-%m-%dT%H:%M:%fZ\',\'now\') WHERE chat_id=?", (mode, body.chat_id))\n                result = {"mode": mode}\n            elif action == "reset_user_scoped":\n                conn.execute("""\n                    UPDATE apex_users\n                    SET onboarded=0,\n                        current_mode=\'general\',\n                        stable_memory=\'\',\n                        last_user_message=\'\',\n                        last_agent_reply=\'\',\n                        conversation_summary=\'\',\n                        last_interaction_at=\'\',\n                        menu_request_count=0,\n                        mode_switch_count=0,\n                        last_mode_switch_at=\'\'\n                    WHERE chat_id=?\n                """, (body.chat_id,))\n                result = {"reset_fields": ["onboarded", "current_mode", "stable_memory", "last_user_message", "last_agent_reply", "conversation_summary", "last_interaction_at", "menu_request_count", "mode_switch_count", "last_mode_switch_at"]}\n            elif action == "resend_menu":\n                result = _apex_bridge_send(body.chat_id, _apex_menu_text_for_user(before))\n            after = _apex_user_snapshot(conn, body.chat_id)\n            _apex_insert_audit(conn, body.chat_id, action, before, after)\n            conn.commit()\n            return {"ok": True, "action": action, "result": result, "user": _apex_attach_identity_confidence(after), "audit_recorded": True, "scope": "user"}\n    except HTTPException:\n        raise\n    except Exception as e:\n        _log.exception("POST /api/apex/users/recovery-action failed")\n        raise HTTPException(status_code=500, detail=str(e))\n\nclass ApexDashboardConfigUpdate(BaseModel):\n    config: Dict[str, Any] = {}\n\ndef _apex_default_config() -> dict:\n    return {\n        "onboarding_menu_text": "Apex AI Gateway\\n\\nChoose your mode:\\n1. General AI\\n2. UPSC Mentor\\n\\nReply with: 1, 2, general, or upsc. Use menu anytime.",\n        "returning_menu_text": "Apex AI Gateway\\n\\nCurrent mode: {mode_label}\\n\\nChoose your mode:\\n1. General AI\\n2. UPSC Mentor\\n\\nReply with: 1, 2, general, or upsc.",\n        "stable_memory_enabled": True,\n        "continuity_length_cap": 800,\n        "summary_length_cap": 1200,\n        "interactive_whatsapp_mode": True,\n        "default_mode": "general",\n        "general_prompt_snippet": "",\n        "upsc_prompt_snippet": "",\n        "quota_preview_enabled": True,\n        "quota_warning_24h": 25,\n        "quota_block_24h": 40,\n        "quota_warning_7d": 120,\n        "quota_block_7d": 200,\n    }\n\ndef _apex_ensure_dashboard_config(conn) -> None:\n    conn.execute("""\n        CREATE TABLE IF NOT EXISTS apex_dashboard_config (\n            key TEXT PRIMARY KEY,\n            value_json TEXT NOT NULL DEFAULT \'\',\n            updated_at TEXT NOT NULL DEFAULT \'\'\n        )\n    """)\n\ndef _apex_load_config(conn) -> dict:\n    _apex_ensure_dashboard_config(conn)\n    config = _apex_default_config()\n    row = conn.execute("SELECT value_json FROM apex_dashboard_config WHERE key=\'runtime\'").fetchone()\n    if row and row[0]:\n        try:\n            saved = json.loads(row[0])\n            if isinstance(saved, dict):\n                config.update(saved)\n        except Exception:\n            pass\n    return config\n\ndef _apex_save_config(conn, payload: dict) -> dict:\n    _apex_ensure_dashboard_config(conn)\n    current = _apex_load_config(conn)\n    for key, value in (payload or {}).items():\n        if key in current:\n            current[key] = value\n    if current.get("default_mode") not in {"general", "upsc"}:\n        current["default_mode"] = "general"\n    defaults = _apex_default_config()\n    for key in ["continuity_length_cap", "summary_length_cap", "quota_warning_24h", "quota_block_24h", "quota_warning_7d", "quota_block_7d"]:\n        try:\n            current[key] = max(0, int(current.get(key) or 0))\n        except Exception:\n            current[key] = defaults[key]\n    for key in ["stable_memory_enabled", "interactive_whatsapp_mode", "quota_preview_enabled"]:\n        current[key] = bool(current.get(key))\n    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())\n    conn.execute("INSERT INTO apex_dashboard_config(key, value_json, updated_at) VALUES(\'runtime\', ?, ?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at", (json.dumps(current, ensure_ascii=False, sort_keys=True), now))\n    conn.commit()\n    return current\n\ndef _apex_quota_preview(conn, config: dict) -> dict:\n    users = []\n    if _apex_table_exists(conn, "apex_users"):\n        users = [dict(row) for row in conn.execute("SELECT * FROM apex_users ORDER BY COALESCE(NULLIF(last_seen,\'\'), first_seen) DESC").fetchall()]\n    counts_24h, counts_7d = {}, {}\n    if _apex_table_exists(conn, "apex_usage_ledger"):\n        from datetime import datetime, timedelta, timezone\n        now = datetime.now(timezone.utc)\n        since_24h = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")\n        since_7d = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")\n        for row in conn.execute("SELECT chat_id, COUNT(*) FROM apex_usage_ledger WHERE created_at >= ? GROUP BY chat_id", (since_24h,)).fetchall():\n            counts_24h[str(row[0] or "")] = int(row[1] or 0)\n        for row in conn.execute("SELECT chat_id, COUNT(*) FROM apex_usage_ledger WHERE created_at >= ? GROUP BY chat_id", (since_7d,)).fetchall():\n            counts_7d[str(row[0] or "")] = int(row[1] or 0)\n    warning_24h = int(config.get("quota_warning_24h") or 0)\n    block_24h = int(config.get("quota_block_24h") or 0)\n    warning_7d = int(config.get("quota_warning_7d") or 0)\n    block_7d = int(config.get("quota_block_7d") or 0)\n    summary = {"normal": 0, "warning": 0, "would_block": 0, "total_users": len(users)}\n    rows = []\n    for user in users:\n        chat_id = str(user.get("chat_id") or "")\n        usage_24h = counts_24h.get(chat_id, 0)\n        usage_7d = counts_7d.get(chat_id, 0)\n        status = "normal"\n        if (block_24h and usage_24h >= block_24h) or (block_7d and usage_7d >= block_7d):\n            status = "would_block"\n        elif (warning_24h and usage_24h >= warning_24h) or (warning_7d and usage_7d >= warning_7d):\n            status = "warning"\n        summary[status] += 1\n        rows.append({"chat_id": chat_id, "display_name": user.get("display_name") or user.get("sender_name") or user.get("chat_name") or user.get("phone_number") or chat_id, "mode": user.get("current_mode") or "general", "usage_24h": usage_24h, "usage_7d": usage_7d, "total_messages": int(user.get("message_count") or 0), "status": status})\n    rows.sort(key=lambda item: (item["status"] != "would_block", item["status"] != "warning", -item["usage_7d"], -item["usage_24h"]))\n    return {"enabled": bool(config.get("quota_preview_enabled", True)), "thresholds": {"warning_24h": warning_24h, "block_24h": block_24h, "warning_7d": warning_7d, "block_7d": block_7d}, "summary": summary, "users": rows[:100]}\n\n@app.get("/api/apex/config")\nasync def get_apex_config():\n    try:\n        with _apex_connect() as conn:\n            return {"config": _apex_load_config(conn)}\n    except Exception as e:\n        _log.exception("GET /api/apex/config failed")\n        raise HTTPException(status_code=500, detail=str(e))\n\n@app.post("/api/apex/config")\nasync def save_apex_config(body: ApexDashboardConfigUpdate):\n    try:\n        with _apex_connect() as conn:\n            return {"ok": True, "config": _apex_save_config(conn, body.config)}\n    except Exception as e:\n        _log.exception("POST /api/apex/config failed")\n        raise HTTPException(status_code=500, detail=str(e))\n\n@app.get("/api/apex/quota-preview")\nasync def get_apex_quota_preview():\n    try:\n        with _apex_connect() as conn:\n            config = _apex_load_config(conn)\n            return _apex_quota_preview(conn, config)\n    except Exception as e:\n        _log.exception("GET /api/apex/quota-preview failed")\n        raise HTTPException(status_code=500, detail=str(e))\n\n@app.get("/api/apex/export/users")\nasync def export_apex_users():\n    try:\n        with _apex_connect() as conn:\n            return {"export": _apex_export_payloads(conn).get("users", [])}\n    except Exception as e:\n        _log.exception("GET /api/apex/export/users failed")\n        raise HTTPException(status_code=500, detail=str(e))\n\n@app.get("/api/apex/export/usage-summary")\nasync def export_apex_usage_summary():\n    try:\n        with _apex_connect() as conn:\n            payload = _apex_export_payloads(conn)\n            return {"export": payload.get("usage_summary", {}), "segments": payload.get("segments", {}).get("counts", {}), "alerts": len(payload.get("alerts", []))}\n    except Exception as e:\n        _log.exception("GET /api/apex/export/usage-summary failed")\n        raise HTTPException(status_code=500, detail=str(e))\n\n@app.get("/api/apex/export/identity-coverage")\nasync def export_apex_identity_coverage():\n    try:\n        with _apex_connect() as conn:\n            return {"export": _apex_export_payloads(conn).get("identity_coverage", {})}\n    except Exception as e:\n        _log.exception("GET /api/apex/export/identity-coverage failed")\n        raise HTTPException(status_code=500, detail=str(e))\n\n@app.get("/api/apex/export/memory-health")\nasync def export_apex_memory_health():\n    try:\n        with _apex_connect() as conn:\n            return {"export": _apex_export_payloads(conn).get("memory_health", {})}\n    except Exception as e:\n        _log.exception("GET /api/apex/export/memory-health failed")\n        raise HTTPException(status_code=500, detail=str(e))\n\n@app.get("/api/apex/export/operator-summary")\nasync def export_apex_operator_summary():\n    try:\n        with _apex_connect() as conn:\n            return {"export": _apex_operator_summary(conn)}\n    except Exception as e:\n        _log.exception("GET /api/apex/export/operator-summary failed")\n        raise HTTPException(status_code=500, detail=str(e))\n\n\n@app.get("/api/apex/segments")\nasync def get_apex_segments():\n    try:\n        with _apex_connect() as conn:\n            return _apex_segment_users(conn)\n    except Exception as e:\n        _log.exception("GET /api/apex/segments failed")\n        raise HTTPException(status_code=500, detail=str(e))\n\n@app.get("/api/apex/alerts")\nasync def get_apex_alerts():\n    try:\n        with _apex_connect() as conn:\n            alerts = _apex_evaluate_alerts(conn)\n            counts = {"critical": 0, "warning": 0, "info": 0}\n            for alert in alerts:\n                severity = str(alert.get("severity") or "info")\n                counts[severity] = counts.get(severity, 0) + 1\n            return {"alerts": alerts, "counts": counts}\n    except Exception as e:\n        _log.exception("GET /api/apex/alerts failed")\n        raise HTTPException(status_code=500, detail=str(e))\n\n@app.get("/api/apex/memory-qa")\nasync def get_apex_memory_qa(chat_id: str = ""):\n    try:\n        if not chat_id:\n            raise HTTPException(status_code=400, detail="chat_id is required")\n        with _apex_connect() as conn:\n            user = _apex_user_snapshot(conn, chat_id)\n            if not user:\n                raise HTTPException(status_code=404, detail="Apex user not found")\n            return {"memory_qa": _apex_memory_qa(user), "context": _apex_prompt_context(user)}\n    except HTTPException:\n        raise\n    except Exception as e:\n        _log.exception("GET /api/apex/memory-qa failed")\n        raise HTTPException(status_code=500, detail=str(e))\n\n@app.post("/api/apex/context-simulation")\nasync def simulate_apex_context(body: ApexContextSimulationRequest):\n    try:\n        with _apex_connect() as conn:\n            user = _apex_user_snapshot(conn, body.chat_id)\n            if not user:\n                raise HTTPException(status_code=404, detail="Apex user not found")\n            return {"context": _apex_prompt_context(user, body.proposed_mode, body.proposed_stable_memory, body.proposed_conversation_summary)}\n    except HTTPException:\n        raise\n    except Exception as e:\n        _log.exception("POST /api/apex/context-simulation failed")\n        raise HTTPException(status_code=500, detail=str(e))\n\n@app.get("/api/apex/timeline")\nasync def get_apex_timeline(chat_id: str = "", limit: int = 100):\n    try:\n        limit = max(1, min(limit, 300))\n        entries = []\n        with _apex_connect() as conn:\n            if _apex_table_exists(conn, "apex_usage_ledger"):\n                params = []\n                sql = "SELECT id, chat_id, event_type, mode, created_at, units, metadata FROM apex_usage_ledger"\n                if chat_id:\n                    sql += " WHERE chat_id = ?"\n                    params.append(chat_id)\n                sql += " ORDER BY id DESC LIMIT ?"\n                params.append(limit)\n                for row in conn.execute(sql, tuple(params)).fetchall():\n                    item = dict(row)\n                    entries.append({\n                        "id": f"usage:{item.get(\'id\')}",\n                        "source": "usage",\n                        "chat_id": item.get("chat_id", ""),\n                        "event_type": item.get("event_type", ""),\n                        "title": str(item.get("event_type") or "usage").replace("_", " ").title(),\n                        "created_at": item.get("created_at", ""),\n                        "mode": item.get("mode", ""),\n                        "status": "ok",\n                        "units": item.get("units", 0),\n                        "metadata": item.get("metadata", ""),\n                        "before_json": "",\n                        "after_json": "",\n                    })\n            _apex_ensure_admin_audit_log(conn)\n            params = []\n            sql = "SELECT id, chat_id, action, created_at, before_json, after_json, status FROM apex_admin_audit_log"\n            if chat_id:\n                sql += " WHERE chat_id = ?"\n                params.append(chat_id)\n            sql += " ORDER BY id DESC LIMIT ?"\n            params.append(limit)\n            for row in conn.execute(sql, tuple(params)).fetchall():\n                item = dict(row)\n                entries.append({\n                    "id": f"audit:{item.get(\'id\')}",\n                    "source": "audit",\n                    "chat_id": item.get("chat_id", ""),\n                    "event_type": item.get("action", ""),\n                    "title": "Operator " + str(item.get("action") or "action").replace("_", " ").title(),\n                    "created_at": item.get("created_at", ""),\n                    "mode": "",\n                    "status": item.get("status", "ok"),\n                    "units": 1,\n                    "metadata": "",\n                    "before_json": item.get("before_json", ""),\n                    "after_json": item.get("after_json", ""),\n                })\n        entries.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)\n        return {"timeline": entries[:limit]}\n    except Exception as e:\n        _log.exception("GET /api/apex/timeline failed")\n        raise HTTPException(status_code=500, detail=str(e))\n\n@app.get("/api/apex/audit-log")\nasync def get_apex_audit_log(chat_id: str = "", limit: int = 50):\n    try:\n        limit = max(1, min(limit, 200))\n        with _apex_connect() as conn:\n            _apex_ensure_admin_audit_log(conn)\n            params = []\n            sql = "SELECT id, chat_id, action, created_at, before_json, after_json, status FROM apex_admin_audit_log"\n            if chat_id:\n                sql += " WHERE chat_id=?"\n                params.append(chat_id)\n            sql += " ORDER BY id DESC LIMIT ?"\n            params.append(limit)\n            return {"audit_log": [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]}\n    except Exception as e:\n        _log.exception("GET /api/apex/audit-log failed")\n        raise HTTPException(status_code=500, detail=str(e))\n\n'
    if anchor not in text:
        raise RuntimeError('web_server.py analytics anchor not found')
    text = text.replace(anchor, replacement + anchor, 1)
    write(path, text)
    print('  [web_server] patched')

def patch_auto_update():
    path = AUTO_UPDATE
    text = read(path)
    original = text
    line = '        python3 /home/market/.hermes/patches/apply_apex_gateway_features.py || echo "WARNING: Apex gateway feature patch failed"\n'
    if 'apply_apex_gateway_features.py' not in text:
        anchor = '        python3 /home/market/.hermes/patches/apply_whitelabel.py || echo "WARNING: White-label patch failed"\n'
        if anchor not in text:
            raise RuntimeError('auto-update.sh white-label anchor not found')
        text = text.replace(anchor, anchor + line, 1)
    if text != original:
        write(path, text)
        print('  [auto-update] applied 1 change')
    else:
        print('  [auto-update] already patched')


def patch_apex_config_controls():
    path = WEB_SERVER
    text = read(path)
    if '@app.get("/api/apex/config")' in text and '@app.get("/api/apex/quota-preview")' in text and 'restore_default_mode' in text and 'reset_user_scoped' in text:
        print('  [apex_config_controls] already patched')
        return
    patch_web_server()


def patch_web_app_shell():
    path = WEB_APP
    text = read(path)
    original = text
    changes = 0
    if 'import ApexPage from "@/pages/ApexPage";' not in text:
        anchor = 'import AnalyticsPage from "@/pages/AnalyticsPage";\n'
        if anchor not in text:
            raise RuntimeError('App.tsx AnalyticsPage import anchor not found')
        text = text.replace(anchor, anchor + 'import ApexPage from "@/pages/ApexPage";\n', 1)
        changes += 1
    if '"/apex": ApexPage,' not in text:
        anchor = '  "/analytics": AnalyticsPage,\n'
        if anchor not in text:
            raise RuntimeError('App.tsx analytics route anchor not found')
        text = text.replace(anchor, anchor + '  "/apex": ApexPage,\n', 1)
        changes += 1
    if 'path: "/apex"' not in text:
        anchor = '  {\n    path: "/analytics",\n    labelKey: "analytics",\n    label: "Analytics",\n    icon: BarChart3,\n  },\n'
        item = '  {\n    path: "/apex",\n    label: "Apex",\n    icon: Zap,\n  },\n'
        if anchor not in text:
            raise RuntimeError('App.tsx analytics nav anchor not found')
        text = text.replace(anchor, anchor + item, 1)
        changes += 1
    if text != original:
        write(path, text)
    status = 'applied ' + str(changes) + ' change(s)' if changes else 'already patched'
    print('  [web_app_shell] ' + status)


def patch_qr_feature():
    # 1. Patch bridge.js
    bridge_path = Path('/home/market/.hermes/hermes-agent/scripts/whatsapp-bridge/bridge.js')
    if bridge_path.exists():
        bridge_text = read(bridge_path)
        original_bridge = bridge_text
        if "writeFileSync('/tmp/hermes_whatsapp_qr.txt'" not in bridge_text:
            bridge_text = bridge_text.replace(
                "qrcode.generate(qr, { small: true });",
                "qrcode.generate(qr, { small: true });\n      require('fs').writeFileSync('/tmp/hermes_whatsapp_qr.txt', qr);"
            )
            bridge_text = bridge_text.replace(
                "connectionState = 'connected';",
                "connectionState = 'connected';\n      require('fs').writeFileSync('/tmp/hermes_whatsapp_qr.txt', 'connected');"
            )
        if bridge_text != original_bridge:
            write(bridge_path, bridge_text)
            print("  [qr_bridge] patched")

    # 2. Patch web_server.py
    server_path = Path('/home/market/.hermes/hermes-agent/hermes_cli/web_server.py')
    if server_path.exists():
        server_text = read(server_path)
        original_server = server_text
        if "/api/apex/whatsapp-relogin" not in server_text:
            endpoints = '''
@app.post("/api/apex/whatsapp-relogin")
async def apex_whatsapp_relogin():
    import os
    os.system("rm -rf /home/market/.hermes/whatsapp/session/*")
    os.system("sudo -n /bin/systemctl restart hermes-whatsapp-bridge")
    return {"status": "ok"}

@app.get("/api/apex/whatsapp-qr")
async def apex_whatsapp_qr():
    try:
        with open("/tmp/hermes_whatsapp_qr.txt", "r") as f:
            return {"qr": f.read().strip()}
    except Exception:
        return {"qr": ""}
'''
            server_text = server_text.replace(
                '@app.get("/api/apex/summary")',
                endpoints + '\n@app.get("/api/apex/summary")'
            )
        if server_text != original_server:
            write(server_path, server_text)
            print("  [qr_server] patched")

    # 3. Patch ApexPage.tsx
    apex_path = Path('/home/market/.hermes/hermes-agent/web/src/pages/ApexPage.tsx')
    if apex_path.exists():
        apex_text = read(apex_path)
        original_apex = apex_text
        if "WhatsApp Re-login" not in apex_text:
            # Inject state
            apex_text = apex_text.replace(
                'const [selectedChatId, setSelectedChatId] = useState<string>("");',
                'const [selectedChatId, setSelectedChatId] = useState<string>("");\n  const [showQRModal, setShowQRModal] = useState(false);\n  const [qrData, setQrData] = useState("");'
            )
            
            # Inject logic
            logic = '''
  useEffect(() => {
    let interval: any;
    if (showQRModal) {
      interval = setInterval(async () => {
        try {
          const res = await fetch("/api/apex/whatsapp-qr", {
            headers: { "X-Hermes-Session-Token": window.__HERMES_SESSION_TOKEN__ || "" }
          });
          const data = await res.json();
          if (data.qr === "connected") {
            setShowQRModal(false);
          } else if (data.qr) {
            setQrData(data.qr);
          }
        } catch (e) {}
      }, 2000);
    }
    return () => clearInterval(interval);
  }, [showQRModal]);

  const handleRelogin = async () => {
    setQrData("");
    setShowQRModal(true);
    await fetch("/api/apex/whatsapp-relogin", {
      method: "POST",
      headers: { "X-Hermes-Session-Token": window.__HERMES_SESSION_TOKEN__ || "" }
    }).catch(console.error);
  };
'''
            apex_text = apex_text.replace(
                'useEffect(() => {',
                logic + '\n  useEffect(() => {',
                1
            )
            
            # Inject UI
            ui = '''
        <Card className="border-border/70 bg-card/70 xl:col-span-1">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Zap className="h-5 w-5 text-primary" />
              WhatsApp Connection
            </CardTitle>
          </CardHeader>
          <CardContent>
            <button type="button" onClick={handleRelogin} className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow hover:bg-primary/90 transition-colors">WhatsApp Re-login</button>
            {showQRModal && (
              <div className="fixed inset-0 z-[100] flex items-center justify-center bg-background/80 backdrop-blur-sm">
                <div className="relative w-full max-w-sm rounded-xl border bg-card p-6 shadow-xl">
                  <button onClick={() => setShowQRModal(false)} className="absolute right-4 top-4 text-muted-foreground hover:text-foreground">✕</button>
                  <h3 className="text-lg font-semibold mb-4 text-center">Scan QR Code</h3>
                  <div className="flex flex-col items-center justify-center p-2 gap-4">
                    {qrData ? (
                      <img src={`https://api.qrserver.com/v1/create-qr-code/?size=250x250&data=${encodeURIComponent(qrData)}`} alt="QR Code" className="rounded-lg shadow-sm w-[250px] h-[250px]" />
                    ) : (
                      <div className="flex flex-col items-center py-10 text-muted-foreground"><Zap className="h-8 w-8 animate-pulse mb-2 text-primary" /> Generating new session...</div>
                    )}
                    <p className="text-sm text-muted-foreground text-center mt-2">Open WhatsApp on your phone and scan this code to link your account.</p>
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
'''
            apex_text = apex_text.replace(
                '<Card className="border-border/70 bg-card/70 xl:col-span-1">',
                ui + '\n        <Card className="border-border/70 bg-card/70 xl:col-span-1">',
                1
            )
        if apex_text != original_apex:
            write(apex_path, apex_text)
            print("  [qr_ui] patched")


def main():
    print('Applying Apex gateway feature patches...')
    patch_whatsapp_adapter()
    try:
        patch_bridge()
    except Exception as exc:
        print(f'  [bridge] skipped: {exc}')
    patch_url_safety()
    try:
        patch_web_tools()
    except Exception as exc:
        print(f'  [web_tools] skipped: {exc}')
    patch_web_server()
    patch_apex_config_controls()
    patch_web_app_shell()
    patch_qr_feature()
    patch_auto_update()
    print('Apex gateway feature patches complete.')

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
