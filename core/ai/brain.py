"""
Mimir AI Brain — LLM with tool-use and context compression
"""
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional, Callable

from openai import AsyncOpenAI, APIError, APITimeoutError

from config.loader import Config
from ai.honcho import HonchoClient
from ai.tools import get_tool_list, execute_tool, tool_event

log = logging.getLogger("mimir.brain")

_KEEP_RECENT = 8
_COMPRESS_AT = 16

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
        self._on_tool_call: Optional[Callable] = None

    def set_tool_callback(self, cb: Callable) -> None:
        self._on_tool_call = cb

    _KEY_MAP = {
        "openrouter":    lambda: os.environ.get("OPENROUTER_API_KEY", ""),
        "openai":        lambda: os.environ.get("OPENAI_API_KEY", ""),
        "anthropic":     lambda: os.environ.get("ANTHROPIC_API_KEY", ""),
        "ollama_cloud":  lambda: os.environ.get("OLLAMA_API_KEY", "ollama"),
        "ollama":        lambda: "ollama",
        "lmstudio":      lambda: "lmstudio",
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
        log.debug(f"{'Primary' if primary else 'Fallback'} client: {provider} → {base_url}")
        return AsyncOpenAI(api_key=api_key or "placeholder", base_url=base_url, timeout=20.0)

    def reload_clients(self) -> None:
        self._primary = self._make_client(primary=True)
        self._fallback = self._make_client(primary=False) if self._cfg.ai.fallback.enabled else None
        self._honcho = HonchoClient(self._cfg.honcho if self._cfg.honcho.enabled else None)
        log.info(
            f"AI clients reloaded — primary: {getattr(self._cfg.ai.primary, 'provider', '?')} "
            f"({self._cfg.ai.primary.base_url})"
        )

    async def load_honcho_context(self, session_id: str) -> None:
        await self._honcho.start_session(session_id)
        self._honcho_context = await self._honcho.get_user_context()

    def _system_prompt(self) -> str:
        soul = _load_agent_file("SOUL.md", max_chars=3000)
        base = soul if soul else self._cfg.mir.personality_prompt.strip()

        parts = [base]

        memory = _load_agent_file("MEMORY.md", max_chars=900)
        if memory:
            parts.append(f"--- MEMORY ---\n{memory}")

        if self._honcho_context:
            parts.append(f"--- USER CONTEXT (Honcho) ---\n{self._honcho_context[:2000]}")

        if self._summary:
            parts.append(f"--- EARLIER CONVERSATION ---\n{self._summary}")

        return "\n\n".join(parts)

    def clear_history(self) -> None:
        self._history = []
        self._summary = None

    async def chat(self, user_message: str) -> str:
        self._history.append({"role": "user", "content": user_message})
        self._pending_user = user_message

        await self._maybe_compress()

        messages = [{"role": "system", "content": self._system_prompt()}] + self._history

        response = await self._try_with_tools(
            self._primary, self._cfg.ai.primary.model, messages
        )

        if response is None and self._fallback:
            log.warning("Primary failed — trying fallback")
            fallback_messages = [{"role": "system", "content": self._system_prompt()}] + self._history
            response = await self._try_with_tools(
                self._fallback, self._cfg.ai.fallback.model, fallback_messages
            )

        if response is None:
            response = "I could not reach the AI engine right now. Please try again."

        self._history.append({"role": "assistant", "content": response})

        if self._pending_user:
            asyncio.create_task(
                self._honcho.add_messages(self._pending_user, response)
            )
            self._pending_user = None

        return response

    async def one_shot(self, prompt: str, system: str = "", max_tokens: int = 150) -> str:
        sys_text = system or self._cfg.mir.personality_prompt or "You are Mimir, a calm Norse wisdom keeper."
        try:
            resp = await self._primary.chat.completions.create(
                model=self._cfg.ai.primary.model,
                messages=[
                    {"role": "system", "content": sys_text},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.7,
            )
            return resp.choices[0].message.content.strip()
        except Exception:
            if self._fallback:
                try:
                    resp = await self._fallback.chat.completions.create(
                        model=self._cfg.ai.fallback.model,
                        messages=[
                            {"role": "system", "content": sys_text},
                            {"role": "user", "content": prompt},
                        ],
                        max_tokens=max_tokens,
                        temperature=0.7,
                    )
                    return resp.choices[0].message.content.strip()
                except Exception:
                    pass
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

    async def _maybe_compress(self) -> None:
        if len(self._history) <= _COMPRESS_AT:
            return

        to_compress = self._history[:-_KEEP_RECENT]
        self._history = self._history[-_KEEP_RECENT:]

        context = ""
        if self._summary:
            context = f"Earlier summary: {self._summary}\n\n"
        context += "New messages:\n" + "\n".join(
            f"{m['role'].upper()}: {m['content'][:200]}" for m in to_compress
        )

        summary_prompt = [
            {"role": "system", "content": "You are an assistant that creates brief summaries of conversations. Reply with at most 3 sentences."},
            {"role": "user", "content": f"Summarize this conversation history:\n\n{context}"},
        ]

        try:
            client = self._fallback or self._primary
            model = self._cfg.ai.fallback.model if self._fallback else self._cfg.ai.primary.model
            resp = await client.chat.completions.create(
                model=model,
                messages=summary_prompt,
                max_tokens=150,
                temperature=0.3,
            )
            self._summary = resp.choices[0].message.content.strip()
            log.info(f"Context compressed — {len(to_compress)} messages → summary")
        except Exception as e:
            log.warning(f"Compression failed, keeping as text: {e}")
            self._summary = context[:400]

    async def _try_with_tools(
        self, client: AsyncOpenAI, model: str, messages: list[dict]
    ) -> Optional[str]:
        active_tools = get_tool_list(getattr(self._cfg, "tools", None))
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

            log.info(f"Tool: {name}({args})")

            if self._on_tool_call:
                ev = tool_event(name, args)
                if ev:
                    asyncio.create_task(self._on_tool_call(ev))

            result = await execute_tool(name, args, getattr(self._cfg, "tools", None))
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
