# CLAUDE.md — Mimir project

> Read this first. Everything needed to work on this codebase is here.

---

## What Mimir is

Mimir is a local-first AI voice assistant. It runs a Python backend (FastAPI + WebSocket)
and a React/Tauri frontend. Users bring their own LLM provider and API keys.

**Three usage modes:**
1. Voice assistant — wake word → STT → LLM → TTS
2. Text chat — type in the UI or send via WebSocket
3. Tool-using agent — web search, file access, shell, vision

**Character:** Norse wisdom keeper. Calm, direct, no filler. Defined in `SOUL.md`.

---

## Architecture

```
mimir/
├── core/                  Python FastAPI backend (port 8900, HTTPS)
│   ├── main.py            Server, WebSocket, REST endpoints
│   ├── ai/
│   │   ├── brain.py       LLM client, tool use, context compression
│   │   ├── tools.py       All tools: web_search, read_file, system_health, etc.
│   │   └── honcho.py      Optional memory client (graceful if disabled)
│   ├── voice/
│   │   ├── tts.py         Edge Neural TTS (primary) + Piper (fallback)
│   │   ├── wake.py        OpenWakeWord
│   │   └── stt.py         Faster-Whisper
│   ├── vision/
│   │   └── watcher.py     OpenCV + MediaPipe (optional)
│   ├── config/
│   │   └── loader.py      Pydantic config, reads ~/.config/mimir/config.yaml
│   └── sessions.py        Session logging
│
├── ui/                    React + Vite frontend
│   └── src/
│       ├── App.tsx         Classic UI
│       ├── AppHUD.tsx      Full Norse HUD (#/hud)
│       ├── AppSetup.tsx    First-run setup wizard (#/setup)
│       ├── api.ts          apiUrl() helper
│       └── ws/client.ts   WebSocket client
│
├── desktop/               Tauri 2 shell
│   └── src-tauri/
│       └── src/lib.rs     Sidecar launcher, system tray, TLS bypass
│
├── setup/                 Setup wizard logic (Python)
│   └── wizard.py          First-run config generator
│
├── agent/                 Mimir's identity files
│   ├── SOUL.md            Character definition (user-replaceable)
│   ├── MEMORY.md          Persistent learned facts (Mimir writes, user confirms)
│   └── USER.md            User profile (name, preferences)
│
├── SOUL.md                Default Norse identity (shipped with Mimir)
└── AGENTS.md              Instructions for non-Claude agent stacks
```

---

## Config

Active config is read from `~/.config/mimir/config.yaml` (Linux/Mac)
or `%APPDATA%\Mimir\config.yaml` (Windows).

The project's `core/config/default.yaml` is the template — never write user
secrets there.

**Key config sections:**
```yaml
ai:
  provider: openrouter        # openrouter | openai | anthropic | ollama | lmstudio
  base_url: https://openrouter.ai/api/v1
  model: openrouter/auto
  api_key: ""                 # Set during setup, stored in user config

voice:
  stt:
    engine: faster-whisper
    model: tiny               # tiny | base | small | medium | large-v3
  tts:
    engine: edge
    voice: en-US-AriaNeural
  wake:
    word: "hey mimir"

honcho:
  enabled: false              # Optional — set to true + provide host to enable
  host: localhost:8000

mir:
  name: Mimir
  user_name: User             # Set during setup
  wake_word: "hey mimir"
```

---

## Running locally

```bash
# Backend
cd core
uv pip install -r requirements.txt
python main.py

# Frontend (separate terminal)
cd ui
npm install
npm run dev

# Or via Tauri (starts both)
cd desktop
cargo tauri dev
```

---

## Key rules

1. **Never commit secrets** — `~/.config/mimir/config.yaml` is never in the repo
2. **SOUL.md is user-owned** — never overwrite it programmatically
3. **All frontend fetch uses `apiUrl()`** from `src/api.ts` — never hardcode ports
4. **Honcho is always optional** — every call to `honcho.py` must degrade gracefully
5. **CSS classes are `mir-*`** — not `jarvis-*`
6. **Install packages with `uv pip install`** — not pip directly

---

## REST endpoints

- `GET  /health` — backend status
- `GET  /config` — full config (no secrets)
- `POST /config` — save config
- `POST /speak` — text to TTS
- `GET  /system/health` — CPU/RAM/disk
- `POST /vision/start|stop` — webcam + MediaPipe
- `GET  /vision/status`
- `POST /vision/snap` — capture + LLM describe
- `GET  /providers` — available providers + active keys
- `GET  /setup/status` — is first-run complete?
- `POST /setup/complete` — mark setup done

---

## WebSocket events

Send: `{"action": "wake"}` `{"action": "chat", "text": "..."}` `{"action": "sleep"}`

Receive: `state_change` `chat_response` `wake` `sleep` `tool_call` `face_detected`

---

## First-run setup flow

If `~/.config/mimir/config.yaml` does not exist, Mimir redirects to `#/setup`.

Setup wizard collects:
1. User name
2. LLM provider + API key (tested live before saving)
3. TTS voice preference
4. Wake word
5. Optional: Honcho host
6. Optional: custom SOUL.md path

On complete: writes config, optionally downloads Whisper model, starts normally.

---

## Building

**Linux (.deb):**
```bash
docker build -t mimir-builder -f desktop/Dockerfile.build desktop/
docker run --rm -v "$(pwd):/workspace" mimir-builder
```

**Windows (.exe + .msi):**
```bash
# Requires Windows or GitHub Actions windows-latest runner
cd core && pyinstaller mimir-core.spec
cd desktop && cargo tauri build
```

**GitHub Actions:** See `.github/workflows/build.yml`
