"""
Mimir Core — WebSocket + REST server
"""
import asyncio
import json
import logging
import os
import random
import subprocess
from datetime import datetime
from typing import Set

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")

from config.loader import load_config, save_config, Config
from voice.tts import TTSEngine
from voice.wake import WakeDetector
from ai.brain import Brain
from sessions import Session
from vision.watcher import VisionWatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mimir")

app = FastAPI(title="Mimir Core", version="0.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

cfg: Config = load_config()

# Serve built React UI
_UI_DIST = Path(__file__).parent.parent / "ui" / "dist"
if _UI_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(_UI_DIST / "assets")), name="assets")

    @app.get("/")
    async def serve_ui():
        return FileResponse(str(_UI_DIST / "index.html"))

_clients: Set[WebSocket] = set()
_state = {
    "status": "idle",
    "wake_active": False,
    "started_at": datetime.now().isoformat(),
}

tts = TTSEngine(engine=cfg.voice.tts.engine, voice=cfg.voice.tts.voice, speed=cfg.voice.tts.speed)
wake = WakeDetector(wake_word=cfg.mir.wake_word, sensitivity=cfg.voice.wake.sensitivity)
brain = Brain(cfg)
session = Session()


async def _on_tool_call(event_data: dict) -> None:
    await broadcast("tool_call", event_data)


brain.set_tool_callback(_on_tool_call)

# ── Vision watcher ────────────────────────────────────────────────────────────

_loop: asyncio.AbstractEventLoop | None = None


def _vision_event(event: str, data: dict):
    if _loop is None:
        return
    asyncio.run_coroutine_threadsafe(_dispatch_vision(event, data), _loop)


async def _dispatch_vision(event: str, data: dict):
    await broadcast(event, data)
    if event == "face_detected" and cfg.vision.auto_wake and _state["status"] == "idle":
        log.info("Face detected — auto-waking Mimir")
        await handle_wake(do_tts=True, vision_greeting=True)
    elif event == "gesture":
        gesture = data.get("gesture")
        if gesture == "thumbs_up":
            await tts.speak("Got it.")
        elif gesture == "wave" and _state["status"] == "idle":
            await handle_wake(do_tts=True)


_watcher = VisionWatcher(on_event=_vision_event, device=cfg.vision.device)

_GREETINGS = [
    "The hall is quiet. What do you need?",
    "I am here. Systems holding.",
    "Welcome back. Everything looks normal.",
    "The hall holds. What needs doing?",
    "I am listening. What brings you here?",
]

_SLEEP_RESPONSES = [
    "Understood. The hall is watched.",
    "I withdraw. Call if anything changes.",
    "Silence. I am here when you need me.",
]

_VISION_GREETINGS = [
    "The hall sees you. What do you need?",
    "I see you are back. Systems holding.",
    "Eyes open. Ready.",
    "Presence confirmed. What needs doing?",
]


# ── Broadcast ─────────────────────────────────────────────────────────────────

async def broadcast(event: str, data: dict) -> None:
    msg = json.dumps({"event": event, "data": data, "ts": datetime.now().isoformat()})
    dead = set()
    for ws in _clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    _clients.difference_update(dead)


# ── Wake handler ──────────────────────────────────────────────────────────────

def _is_local(ws: WebSocket) -> bool:
    host = ws.client.host if ws.client else "127.0.0.1"
    return host in ("127.0.0.1", "::1", "localhost")


