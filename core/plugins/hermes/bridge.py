"""
Hermes Bridge — optional plugin that connects Mimir to a local Hermes agent fleet.

This plugin is NOT included in the public Mimir Agent distribution.
To enable it, install Hermes locally and set tools.hermes = true in config.yaml.

Requires:
  - ~/.hermes/hermes-agent/ (Hermes installation)
  - Hermes gateway running on localhost:7800
"""
import logging
import os
import sys
from typing import Optional

import httpx

log = logging.getLogger("mimir.hermes")

_HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
_HERMES_AGENT = os.path.join(_HERMES_HOME, "hermes-agent")
_HTTP_BASE = "http://localhost:7800"


def _kb():
    os.environ.setdefault("HERMES_HOME", _HERMES_HOME)
    if _HERMES_AGENT not in sys.path:
        sys.path.insert(0, _HERMES_AGENT)
    from hermes_cli import kanban_db
    return kanban_db


class HermesBridge:
    def __init__(self):
        self._client = httpx.AsyncClient(timeout=5.0)

    def create_task_sync(
        self,
        title: str,
        body: str = "",
        assignee: str = "mimir",
        priority: int = 0,
    ) -> str:
        kb = _kb()
        db_path = kb.kanban_db_path()
        conn = kb.connect(db_path)
        try:
            task_id = kb.create_task(
                conn,
                title=title,
                body=body,
                assignee=assignee,
                created_by="mimir",
                priority=priority,
            )
            log.info(f"Hermes task created: {task_id} → {assignee}")
            return task_id
        finally:
            conn.close()

    def get_tasks_sync(self, assignee: Optional[str] = None, status: Optional[str] = None) -> list:
        kb = _kb()
        db_path = kb.kanban_db_path()
        conn = kb.connect(db_path)
        try:
            tasks = kb.list_tasks(conn, assignee=assignee, status=status)
            return [
                {
                    "id": t.id,
                    "title": t.title,
                    "assignee": t.assignee,
                    "status": t.status,
                    "priority": t.priority,
                }
                for t in tasks
                if t.status not in ("done", "archived")
            ]
        finally:
            conn.close()

    async def create_task(
        self,
        title: str,
        body: str = "",
        assignee: str = "mimir",
        priority: int = 0,
    ) -> dict:
        import asyncio
        try:
            task_id = await asyncio.to_thread(
                self.create_task_sync, title, body, assignee, priority
            )
            return {"ok": True, "task_id": task_id}
        except Exception as e:
            log.warning(f"create_task failed: {e}")
            return {"ok": False, "error": str(e)}

    async def get_tasks(self, assignee: Optional[str] = None) -> list:
        import asyncio
        try:
            return await asyncio.to_thread(self.get_tasks_sync, assignee)
        except Exception as e:
            log.warning(f"get_tasks failed: {e}")
            return []

    async def get_status(self) -> dict:
        try:
            r = await self._client.get(f"{_HTTP_BASE}/api/status")
            return r.json()
        except Exception as e:
            log.warning(f"get_status failed: {e}")
            return {"error": str(e)}

    async def get_activity(self, limit: int = 10) -> list:
        try:
            r = await self._client.get(f"{_HTTP_BASE}/api/activity")
            items = r.json()
            return items[:limit] if isinstance(items, list) else []
        except Exception as e:
            log.warning(f"get_activity failed: {e}")
            return []
