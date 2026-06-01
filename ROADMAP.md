# Mimir Agent — Roadmap

> Full utviklingsplan for Mimir Agent. Oppdateres etter hvert fase ferdigstilles.
> Siste oppdatering: 2026-06-01

---

## Prosjektstatus

**Mimir Agent** er en lokal-first AI-stemmeassistent med norrøn karakter.
Brukeren tar med sin egen LLM-leverandør og API-nøkkel. Ingen sky-avhengighet utover det.

Distribusjonsmodell: Én installasjonspakke (`.deb` Linux, `.exe`/`.msi` Windows).
Dobbeltklikk → setup-wizard → klar. Ingen Python-installasjon, ingen WSL2.

---

## Arkitektur-beslutninger (ikke reverser uten grunn)

| Beslutning | Begrunnelse |
|-----------|-------------|
| Nativt Windows via PyInstaller — ikke WSL2 | Brukerne vil ikke ha WSL2 |
| Edge Neural TTS primær, Piper fallback | Edge er dramatisk bedre; Piper fungerer offline |
| Honcho er alltid valgfritt | Mimir skal fungere uten minnelag |
| SOUL.md er brukereiet — aldri overskriv | Identiteten er personlig |
| Permission-system: always/ask/never | Som Claude Code — spør ved behov, husk svaret |
| `/`-kommandoer i chat-input | Samme UX som Claude Code slash-kommandoer |
| Hermes-integrasjon er plugin, ikke core | Mimir Agent er uavhengig av Hermes-floaten |
| Tauri 2 som desktop-skall | Native, ingen Electron-overhead |
| CSS-klasser heter `mir-*` | Konsistent navnerom |

---

## Fase 1 — Core Backend ✅ FERDIG

**Mål:** Komplett Python-backend portert fra privat jarvis-repo, renset for private referanser.

