# AGENTS.md — Mimir project

Instructions for AI agent stacks working on this codebase.
If you're using Claude Code, read CLAUDE.md instead — it's more detailed.

---

## What this project is

Mimir is a local-first AI voice assistant. Python backend + React/Tauri frontend.
Users bring their own LLM provider. No private config in this repo.

## Key files to understand first

1. `CLAUDE.md` — full architecture and rules
2. `core/config/loader.py` — how config works
3. `core/ai/brain.py` — LLM client and tool use
4. `ui/src/AppHUD.tsx` — main UI component

## Rules

- Never write secrets or personal config to any file in this repo
- SOUL.md is user-owned — never overwrite it programmatically
- Honcho integration must always be optional (graceful degradation)
- All CSS classes are `mir-*`
- Use `apiUrl()` from `ui/src/api.ts` for all fetch calls

## Stack

- Python 3.11+ / FastAPI / uv
- React 18 / Vite / TypeScript
- Tauri 2 / Rust
- Faster-Whisper (STT)
- Edge TTS / Piper (TTS)
- OpenWakeWord (wake word)
- OpenCV + MediaPipe (vision, optional)
