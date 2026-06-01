# Mimir

A local-first AI voice assistant with a Norse soul.

Mimir listens, thinks, and speaks. He runs on your machine, uses your API keys,
and remembers what matters. No cloud required. No subscriptions. No data leaving
your machine unless you choose it.

---

## Features

- **Voice interface** — wake word, speech-to-text, text-to-speech
- **LLM agnostic** — bring your own provider (OpenRouter, OpenAI, Claude, Ollama)
- **Tool use** — web search, file access, system health, shell commands
- **Memory** — optional Honcho integration for persistent context across sessions
- **HUD** — full Norse-themed heads-up display
- **Extensible** — clean codebase, agent-readable docs, works with Claude Code / Codex / OpenCode / Hermes

---

## Quick start

1. Download the installer for your platform
2. Run the setup wizard — choose your LLM provider, enter your API key
3. Say "Hei Mimir" (or your configured wake word)

---

## Providers supported

| Provider | Type | Cost |
|---|---|---|
| Ollama (local) | Local | Free |
| LM Studio | Local | Free |
| OpenRouter | Cloud | Pay-per-use |
| OpenAI / Codex | Cloud | Pay-per-use |
| Anthropic (Claude) | Cloud | Pay-per-use |
| Ollama Cloud | Cloud | Free tier |

---

## Optional: Honcho memory

Mimir works without memory. To enable persistent context across sessions,
run Honcho locally (Docker) and point Mimir to it during setup.

See [docs/honcho.md](docs/honcho.md) for setup instructions.

---

## Customization

Mimir ships with a default Norse identity (`SOUL.md`). Replace it with your own
to change his personality, language, or tone completely.

See [docs/soul.md](docs/soul.md) for guidance.

---

## Extending Mimir

The codebase is designed to be worked on by AI agents and humans alike.
Read `CLAUDE.md` if you're using Claude Code, or `AGENTS.md` for other agent stacks.

---

## License

MIT