async def handle_wake(do_tts: bool = True, vision_greeting: bool = False) -> None:
    log.info("Mimir awakened")
    _state["wake_active"] = True
    await _set_state("listening")

    if cfg.ui.screen_wake_command:
        try:
            subprocess.Popen(cfg.ui.screen_wake_command.split())
        except Exception as e:
            log.warning(f"screen_wake failed: {e}")

    if not cfg.mir.greeting_enabled:
        greeting = ""
    elif vision_greeting:
        greeting = random.choice(_VISION_GREETINGS)
    else:
        greeting = random.choice(_GREETINGS)

    await broadcast("wake", {"status": "listening", "greeting": greeting})

    session.start()
    asyncio.create_task(brain.load_honcho_context(str(session._number)))
    if greeting:
        session.add("mimir", greeting)
        if do_tts:
            await _set_state("speaking")
            await tts.speak(greeting)
            await _set_state("listening")


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    _clients.add(ws)
    log.info(f"Client connected — {len(_clients)} active")

    await ws.send_text(json.dumps({
        "event": "connected",
        "data": {"name": cfg.mir.name, "version": "0.3.0", "state": _state},
        "ts": datetime.now().isoformat(),
    }))

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            await _handle_client_message(ws, msg)
    except WebSocketDisconnect:
        _clients.discard(ws)
        log.info(f"Client disconnected — {len(_clients)} active")


async def _handle_client_message(ws: WebSocket, msg: dict) -> None:
    action = msg.get("action")
    try:
        if action == "ping":
            await ws.send_text(json.dumps({"event": "pong", "ts": datetime.now().isoformat()}))

        elif action == "wake":
            await handle_wake(do_tts=_is_local(ws))

        elif action == "new_session":
            brain.clear_history()
            if session.active():
                session.end()
            await broadcast("session_reset", {"status": "ready"})
            await ws.send_text(json.dumps({
                "event": "session_reset",
                "data": {"message": "New session started"},
                "ts": datetime.now().isoformat(),
            }))
            log.info("New session started by user")

        elif action == "sleep":
            response = random.choice(_SLEEP_RESPONSES)
            await broadcast("sleep", {"status": "idle", "response": response})
            session.add("mimir", response)
            session.end()
            if _is_local(ws):
                await tts.speak(response)
            await _set_state("idle")
            _state["wake_active"] = False

        elif action == "speak":
            text = msg.get("text", "")
            if text:
                await _set_state("speaking")
                await tts.speak(text)
                await _set_state("idle")

        elif action == "chat":
            text = msg.get("text", "").strip()
            if text:
                log.info(f"User: {text[:80]}")
                await broadcast("chat_input", {"text": text})
                session.add("user", text)
                await _set_state("thinking")
                response = await brain.chat(text)
                session.add("mimir", response)
                await broadcast("chat_response", {"text": response})
                if _is_local(ws):
                    await _set_state("speaking")
                    await tts.speak(response)
                    prev = "listening" if _state.get("wake_active") else "idle"
                    await _set_state(prev)
                else:
                    await _set_state("idle")

        elif action == "chat_with_image":
            text = msg.get("text", "").strip() or "What do you see in this image?"
            b64  = msg.get("image_b64", "")
            if b64:
                log.info(f"User (image): {text[:60]}")
                await broadcast("chat_input", {"text": f"📎 {text}"})
                session.add("user", f"[image] {text}")
                await _set_state("thinking")
                response = await brain.chat_with_image(text, b64)
                session.add("mimir", response)
                await broadcast("chat_response", {"text": response})
                if _is_local(ws):
                    await _set_state("speaking")
                    await tts.speak(response)
                    prev = "listening" if _state.get("wake_active") else "idle"
                    await _set_state(prev)
                else:
                    await _set_state("idle")

        elif action == "clear_history":
            brain.clear_history()
            await ws.send_text(json.dumps({"event": "history_cleared", "ts": datetime.now().isoformat()}))

        elif action == "get_config":
            await ws.send_text(json.dumps({
                "event": "config", "data": cfg.model_dump(),
                "ts": datetime.now().isoformat(),
            }))

        elif action == "get_state":
            await ws.send_text(json.dumps({
                "event": "state", "data": _state,
                "ts": datetime.now().isoformat(),
            }))

    except Exception as e:
        log.error(f"Error handling action '{action}': {e}", exc_info=True)
        try:
            await ws.send_text(json.dumps({
                "event": "error", "data": {"action": action, "message": str(e)},
                "ts": datetime.now().isoformat(),
            }))
        except Exception:
            pass


