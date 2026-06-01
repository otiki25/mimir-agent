"""
Mimir Tool Dispatcher — function-calling tools available to Brain.
"""
import json
import logging
import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("mimir.tools")

# ── Tool definitions ──────────────────────────────────────────────────────────

_TOOL_SYSTEM_HEALTH = {
    "type": "function",
    "function": {
        "name": "get_system_health",
        "description": (
            "Get hardware health for the server: CPU usage, RAM, disk, and uptime. "
            "Use when the user asks about server status, performance, or resources."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}

_TOOL_WEB_SEARCH = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the internet for up-to-date information. "
            "Use when the user asks about something you don't know, news, weather, prices, facts."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
}

_TOOL_DATETIME = {
    "type": "function",
    "function": {
        "name": "get_datetime",
        "description": "Get the current date and time. Use when the user asks about time or date.",
        "parameters": {"type": "object", "properties": {}},
    },
}

_TOOL_FILE_READ = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": (
            "Read the contents of a file. Only allowed in approved directories. "
            "Use when the user explicitly asks to read a file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
            },
            "required": ["path"],
        },
    },
}

_TOOL_FILE_WRITE = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": (
            "Write text to a file. Only allowed in approved directories. "
            "Use when the user explicitly asks to save, write, or create a file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write to"},
                "content": {"type": "string", "description": "Text to write"},
                "append": {"type": "boolean", "description": "True to append, False (default) to overwrite"},
            },
            "required": ["path", "content"],
        },
    },
}

_TOOL_SHELL = {
    "type": "function",
    "function": {
        "name": "run_command",
        "description": (
            "Run a system command and return its output. "
            "Only safe read-only commands are allowed (ls, ps, df, systemctl status, docker ps, etc.)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to run (e.g. 'ls -la /tmp' or 'systemctl status mimir')"},
            },
            "required": ["command"],
        },
    },
}

_TOOL_BROWSER = {
    "type": "function",
    "function": {
        "name": "browse_web",
        "description": (
            "Open a URL in a headless browser and fetch the page's text content. "
            "Use when the user asks to visit, read, or fetch content from a webpage."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to visit"},
                "screenshot": {"type": "boolean", "description": "Take a screenshot of the page (saved to /tmp/)"},
            },
            "required": ["url"],
        },
    },
}