**Ferdig:**
- [x] `core/config/loader.py` — cross-platform config (`~/.config/mimir-agent/` + `%APPDATA%\MimirAgent\`)
- [x] `core/ai/brain.py` — LLM-klient, tool-use, context-komprimering, permission gate
- [x] `core/ai/honcho.py` — Honcho minneklient (workspace/peer fra config, ikke hardkodet)
- [x] `core/ai/tools.py` — system_health, web_search, datetime, read_file, write_file, shell, browser, screenshot, telegram_notify
- [x] `core/sessions.py` — session-logging til platform-korrekt mappe
- [x] `core/main.py` — FastAPI + WebSocket + alle REST-endepunkter
- [x] `core/voice/tts.py` — Edge Neural primær + Piper fallback + espeak-ng nødfallback
- [x] `core/voice/wake.py` — OpenWakeWord
- [x] `core/vision/watcher.py` — OpenCV + MediaPipe ansikt/gest-deteksjon
- [x] `core/plugins/hermes/bridge.py` — Hermes som valgfri plugin
- [x] `core/requirements.txt`
- [x] `config/default.yaml`
- [x] Permission-system: `PermissionLevel` (always/ask/never) per verktøy
- [x] Slash-kommandoer backend: `/clear /goal /steer /btw /compact /memory /tools /voice /mic /vision /sleep /help`
- [x] `GET /commands` — frontend henter kommandoliste dynamisk

**Nøkkel-filer:**
```
core/
├── main.py              (FastAPI, WebSocket, REST, slash-kommando-handler)
├── sessions.py          (JSON-logging)
├── config/loader.py     (Pydantic config + PermissionLevel)
├── ai/brain.py          (LLM, permission gate, context-injeksjon)
├── ai/tools.py          (alle verktøy)
├── ai/honcho.py         (valgfri minneklient)
├── voice/tts.py         (Edge + Piper)
├── voice/wake.py        (OpenWakeWord)
├── vision/watcher.py    (webcam + MediaPipe)
└── plugins/hermes/bridge.py
```

---

## Fase 2 — React UI ⬜ NESTE

**Mål:** Port av HUD-grensesnittet fra privat jarvis-repo til `ui/`, renset og tilpasset Mimir Agent.

**Oppgaver:**
- [ ] `ui/` — sett opp Vite + React + TypeScript (kopier fra jarvis-ui)
- [ ] `ui/src/ws/client.ts` — WebSocket-klient (allerede i jarvis, rens og kopier)
- [ ] `ui/src/api.ts` — `apiUrl()` helper (Tauri vs nettleser)
- [ ] `ui/src/AppHUD.tsx` — Hoved-HUD (norrønt UI, portert og renset)
- [ ] `ui/src/AppHUD.css` — All HUD-styling (`mir-*` klasser)
- [ ] **Slash command autocomplete** — `/`-meny over inputfeltet (Tab/Enter/↑↓)
- [ ] **Permission dialog** — overlay med NEI / TILLAT ÉN GANG / ALLTID TILLAT
- [ ] **Command result toast** — 4-sekunders toast etter slash-kommando
- [ ] `ui/src/hooks/useSpeechRecognition.ts` — STT-hook (PTT + open mic)
- [ ] `ui/src/components/Settings/` — Innstillinger (AI / STEMME / VERKTØY / SYSTEM)
- [ ] `ui/package.json` + `ui/vite.config.ts`

**WebSocket-events frontend må håndtere:**
```
connected, state_change, wake, sleep, chat_input, chat_response,
tool_call, permission_request, command_result, voice_toggle,
vision_toggle, mic_toggle_request, face_detected, face_lost, gesture
```

**WebSocket-actions frontend sender:**
```
wake, sleep, chat, chat_with_image, speak, new_session, ping,
permission_response, command, clear_history, get_config, get_state
```

---

## Fase 3 — Setup Wizard ⬜

**Mål:** Første-gangs oppsett som samler all nødvendig info og skriver config.

**Oppgaver:**
- [ ] `ui/src/AppSetup.tsx` — Wizard-komponent (rutes til fra `#/setup`)
- [ ] Backend-sjekk: `GET /setup/status` → redirect til `#/setup` hvis ikke ferdig
- [ ] `POST /setup/complete` — marker setup ferdig
- [ ] Wizard-steg (i rekkefølge):
  1. Velkomst + navn (sett `mir.user_name`)
  2. LLM-leverandør + API-nøkkel (test live før lagring via `/providers`)
  3. TTS-stemme (forhåndsavspilling)
  4. Vekkeord
  5. Valgfritt: Honcho-host
  6. Valgfritt: egendefinert SOUL.md-sti
  7. Last ned Whisper-modell (valgfritt, viser fremgang)
- [ ] Skriv config til `~/.config/mimir-agent/config.yaml`
- [ ] Sett `setup_complete: true`

---

## Fase 4 — Desktop App (Linux .deb) ⬜

**Mål:** Én installasjonspakke for Linux. Dobbeltklikk, setup, klar.

**Oppgaver:**
- [ ] `desktop/src-tauri/` — Tauri 2-skall (kopier fra jarvis tauri-app, tilpass)
- [ ] `desktop/src-tauri/src/lib.rs` — Sidecar: starter `mir-core` binær, poller TCP 8900
- [ ] `desktop/src-tauri/tauri.conf.json` — app-navn Mimir, ikoner, URL
- [ ] `desktop/Dockerfile.build` — Ubuntu 24.04 build-container
- [ ] `desktop/build-inner.sh` — `npm build` + `cargo tauri build`
- [ ] `.github/workflows/build-linux.yml` — CI/CD → artifact `.deb`
- [ ] Test: installer `.deb`, verifiser autostart og systemtray

**Viktig:** Bygg i Docker-container (unngår Zorin pakke-konflikter med webkit2gtk).

---

## Fase 5 — Windows Distribusjon ⬜

**Mål:** Native Windows-pakke. Ingen Python-installasjon, ingen WSL2.

**Distribusjonsmodell:**
```
Mimir_setup.exe
  └── Tauri-skall (native Windows app)
  └── mir-core.exe  (PyInstaller-bundle)
  └── cert/         (auto-generert ved første kjøring)
```

**Oppgaver:**
- [ ] `core/mimir-core.spec` — PyInstaller spec-fil for Windows
- [ ] Tilpass `core/ai/tools.py` for Windows:
  - Screenshot: bytt `scrot` → `PIL.ImageGrab` (Windows-nativt)
  - TTS `espeak-ng` fallback: Windows-path eller utelat
- [ ] `desktop/src-tauri/` — Windows build-konfig (`.msi` + `.exe`)
- [ ] `.github/workflows/build-windows.yml` — `windows-latest` runner
  - `pyinstaller mimir-core.spec` → `mir-core.exe`
  - `cargo tauri build` → `Mimir_x.x.x_x64-setup.exe` + `.msi`
- [ ] Test: installer på ren Windows 11, gå gjennom setup-wizard
- [ ] Kodesignering (valgfritt men anbefalt for å unngå SmartScreen-advarsel)

**Windows-spesifikke hensyn:**
- Lydavspilling: `ffmpeg` / `mpg123` vs Windows Media Foundation
- Piper binær: finnes for Windows på GitHub Releases
- Config-sti: `%APPDATA%\MimirAgent\config.yaml` (allerede håndtert i `loader.py`)

---

## Fase 6 — Work Mode (Kode-modus) ⬜

**Mål:** Mimir kan bytte til en fokusert kode-/arbeids-modus med kraftigere modell og terminal-grensesnitt.

**Konsept:**
- Default-modus: stemmeassistent (prat naturlig med Mimir)
- Trigger: "la oss kode", "åpne CLI", "bygg en app" → Mimir detekterer intent
- Work Mode aktiveres: mikrofon mutes, TTS mutes, fokus til kode-panel
- Modell kan byttes til kraftigere (f.eks. Opus) for kode-sesjon
- Tilbake til stemme-modus: si "ferdig" eller klikk tilbake

**Oppgaver:**

### 6A — `/model`-kommando
- [ ] `/model` slash-kommando: `mir.send("command", { command: "model", args: "anthropic/claude-opus-4-7" })`
- [ ] Backend: bytter `cfg.ai.primary.model`, kaller `brain.reload_clients()`
- [ ] Broadcast `model_changed` event til frontend
- [ ] Frontend viser aktiv modell i HUD-statuslinje

### 6B — Intent-deteksjon + mode-trigger
- [ ] Frontend: keyword-matching på chat-input ("kod", "CLI", "bygg", "app", "terminal", "script")
- [ ] Alternativt: brain returnerer `{"action": "switch_mode", "mode": "work"}` i svar
- [ ] Broadcast `mode_change` event: `{"mode": "work" | "voice"}`
- [ ] Auto-mute mic og TTS ved work mode aktivering
- [ ] Broadcast `mic_mute` + `voice_mute` events

### 6C — Work Mode-panel i HUD
- [ ] Ny route `#/work` eller overlay-panel i eksisterende HUD
- [ ] Større textarea for chat (kode-fokus)
- [ ] Syntax-highlighting (Prism.js eller highlight.js)
- [ ] Modell-velger øverst (dropdown med tilgjengelige modeller)
- [ ] "TILBAKE TIL STEMME"-knapp
- [ ] Muted mic-indikator tydelig synlig

### 6D — Embedded Terminal (xterm.js)
- [ ] `npm install xterm xterm-addon-fit xterm-addon-web-links`
- [ ] `ui/src/components/Terminal/Terminal.tsx` — xterm.js wrapper
- [ ] Backend: WebSocket-action `terminal_input` → kjør via `run_command` tool
- [ ] Output streames tilbake over WebSocket: `terminal_output` event
- [ ] Tauri: shell-plugin for direkte prosessadgang (bedre enn HTTP-runding)
- [ ] Sandkasse: samme allowlist som `run_command` i tools.py

---

## Fase 7 — Honcho & Persistent Minne ⬜

**Mål:** Valgfri persistent bruker-kontekst på tvers av sesjoner.

**Oppgaver:**
- [ ] Forbedre `core/ai/honcho.py` — bedre feilhåndtering, retry-logikk
- [ ] `setup/wizard.py` — Honcho Docker-oppsett som del av setup-wizard
- [ ] `docs/honcho.md` — brukerveiledning for Honcho-oppsett
- [ ] Honcho Dashboard-referanse (optional: `docs/honcho-dashboard.md`)
- [ ] Test: full sesjon med Honcho aktivert, verifiser at kontekst overlever restart
- [ ] MEMORY.md og USER.md-integrasjon (Mimir foreslår, bruker bekrefter)

---

## Fase 8 — Plugin-system ⬜

**Mål:** Brukere og utviklere kan legge til egne verktøy og integrasjoner.

**Konsept:**
```
~/.config/mimir-agent/plugins/
  my-tool/
    __init__.py      (tool-definisjon + executor)
    plugin.yaml      (navn, versjon, beskrivelse, tillatelser)
```

**Oppgaver:**
- [ ] Plugin-loader i `core/main.py` — scanner `plugins/`-mappe ved oppstart
- [ ] Plugin-API: `register_tool(definition, executor)` 
- [ ] Tillatelsessystem: plugins må deklarere hvilke tillatelser de trenger
- [ ] `GET /plugins` — liste installerte plugins
- [ ] Eksempel-plugin: `weather` (OpenWeatherMap)
- [ ] Eksempel-plugin: `calendar` (lokalt ical)
- [ ] `docs/plugin-dev.md` — utviklerveiledning

---

## Fase 9 — Dream Dashboard (Isometrisk by-kart) ⬜

**Mål:** Et visuelt dashboard der hele Mimir-verdenen er en norrøn by sett ovenfra — hver modul er en bygning, status vises live på kartet.

**Inspirasjon:** Bryan Valdes / #openclaw — isometrisk agent-by med Hermes HQ, Forge Labs, Hunter Station.

**Konsept:**
```
Nattlig norrøn festning, fugleperspektiv:
  Mimir HQ        → stortårn / mead hall (sentrum)
  Voice/Wake      → vakttårn med fakkel
  Vision          → utkikkspost
  Memory/Honcho   → runestein-arkiv / bibliotek
  Work Mode       → smedja med glødende ild
  Hermes Plugin   → smiehus (Forge)
```

**Hver bygning:**
- Viser live status-badge (● Online / ○ Idle / ⚡ Working)
- Er klikkbar → åpner detalj-panel for den modulen
- Lyser opp / animeres når aktiv

**Teknisk tilnærming:**
- [ ] Generer isometrisk norrøn by-art med Midjourney/Stable Diffusion
- [ ] React-komponent: statisk PNG bakgrunn + absolutt-posisjonerte overlays
- [ ] Klikk-soner per bygning (posisjonerte `<div>`er)
- [ ] WebSocket-events oppdaterer status-badges live
- [ ] Klikk → modal/side-panel per modul
- [ ] Ny route `#/city` eller `#/world`

**Forutsetning:** Fase 2 (React UI) ferdig.
**Estimat:** ~1 uke for MVP etter at kunsten er klar.

---

## Backlog / Fremtidige ideer

- **SOUL.md-galleri** — community-bidragte identiteter (pirat, akademiker, militær, etc.)
- **Mobilapp** — React Native wrapper mot lokal Mimir-server
- **Multi-agent** — Mimir som orkestrator for lokale spesial-agenter
- **Vektorminne** — lokal RAG med Chroma eller Qdrant (over Honcho)
- **Stemmegjenkjenning av bruker** — forskjellig oppførsel basert på hvem som snakker
- **Kalender-integrasjon** — lese/skrive lokale ical-filer
- **Notifikasjoner** — OS-native notifikasjoner ved viktige hendelser

---

## Versjonsoversikt

| Versjon | Innhold |
|---------|---------|
| 0.1.0 | Core backend + permission-system + slash-kommandoer |
| 0.2.0 | React UI (HUD + Setup Wizard) |
| 0.3.0 | Linux .deb Tauri-app |
| 0.4.0 | Windows .exe/.msi |
| 0.5.0 | Work Mode + /model + xterm.js |
| 0.6.0 | Honcho minnelag |
| 1.0.0 | Plugin-system + stabil API |
