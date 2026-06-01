"""
Honcho integration — fetch user context and log conversations.
Disabled gracefully when honcho.enabled = false in config.
"""
import logging
from datetime import datetime
from typing import Optional

import httpx

log = logging.getLogger("mimir.honcho")


class HonchoClient:
    def __init__(self, cfg=None):
        self._cfg = cfg
        self._client = httpx.AsyncClient(timeout=5.0)
        self._session_id: Optional[str] = None

    def _enabled(self) -> bool:
        return self._cfg is not None and getattr(self._cfg, "enabled", False)

    def _base(self) -> str:
        host = getattr(self._cfg, "host", "localhost:8000") if self._cfg else "localhost:8000"
        return f"http://{host}/v3"

    def _workspace(self) -> str:
        return getattr(self._cfg, "workspace", "mimir") if self._cfg else "mimir"

    def _peer(self) -> str:
        return getattr(self._cfg, "peer_id", "user") if self._cfg else "user"

    async def get_user_context(self) -> Optional[str]:
        if not self._enabled():
            return None
        try:
            ws, peer = self._workspace(), self._peer()
            r = await self._client.get(f"{self._base()}/workspaces/{ws}/peers/{peer}/context")
            if r.status_code == 200:
                rep = r.json().get("representation", "")
                if rep:
                    log.info("Honcho context fetched")
                    return rep
        except Exception as e:
            log.warning(f"Honcho context fetch failed: {e}")
        return None

    async def start_session(self, session_id: str) -> None:
        if not self._enabled():
            return
        self._session_id = f"mimir-{session_id}"
        try:
            r = await self._client.post(
                f"{self._base()}/workspaces/{self._workspace()}/sessions",
                json={"id": self._session_id},
            )
            if r.status_code not in (200, 201, 409):
                log.warning(f"Honcho session create: {r.status_code}")
            else:
                log.info(f"Honcho session: {self._session_id}")
        except Exception as e:
            log.warning(f"Honcho session failed: {e}")

    async def add_messages(self, user_text: str, mimir_text: str) -> None:
        if not self._enabled() or not self._session_id:
            return
        try:
            peer = self._peer()
            messages = [
                {"peer_id": peer, "content": user_text,
                 "metadata": {"role": "user", "source": "mimir"},
                 "created_at": datetime.now().isoformat()},
                {"peer_id": "mimir", "content": mimir_text,
                 "metadata": {"role": "assistant", "source": "mimir"},
                 "created_at": datetime.now().isoformat()},
            ]
            await self._client.post(
                f"{self._base()}/workspaces/{self._workspace()}/sessions/{self._session_id}/messages",
                json={"messages": messages},
            )
        except Exception as e:
            log.warning(f"Honcho message logging failed: {e}")

    async def end_session(self) -> None:
        self._session_id = None