_TOOL_SCREENSHOT = {
    "type": "function",
    "function": {
        "name": "take_screenshot",
        "description": (
            "Take a screenshot of the desktop and save it to /tmp/. "
            "Use when the user asks you to see what is on the screen."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}

_TOOL_TELEGRAM_NOTIFY = {
    "type": "function",
    "function": {
        "name": "notify_telegram",
        "description": (
            "Send a Telegram message to the user. The message is signed automatically with [Mimir]. "
            "Use for important notifications, warnings, results, or recommendations."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message text to send"},
                "urgent": {"type": "boolean", "description": "True for critical/urgent message — adds 🚨"},
            },
            "required": ["message"],
        },
    },
}


def get_tool_list(tools_cfg) -> list:
    result = []
    if getattr(tools_cfg, "system_health", True):
        result.append(_TOOL_SYSTEM_HEALTH)
    if getattr(tools_cfg, "web_search", True):
        result.append(_TOOL_WEB_SEARCH)
    if getattr(tools_cfg, "datetime", True):
        result.append(_TOOL_DATETIME)
    if getattr(tools_cfg, "file_read", False):
        result.append(_TOOL_FILE_READ)
    if getattr(tools_cfg, "file_write", False):
        result.append(_TOOL_FILE_WRITE)
    if getattr(tools_cfg, "shell", False):
        result.append(_TOOL_SHELL)
    if getattr(tools_cfg, "browser", False):
        result.append(_TOOL_BROWSER)
    if getattr(tools_cfg, "screenshot", False):
        result.append(_TOOL_SCREENSHOT)
    if getattr(tools_cfg, "telegram_notify", False):
        result.append(_TOOL_TELEGRAM_NOTIFY)
    return result


TOOLS = get_tool_list(None)


# ── Executors ─────────────────────────────────────────────────────────────────

async def execute_tool(name: str, arguments: dict, tools_cfg=None) -> str:
    try:
        if name == "get_system_health":
            return _system_health()

        elif name == "web_search":
            return await _web_search(arguments.get("query", ""))

        elif name == "get_datetime":
            return _get_datetime()

        elif name == "read_file":
            allowed = getattr(tools_cfg, "file_read_paths", ["~/Documents/"])
            return _read_file(arguments.get("path", ""), allowed)

        elif name == "write_file":
            allowed = getattr(tools_cfg, "file_write_paths", ["/tmp/"])
            return _write_file(
                arguments.get("path", ""),
                arguments.get("content", ""),
                allowed,
                append=arguments.get("append", False),
            )

        elif name == "run_command":
            return _run_command(arguments.get("command", ""))

        elif name == "browse_web":
            return await _browse_web(
                arguments.get("url", ""),
                take_screenshot=arguments.get("screenshot", False),
            )

        elif name == "take_screenshot":
            return _take_screenshot()

        elif name == "notify_telegram":
            token   = getattr(tools_cfg, "telegram_bot_token", "") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
            chat_id = getattr(tools_cfg, "telegram_chat_id", "") or os.environ.get("TELEGRAM_CHAT_ID", "")
            return await _notify_telegram(
                arguments.get("message", ""),
                token=token,
                chat_id=chat_id,
                urgent=arguments.get("urgent", False),
            )

        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

    except Exception as e:
        log.error(f"Tool {name} crashed: {e}")
        return json.dumps({"error": str(e)})


def _system_health() -> str:
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        uptime_secs = int(datetime.now().timestamp() - psutil.boot_time())
        hours, rem = divmod(uptime_secs, 3600)
        minutes = rem // 60
        return json.dumps({
            "cpu_percent": cpu,
            "ram_percent": round(ram.percent, 1),
            "ram_used_gb": round(ram.used / 1e9, 2),
            "ram_total_gb": round(ram.total / 1e9, 2),
            "disk_percent": round(disk.percent, 1),
            "disk_used_gb": round(disk.used / 1e9, 1),
            "disk_total_gb": round(disk.total / 1e9, 1),
            "uptime": f"{hours}h {minutes}m",
        })
    except ImportError:
        return json.dumps({"error": "psutil not installed"})


async def _web_search(query: str) -> str:
    if not query:
        return json.dumps({"error": "Empty search query"})
    try:
        from ddgs import DDGS
        results = list(DDGS().text(query, max_results=4))
        if not results:
            return json.dumps({"results": [], "message": "No results found"})
        return json.dumps({
            "results": [
                {"title": r.get("title", ""), "snippet": r.get("body", "")[:300], "url": r.get("href", "")}
                for r in results
            ]
        })
    except Exception as e:
        return json.dumps({"error": f"Search failed: {e}"})


def _get_datetime() -> str:
    now = datetime.now()
    return json.dumps({
        "weekday": now.strftime("%A"),
        "date": now.strftime("%B %d, %Y"),
        "time": now.strftime("%H:%M"),
        "iso": now.isoformat(),
    })


def _read_file(path: str, allowed_prefixes: list) -> str:
    expanded = os.path.expanduser(path)
    resolved = str(Path(expanded).resolve())
    allowed = [str(Path(os.path.expanduser(p)).resolve()) for p in allowed_prefixes]
    if not any(resolved.startswith(a) for a in allowed):
        return json.dumps({"error": f"Access denied. Allowed directories: {', '.join(allowed_prefixes)}"})
    try:
        content = Path(resolved).read_text(encoding="utf-8")
        return json.dumps({"path": resolved, "content": content[:4000]})
    except FileNotFoundError:
        return json.dumps({"error": f"File not found: {path}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


_SAFE_FIRST_WORDS = {
    "ls", "cat", "pwd", "ps", "df", "du", "free", "uname", "date",
    "who", "uptime", "find", "grep", "echo", "wc", "head", "tail",
    "hostname", "ip", "docker", "systemctl", "git", "curl", "ping",
    "journalctl", "env", "printenv", "id", "whoami", "lsof", "netstat",
    "ss", "top", "htop", "nmap", "traceroute",
}
_INJECT_RE = re.compile(r"[;&|`$><]|(\$\()")


def _run_command(command: str) -> str:
    command = command.strip()
    if not command:
        return json.dumps({"error": "Empty command"})
    if _INJECT_RE.search(command):
        return json.dumps({"error": "Shell injection not allowed (semicolons, pipes, redirects)"})
    parts = command.split()
    first = parts[0].lstrip("./")
    if first not in _SAFE_FIRST_WORDS:
        return json.dumps({"error": f"Command '{first}' not allowed. Allowed: {sorted(_SAFE_FIRST_WORDS)}"})
    try:
        result = subprocess.run(
            parts,
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "LANG": "en_US.UTF-8"},
        )
        output = (result.stdout or "") + (result.stderr or "")
        return json.dumps({
            "command": command,
            "exit_code": result.returncode,
            "output": output[:4000],
        })
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Command timed out (15s)"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _write_file(path: str, content: str, allowed_prefixes: list, append: bool = False) -> str:
    expanded = os.path.expanduser(path)
    resolved = str(Path(expanded).resolve())
    allowed = [str(Path(os.path.expanduser(p)).resolve()) for p in allowed_prefixes]
    if not any(resolved.startswith(a) for a in allowed):
        return json.dumps({"error": f"Access denied. Allowed directories: {', '.join(allowed_prefixes)}"})
    try:
        mode = "a" if append else "w"
        Path(resolved).parent.mkdir(parents=True, exist_ok=True)
        with open(resolved, mode, encoding="utf-8") as f:
            f.write(content)
        return json.dumps({"success": True, "path": resolved, "bytes": len(content.encode())})
    except Exception as e:
        return json.dumps({"error": str(e)})


async def _browse_web(url: str, take_screenshot: bool = False) -> str:
    if not url:
        return json.dumps({"error": "Empty URL"})
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, timeout=20000, wait_until="domcontentloaded")
            title = await page.title()
            text = await page.evaluate("""() => {
                const els = document.querySelectorAll('script,style,nav,header,footer,aside');
                els.forEach(e => e.remove());
                return document.body ? document.body.innerText : '';
            }""")
            text = re.sub(r"\n{3,}", "\n\n", text or "").strip()
            result: dict = {"url": url, "title": title, "content": text[:4000]}
            if take_screenshot:
                path = tempfile.mktemp(prefix="mimir_browser_", suffix=".png", dir="/tmp")
                await page.screenshot(path=path, full_page=False)
                result["screenshot"] = path
            await browser.close()
            return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": f"Browser failed: {e}"})


def _take_screenshot() -> str:
    path = tempfile.mktemp(prefix="mimir_screenshot_", suffix=".png", dir="/tmp")
    try:
        result = subprocess.run(
            ["scrot", "-z", path],
            capture_output=True, timeout=10,
            env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
        )
        if result.returncode != 0:
            return json.dumps({"error": f"scrot failed: {result.stderr.decode()[:200]}"})
        size = Path(path).stat().st_size if Path(path).exists() else 0
        return json.dumps({"success": True, "path": path, "size_kb": size // 1024})
    except Exception as e:
        return json.dumps({"error": str(e)})


_MIMIR_OUTBOX = Path.home() / ".config" / "mimir-agent" / "mimir_messages.jsonl"


async def _notify_telegram(message: str, token: str, chat_id: str, urgent: bool = False) -> str:
    if not message.strip():
        return json.dumps({"error": "Empty message"})
    if not token or not chat_id:
        return json.dumps({"error": "Telegram not configured (bot_token / chat_id missing)"})

    prefix = "🚨 " if urgent else ""
    signed = f"{prefix}[Mimir]\n{message.strip()}"

    try:
        import httpx
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json={"chat_id": chat_id, "text": signed, "parse_mode": "HTML"})
            r.raise_for_status()
            msg_id = r.json().get("result", {}).get("message_id")
    except Exception as e:
        return json.dumps({"error": f"Telegram send failed: {e}"})

    try:
        _MIMIR_OUTBOX.parent.mkdir(parents=True, exist_ok=True)
        with open(_MIMIR_OUTBOX, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now().isoformat(),
                "message": message,
                "urgent": urgent,
                "msg_id": msg_id,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass

    return json.dumps({"success": True, "message_id": msg_id, "sent": signed[:80]})


def tool_event(name: str, arguments: dict) -> Optional[dict]:
    if name == "get_system_health":
        return {"tool": "system_health"}
    if name == "web_search":
        return {"tool": "web_search", "query": arguments.get("query", "")}
    if name == "get_datetime":
        return {"tool": "datetime"}
    if name == "read_file":
        return {"tool": "read_file", "path": arguments.get("path", "")}
    if name == "write_file":
        return {"tool": "write_file", "path": arguments.get("path", "")}
    if name == "run_command":
        return {"tool": "shell", "command": arguments.get("command", "")}
    if name == "browse_web":
        return {"tool": "browser", "url": arguments.get("url", "")}
    if name == "take_screenshot":
        return {"tool": "screenshot"}
    if name == "notify_telegram":
        return {"tool": "telegram", "message": arguments.get("message", "")[:60]}
    return None
