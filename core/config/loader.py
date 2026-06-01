import os
import platform
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel


class PermissionLevel(str, Enum):
    always = "always"   # auto-approve, no dialog
    ask    = "ask"      # ask user on first use, remember answer
    never  = "never"    # always block


class ToolPermissions(BaseModel):
    """Per-tool permission levels. 'always' = safe/read-only by default."""
    get_system_health: PermissionLevel = PermissionLevel.always
    web_search:        PermissionLevel = PermissionLevel.always
    get_datetime:      PermissionLevel = PermissionLevel.always
    read_file:         PermissionLevel = PermissionLevel.ask
    write_file:        PermissionLevel = PermissionLevel.ask
    run_command:       PermissionLevel = PermissionLevel.ask
    browse_web:        PermissionLevel = PermissionLevel.ask
    take_screenshot:   PermissionLevel = PermissionLevel.ask
    notify_telegram:   PermissionLevel = PermissionLevel.ask


class STTConfig(BaseModel):
    engine: str = "faster-whisper"
    model: str = "tiny"
    language: str = "en"
    device: str = "cpu"


class TTSConfig(BaseModel):
    engine: str = "edge"
    voice: str = "en-US-AriaNeural"
    speed: float = 1.0
    pitch: float = 1.0


class WakeConfig(BaseModel):
    engine: str = "openwakeword"
    sensitivity: float = 0.7
    custom_model: Optional[str] = None


class InputConfig(BaseModel):
    mode: str = "open_mic"
    ptt_key: str = "Space"


class VoiceConfig(BaseModel):
    stt: STTConfig = STTConfig()
    tts: TTSConfig = TTSConfig()
    wake: WakeConfig = WakeConfig()
    input: InputConfig = InputConfig()


class AIProviderConfig(BaseModel):
    provider: str = "openrouter"
    base_url: str = "https://openrouter.ai/api/v1"
    host: str = ""
    model: str = "openrouter/auto"
    api_key: str = ""
    context_length: int = 8192
    temperature: float = 0.7


class AIFallbackConfig(BaseModel):
    enabled: bool = False
    provider: str = "ollama"
    host: str = "localhost:11434"
    model: str = "llama3"
    trigger: str = "timeout_or_error"


class AIConfig(BaseModel):
    primary: AIProviderConfig = AIProviderConfig()
    fallback: AIFallbackConfig = AIFallbackConfig()


class HonchoConfig(BaseModel):
    enabled: bool = False
    host: str = "localhost:8000"
    workspace: str = "mimir"
    peer_id: str = "user"


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8900
    auth_token: Optional[str] = None


class UIConfig(BaseModel):
    theme: str = "mimir-dark"
    hud_opacity: float = 0.95
    startup_mode: str = "fullscreen"
    show_on_wake: bool = True
    screen_wake_command: str = ""


class MirConfig(BaseModel):
    name: str = "Mimir"
    user_name: str = "User"
    wake_word: str = "hey mimir"
    language: str = "en"
    session_memory: bool = True
    greeting_enabled: bool = True
    personality_prompt: str = "You are Mimir, a calm and direct Norse wisdom keeper."


class VisionConfig(BaseModel):
    enabled: bool = False
    device: int = 0
    auto_wake: bool = True


class ToolsConfig(BaseModel):
    permissions: ToolPermissions = ToolPermissions()
    file_read_paths: list[str] = ["~/Documents/"]
    file_write_paths: list[str] = ["~/Documents/", "/tmp/"]
    telegram_chat_id: str = ""
    telegram_bot_token: str = ""


class Config(BaseModel):
    mir: MirConfig = MirConfig()
    voice: VoiceConfig = VoiceConfig()
    ai: AIConfig = AIConfig()
    honcho: HonchoConfig = HonchoConfig()
    server: ServerConfig = ServerConfig()
    ui: UIConfig = UIConfig()
    tools: ToolsConfig = ToolsConfig()
    vision: VisionConfig = VisionConfig()
    setup_complete: bool = False


def _config_dir() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "MimirAgent"
    return Path.home() / ".config" / "mimir-agent"


def _config_path() -> Path:
    return _config_dir() / "config.yaml"


_CONFIG_PATHS = [
    _config_path(),
    Path(__file__).parent.parent.parent / "config" / "config.yaml",
]


def load_config() -> Config:
    for path in _CONFIG_PATHS:
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            return Config(**data)
    return Config()


def save_config(cfg: Config, path: Optional[Path] = None) -> None:
    if path is None:
        path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(cfg.model_dump(), f, allow_unicode=True, default_flow_style=False)
