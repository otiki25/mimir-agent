"""
Session logging — saves each Mimir conversation to a JSON file.
Filename: YYYY-MM-DD_NNNNN.json (globally incrementing 5-digit number)
"""
import json
import logging
import os
import platform
from datetime import datetime
from pathlib import Path

log = logging.getLogger("mimir.sessions")


def _sessions_dir() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "MimirAgent" / "sessions"
    return Path.home() / ".config" / "mimir-agent" / "sessions"


def _counter_file() -> Path:
    return _sessions_dir().parent / ".session_counter"


def _next_session_number() -> int:
    counter = _counter_file()
    counter.parent.mkdir(parents=True, exist_ok=True)
    current = 0
    if counter.exists():
        try:
            current = int(counter.read_text().strip())
        except ValueError:
            current = 0
    next_num = current + 1
    counter.write_text(str(next_num))
    return next_num


class Session:
    def __init__(self):
        self._messages: list[dict] = []
        self._started = datetime.now()
        self._path: Path | None = None
        self._number: int = 0

    def start(self) -> None:
        self._number = _next_session_number()
        self._started = datetime.now()
        date_str = self._started.strftime("%Y-%m-%d")
        filename = f"{date_str}_{self._number:05d}.json"
        logs_dir = _sessions_dir()
        logs_dir.mkdir(parents=True, exist_ok=True)
        self._path = logs_dir / filename
        self._messages = []
        self._save()
        log.info(f"Session #{self._number:05d} started — {filename}")

    def add(self, role: str, text: str) -> None:
        self._messages.append({
            "ts": datetime.now().isoformat(),
            "role": role,
            "text": text,
        })
        self._save()

    def end(self) -> None:
        if not self._path:
            return
        self._save(ended=True)
        log.info(f"Session #{self._number:05d} ended ({len(self._messages)} messages)")
        self._path = None

    def active(self) -> bool:
        return self._path is not None

    def _save(self, ended: bool = False) -> None:
        if not self._path:
            return
        data = {
            "session": self._number,
            "started": self._started.isoformat(),
            "ended": datetime.now().isoformat() if ended else None,
            "messages": self._messages,
        }
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