async def _set_state(status: str) -> None:
    _state["status"] = status
    await broadcast("state_change", {"status": status})


# ── REST ──────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok", "name": cfg.mir.name, "version": "0.3.0",
        "clients": len(_clients), "state": _state["status"],
        "uptime_since": _state["started_at"],
        "tts_ready": tts.engine == "edge" or tts._piper_voice_path is not None,
    }


@app.get("/system/health")
async def system_health():
    import json as _json
    from ai.tools import _system_health
    return _json.loads(_system_health())


@app.get("/config")
async def get_config():
    data = cfg.model_dump()
    soul_path = Path(__file__).parent.parent / "agent" / "SOUL.md"
    data["_soul_active"] = soul_path.exists() and soul_path.stat().st_size > 0
    return data


@app.post("/wake")
async def api_wake():
    await handle_wake()
    return {"ok": True}


@app.post("/sleep")
async def api_sleep():
    response = random.choice(_SLEEP_RESPONSES)
    await _set_state("idle")
    _state["wake_active"] = False
    asyncio.create_task(tts.speak(response))
    return {"ok": True, "response": response}


@app.post("/speak")
async def api_speak(body: dict):
    text = body.get("text", "")
    if text:
        asyncio.create_task(tts.speak(text))
    return {"ok": True}


@app.post("/notify")
async def api_notify(body: dict):
    """External message channel — send a message through Mimir's brain and get a response.

    Body: {"text": "...", "source": "external", "speak": true}
    """
    text = body.get("text", "").strip()
    source = body.get("source", "external")
    do_speak = body.get("speak", True)

    if not text:
        return {"ok": False, "error": "Empty message"}

    log.info(f"Notify from {source}: {text[:80]}")
    await broadcast("chat_input", {"text": text, "source": source})
    session.add("user", f"[{source}] {text}")
    await _set_state("thinking")
    response = await brain.chat(text)
    session.add("mimir", response)
    await broadcast("chat_response", {"text": response, "source": source})

    if do_speak:
        await _set_state("speaking")
        await tts.speak(response)

    await _set_state("idle")
    return {"ok": True, "response": response}


@app.post("/config")
async def save_config_endpoint(body: dict):
    from pydantic import ValidationError
    try:
        new_cfg = cfg.__class__(**body)
        save_config(new_cfg)
        for field in cfg.model_fields:
            setattr(cfg, field, getattr(new_cfg, field))
        tts.engine = cfg.voice.tts.engine
        tts.voice = cfg.voice.tts.voice
        tts.speed = cfg.voice.tts.speed
        tts.setup()
        brain.reload_clients()
        _save_env_keys(body)
        log.info("Config updated")
        return {"ok": True}
    except ValidationError as e:
        return {"ok": False, "error": str(e)}


def _save_env_keys(body: dict) -> None:
    env_path = Path(__file__).parent.parent / ".env"
    keys = {}
    if "api_keys" in body:
        for k, v in body["api_keys"].items():
            if v:
                keys[k] = v
    if not keys:
        return
    existing = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()
    existing.update(keys)
    env_path.write_text("\n".join(f"{k}={v}" for k, v in existing.items()) + "\n")
    for k, v in keys.items():
        os.environ[k] = v


@app.get("/vision/status")
async def vision_status():
    return {
        "enabled": cfg.vision.enabled,
        "running": _watcher.running,
        "face_present": _watcher.face_present,
        "last_gesture": _watcher.last_gesture,
        "device": cfg.vision.device,
        "auto_wake": cfg.vision.auto_wake,
    }


@app.post("/vision/start")
async def vision_start():
    cfg.vision.enabled = True
    ok = _watcher.start()
    save_config(cfg)
    return {"started": ok}


@app.post("/vision/stop")
async def vision_stop():
    cfg.vision.enabled = False
    _watcher.stop()
    save_config(cfg)
    return {"stopped": True}


