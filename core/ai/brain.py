"""
Mimir AI Brain — LLM with tool-use, permission gate, and context injection.
"""
import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Optional, Callable

from openai import AsyncOpenAI, APIError, APITimeoutError

from config.loader import Config, PermissionLevel, save_config
from ai.honcho import HonchoClient
from ai.tools import get_tool_list, execute_tool, tool_event

log = logging.getLogger("mimir.brain")

_KEEP_RECENT = 8
_COMPRESS_AT = 16
_PERMISSION_TIMEOUT = 30.0

_AGENT_DIR = Path(__file__).parent.parent.parent / "agent"


def _load_agent_file(name: str, max_chars: int = 2000) -> str:
    path = _AGENT_DIR / name
    try:
        if path.exists():
            content = path.read_text(encoding="utf-8")
            if len(content) > max_chars * 0.8:
                log.warning(
                    f"{name}: {len(content)}/{max_chars} chars "
                    f"({'OVER LIMIT — TRUNCATED' if len(content) > max_chars else 'approaching limit'})"
                )
            return content[:max_chars]
    except Exception as e:
        log.warning(f"Could not read {name}: {e}")
    return ""


class Brain:
    def __init__(self, cfg: Config):
        self._cfg = cfg
        self._primary = self._make_client(primary=True)
        self._fallback = self._make_client(primary=False) if cfg.ai.fallback.enabled else None
        self._history: list[dict] = []
        self._summary: Optional[str] = None
        self._honcho = HonchoClient(cfg.honcho if cfg.honcho.enabled else None)
        self._honcho_context: Optional[str] = None
        self._pending_user: Optional[str] = None

        # Callbacks
        self._on_tool_call: Optional[Callable] = None
        self._on_permission_request: Optional[Callable] = None

        # Permission gate: request_id → (tool_name, Future)
        self._pending_permissions: dict[str, tuple[str, asyncio.Future]] = {}

        # Context injected by slash commands
        self._goal: Optional[str] = None
        self._steering: Optional[str] = None
        self._extra_context: list[str] = []

    def set_tool_callback(self, cb: Callable) -> None:
        self._on_tool_call = cb

    def set_permission_callback(self, cb: Callable) -> None:
        """cb(tool_name, description, request_id) — called when tool needs permission."""
        self._on_permission_request = cb

    # ── Slash command context injection ──────────────────────────────────────

    def set_goal(self, goal: str) -> None:
        self._goal = goal.strip()
        log.info(f"Goal set: {self._goal[:60]}")

    def set_steering(self, text: str) -> None:
        self._steering = text.strip()
        log.info(f"Steering: {self._steering[:60]}")

    def add_context(self, text: str) -> None:
        """Add background context (/btw) without generating a response."""
        self._extra_context.append(text.strip())
        log.info(f"Context added: {text[:60]}")

    def clear_context(self) -> None:
        self._goal = None
        self._steering = None
        self._extra_context = []

    # ── Permission gate ───────────────────────────────────────────────────────

    async def _check_permission(self, tool_name: str, description: str) -> bool:
        perms = self._cfg.tools.permissions
        level = getattr(perms, tool_name, PermissionLevel.ask)

        if level == PermissionLevel.always:
            return True
        if level == PermissionLevel.never:
            log.info(f"Tool '{tool_name}' blocked (never)")
            return False

        # ask — pause and wait for user response
        request_id = uuid.uuid4().hex[:8]
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_permissions[request_id] = (tool_name, future)

        if self._on_permission_request:
            await self._on_permission_request(tool_name, description, request_id)
        else:
            # No UI connected — auto-deny for safety
            log.warning(f"Permission needed for '{tool_name}' but no UI connected — denying")
            self._pending_permissions.pop(request_id, None)
            return False

        try:
            result = await asyncio.wait_for(asyncio.shield(future), timeout=_PERMISSION_TIMEOUT)
            return result
        except asyncio.TimeoutError:
            self._pending_permissions.pop(request_id, None)
            log.info(f"Permission timeout for '{tool_name}' — denying")
            return False

    def grant_permission(self, request_id: str, allow: bool, permanent: bool) -> None:
        """Called from main.py when user responds to a permission dialog."""
        entry = self._pending_permissions.pop(request_id, None)
        if entry is None:
            log.warning(f"Unknown permission request_id: {request_id}")
            return
        tool_name, future = entry
        if not future.done():
            future.set_result(allow)

        if allow and permanent:
            perms = self._cfg.tools.permissions
            if hasattr(perms, tool_name):
                setattr(perms, tool_name, PermissionLevel.always)
                save_config(self._cfg)
                log.info(f"Tool '{tool_name}' permanently allowed — saved to config")

    # ── Client factory ────────────────────────────────────────────────────────

    _KEY_MAP = {
        "openrouter":   lambda: os.environ.get("OPENROUTER_API_KEY", ""),
        "openai":       lambda: os.environ.get("OPENAI_API_KEY", ""),
        "anthropic":    lambda: os.environ.get("ANTHROPIC_API_KEY", ""),
        "ollama_cloud": lambda: os.environ.get("OLLAMA_API_KEY", "ollama"),
        "ollama":       lambda: "ollama",
        "lmstudio":     lambda: "lmstudio",
    }

    def _make_client(self, primary: bool) -> AsyncOpenAI:
        if primary:
            p = self._cfg.ai.primary
            provider = getattr(p, "provider", "openrouter")
            api_key = p.api_key or self._KEY_MAP.get(provider, lambda: "")()
            base_url = p.base_url if p.base_url else f"http://{p.host}/v1"
        else:
            p = self._cfg.ai.fallback
            provider = getattr(p, "provider", "ollama")
            api_key = self._KEY_MAP.get(provider, lambda: "ollama")()
            base_url = f"http://{p.host}/v1"
        return AsyncOpenAI(api_key=api_key or "placeholder", base_url=base_url, timeout=20.0)

    def reload_clients(self) -> None:
        self._primary = self._make_client(primary=True)
        self._fallback = self._make_client(primary=False) if self._cfg.ai.fallback.enabled else None
        self._honcho = HonchoClient(self._cfg.honcho if self._cfg.honcho.enabled else None)
        log.info(f"AI clients reloaded — {self._cfg.ai.primary.provider} ({self._cfg.ai.primary.base_url})")

    # ── System prompt ─────────────────────────────────────────────────────────

    async def load_honcho_context(self, session_id: str) -> None:
        await self._honcho.start_session(session_id)
        self._honcho_context = await self._honcho.get_user_context()

    def _system_prompt(self) -> str:
        soul = _load_agent_file("SOUL.md", max_chars=3000)
        base = soul if soul else self._cfg.mir.personality_prompt.strip()
        parts = [base]

        if self._goal:
            parts.append(f"--- SESSION GOAL ---\n{self._goal}")

        if self._steering:
            parts.append(f"--- FOCUS ---\n{self._steering}")

        if self._extra_context:
            parts.append("--- BACKGROUND CONTEXT ---\n" + "\n".join(self._extra_context))

        memory = _load_agent_file("MEMORY.md", max_chars=900)
        if memory:
            parts.append(f"--- MEMORY ---\n{memory}")

        if self._honcho_context:
            parts.append(f"--- USER CONTEXT (Honcho) ---\n{self._honcho_context[:2000]}")

        if self._summary:
            parts.append(f"--- EARLIER CONVERSATION ---\n{self._summary}")

        return "\n\n".join(parts)

    # ── History management ────────────────────────────────────────────────────

    def clear_history(self) -> None:
        self._history = []
        self._summary = None

    def get_memory_contents(self) -> str:
        return _load_agent_file("MEMORY.md", max_chars=4000) or "(empty)"

    def get_tool_permissions(self) -> dict:
        return self._cfg.tools.permissions.model_dump()

    def set_tool_permission(self, tool_name: str, level: str) -> bool:
        perms = self._cfg.tools.permissions
        if not hasattr(perms, tool_name):
            return False
        try:
            setattr(perms, tool_name, PermissionLevel(level))
            save_config(self._cfg)
            return True
        except ValueError:
            return False

    async def force_compress(self) -> str:
        if not self._history:
            return "Nothing to compact."
        await self._maybe_compress(force=True)
        return f"Compacted {len(self._history)} messages → summary stored."

    # ── Chat ──────────────────────────────────────────────────────────────────

    async def chat(self, user_message: str) -> str:
        self._history.append({"role": "user", "content": user_message})
        self._pending_user = user_message

        await self._maybe_compress()

        messages = [{"role": "system", "content": self._system_prompt()}] + self._history

        response = await self._try_with_tools(self._primary, self._cfg.ai.primary.model, messages)

        if response is None and self._fallback:
            log.warning("Primary failed — trying fallback")
            fallback_messages = [{"role": "system", "content": self._system_prompt()}] + self._history
            response = await self._try_with_tools(self._fallback, self._cfg.ai.fallback.model, fallback_messages)

        if response is None:
            response = "I could not reach the AI engine right now. Please try again."

        self._history.append({"role": "assistant", "content": response})

        if self._pending_user:
            asyncio.create_task(self._honcho.add_messages(self._pending_user, response))
            self._pending_user = None

        return response

    async def one_shot(self, prompt: str, system: str = "", max_tokens: int = 150) -> str:
        sys_text = system or self._cfg.mir.personality_prompt or "You are Mimir."
        for client, model in [
            (self._primary, self._cfg.ai.primary.model),
            (self._fallback, self._cfg.ai.fallback.model) if self._fallback else (None, None),
        ]:
            if client is None:
                continue
            try:
                resp = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": sys_text},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=max_tokens,
                    temperature=0.7,
                )
                return resp.choices[0].message.content.strip()
            except Exception:
                continue
        return ""

    async def chat_with_image(self, user_message: str, image_b64: str) -> str:
        vision_content = [
            {"type": "text", "text": user_message},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
        ]
        self._history.append({"role": "user", "content": vision_content})
        self._pending_user = user_message

        await self._maybe_compress()
        messages = [{"role": "system", "content": self._system_prompt()}] + self._history

        response = await self._try_plain(self._primary, self._cfg.ai.primary.model, messages)
        if response is None and self._fallback:
            fallback_msgs = [{"role": "system", "content": self._system_prompt()}] + self._history
            response = await self._try_plain(self._fallback, self._cfg.ai.fallback.model, fallback_msgs)
        if response is None:
            response = "I could not analyze the image right now."

        self._history[-1] = {"role": "user", "content": f"[image] {user_message}"}
        self._history.append({"role": "assistant", "content": response})

        if self._pending_user:
            asyncio.create_task(self._honcho.add_messages(self._pending_user, response))
            self._pending_user = None

        return response

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _maybe_compress(self, force: bool = False) -> None:
        if not force and len(self._history) <= _COMPRESS_AT:
            return

        to_compress = self._history[:-_KEEP_RECENT] if not force else self._history
        if force:
            self._history = []
        else:
            self._history = self._history[-_KEEP_RECENT:]

        context = ""
        if self._summary:
            context = f"Earlier summary: {self._summary}\n\n"
        context += "Messages:\n" + "\n".join(
            f"{m['role'].upper()}: {m['content'][:200]}" for m in to_compress
        )

        try:
            client = self._fallback or self._primary
            model = self._cfg.ai.fallback.model if self._fallback else self._cfg.ai.primary.model
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "Summarize this conversation in at most 3 sentences."},
                    {"role": "user", "content": context},
                ],
                max_tokens=150,
                temperature=0.3,
            )
            self._summary = resp.choices[0].message.content.strip()
            log.info(f"Context compressed — {len(to_compress)} messages → summary")
        except Exception as e:
            log.warning(f"Compression failed: {e}")
            self._summary = context[:400]

    async def _try_with_tools(
        self, client: AsyncOpenAI, model: str, messages: list[dict]
    ) -> Optional[str]:
        active_tools = get_tool_list(self._cfg.tools)
        if not active_tools:
            return await self._try_plain(client, model, messages)

        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=self._cfg.ai.primary.temperature,
                max_tokens=512,
                tools=active_tools,
                tool_choice="auto",
            )
        except Exception:
            return await self._try_plain(client, model, messages)

        choice = resp.choices[0]

        if not choice.message.tool_calls:
            return choice.message.content

        tool_messages = list(messages) + [choice.message]

        for tc in choice.message.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            # Build human-readable description for permission dialog
            description = _tool_description(name, args)

            # Permission gate
            allowed = await self._check_permission(name, description)
            if not allowed:
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps({"error": "Permission denied by user."}),
                })
                continue

            log.info(f"Tool: {name}({args})")

            if self._on_tool_call:
                ev = tool_event(name, args)
                if ev:
                    asyncio.create_task(self._on_tool_call(ev))

            result = await execute_tool(name, args, self._cfg.tools)
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

        try:
            final = await client.chat.completions.create(
                model=model,
                messages=tool_messages,
                temperature=self._cfg.ai.primary.temperature,
                max_tokens=512,
            )
            return final.choices[0].message.content
        except Exception as e:
            log.error(f"Final response after tool failed: {e}")
            return None

    async def _try_plain(
        self, client: AsyncOpenAI, model: str, messages: list[dict]
    ) -> Optional[str]:
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=self._cfg.ai.primary.temperature,
                max_tokens=512,
            )
            return resp.choices[0].message.content
        except (APIError, APITimeoutError, Exception) as e:
            log.error(f"AI error ({model}): {e}")
            return None


def _tool_description(name: str, args: dict) -> str:
    """Human-readable description of what a tool call will do."""
    if name == "run_command":
        return f"Run command: `{args.get('command', '')}`"
    if name == "write_file":
        return f"Write to file: `{args.get('path', '')}`"
    if name == "read_file":
        return f"Read file: `{args.get('path', '')}`"
    if name == "browse_web":
        return f"Open URL: `{args.get('url', '')}`"
    if name == "take_screenshot":
        return "Take a screenshot of your desktop"
    if name == "notify_telegram":
        msg = args.get("message", "")[:60]
        return f"Send Telegram message: \"{msg}\""
    return name