@app.post("/vision/snap")
async def vision_snap():
    b64 = _watcher.snap()
    if not b64:
        return {"error": "Could not capture from camera"}
    response = await brain.chat_with_image(
        "Briefly describe what you see in the image. Two sentences max.",
        image_b64=b64,
    )
    return {"image_b64": b64, "description": response}


@app.get("/providers")
async def list_providers():
    return {
        "providers": [
            {
                "id": "openrouter",
                "name": "OpenRouter",
                "base_url": "https://openrouter.ai/api/v1",
                "key_env": "OPENROUTER_API_KEY",
                "models": ["openai/gpt-4o", "anthropic/claude-sonnet-4-5", "google/gemini-2.5-pro", "openrouter/auto"],
            },
            {
                "id": "openai",
                "name": "OpenAI",
                "base_url": "https://api.openai.com/v1",
                "key_env": "OPENAI_API_KEY",
                "models": ["gpt-4o", "gpt-4o-mini", "o1-mini"],
            },
            {
                "id": "anthropic",
                "name": "Anthropic",
                "base_url": "https://api.anthropic.com/v1",
                "key_env": "ANTHROPIC_API_KEY",
                "models": ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
            },
            {
                "id": "ollama_cloud",
                "name": "Ollama Cloud",
                "base_url": "https://ollama.com/v1",
                "key_env": "OLLAMA_API_KEY",
                "models": ["gemma4:31b", "gemma4:12b", "llama3.3:70b"],
            },
            {
                "id": "ollama",
                "name": "Ollama (local)",
                "base_url": "http://localhost:11434/v1",
                "key_env": "",
                "models": [],
            },
            {
                "id": "lmstudio",
                "name": "LM Studio (local)",
                "base_url": "",
                "key_env": "",
                "models": [],
            },
        ],
        "active_keys": {
            "OPENROUTER_API_KEY": bool(os.environ.get("OPENROUTER_API_KEY")),
            "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY")),
            "ANTHROPIC_API_KEY": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "OLLAMA_API_KEY": bool(os.environ.get("OLLAMA_API_KEY")),
        }
    }


@app.get("/setup/status")
async def setup_status():
    return {"complete": cfg.setup_complete}


@app.post("/setup/complete")
async def setup_complete():
    cfg.setup_complete = True
    save_config(cfg)
    return {"ok": True}


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    global _loop
    _loop = asyncio.get_event_loop()
    tts.setup()
    wake.on_wake(handle_wake)
    wake.start()
    if cfg.vision.enabled:
        ok = _watcher.start()
        log.info("Vision watcher: %s (device=%d)", "OK" if ok else "FAILED", cfg.vision.device)
    log.info(f"Mimir Core v0.3.0 ready — port {cfg.server.port}")
    log.info(f"TTS: {cfg.voice.tts.engine} / voice: {cfg.voice.tts.voice}")
    log.info(f"Wake: '{cfg.mir.wake_word}' (sensitivity {cfg.voice.wake.sensitivity})")


if _UI_DIST.exists():
    @app.get("/{file_path:path}")
    async def serve_static(file_path: str):
        full = _UI_DIST / file_path
        if full.exists() and full.is_file():
            return FileResponse(str(full))
        return FileResponse(str(_UI_DIST / "index.html"))


def main():
    cert_dir = Path(__file__).parent.parent / "cert"
    ssl_cert = cert_dir / "cert.pem"
    ssl_key  = cert_dir / "key.pem"
    use_ssl  = ssl_cert.exists() and ssl_key.exists()

    if use_ssl:
        log.info("HTTPS enabled (self-signed cert)")
    else:
        log.warning("Running without HTTPS — microphone only works on localhost")

    uvicorn.run(
        "main:app",
        host=cfg.server.host,
        port=cfg.server.port,
        log_level="warning",
        reload=False,
        ssl_certfile=str(ssl_cert) if use_ssl else None,
        ssl_keyfile=str(ssl_key)  if use_ssl else None,
    )


if __name__ == "__main__":
    main()
