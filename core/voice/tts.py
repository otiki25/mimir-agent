"""
Text-to-Speech — Edge Neural TTS (primary) + Piper (offline fallback)
"""
import asyncio
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

log = logging.getLogger("mimir.tts")

try:
    import sounddevice as sd
    import soundfile as sf
    _AUDIO_AVAILABLE = True
except (ImportError, OSError):
    _AUDIO_AVAILABLE = False
    log.warning("sounddevice/soundfile/PortAudio not available — TTS will be silent")

try:
    import edge_tts
    _EDGE_AVAILABLE = True
except ImportError:
    _EDGE_AVAILABLE = False

_PIPER_BIN = Path.home() / ".local" / "bin" / "piper"
_PIPER_MODELS_DIR = Path.home() / ".local" / "share" / "piper-voices"
_PIPER_LIB_DIR = Path.home() / ".local" / "lib" / "piper"
_PIPER_ESPEAK_DATA = Path.home() / ".local" / "share" / "piper-espeak-data"

EDGE_VOICES = {
    "en-US-AriaNeural",
    "en-US-GuyNeural",
    "en-GB-SoniaNeural",
    "en-GB-RyanNeural",
    "nb-NO-FinnNeural",
    "nb-NO-PernilleNeural",
}


def _play_wav(path: str) -> None:
    data, sr = sf.read(path)
    sd.play(data, sr)
    sd.wait()


def _clean(text: str) -> str:
    """Strip markdown and symbols that sound odd in TTS."""
    import re
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,2}(.*?)_{1,2}', r'\1', text)
    text = re.sub(r'`{1,3}[^`]*`{1,3}', '', text)
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'—', ',', text)
    text = re.sub(r'[/\\|<>]', ' ', text)
    text = re.sub(r'&', ' and ', text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()


class TTSEngine:
    def __init__(self, engine: str = "edge", voice: str = "en-US-AriaNeural", speed: float = 1.0):
        self.engine = engine
        self.voice = voice
        self.speed = speed
        self._piper_voice_path: Optional[Path] = None

    def setup(self) -> None:
        if self.engine == "piper" or not _EDGE_AVAILABLE:
            self._setup_piper()
        else:
            log.info(f"Edge TTS ready: {self.voice}")
            self._setup_piper(silent=True)

    def _setup_piper(self, silent: bool = False) -> None:
        voice_file = _PIPER_MODELS_DIR / f"{self.voice}.onnx"
        if voice_file.exists():
            self._piper_voice_path = voice_file
            if not silent:
                log.info(f"Piper voice: {self.voice}")
        else:
            if _PIPER_MODELS_DIR.exists():
                voices = list(_PIPER_MODELS_DIR.glob("*.onnx"))
                if voices:
                    self._piper_voice_path = voices[0]
                    if not silent:
                        log.info(f"Piper fallback voice: {voices[0].name}")

    async def speak(self, text: str) -> None:
        text = _clean(text)
        log.info(f"Mimir speaks [{self.engine}]: {text[:80]}{'...' if len(text) > 80 else ''}")

        if self.engine == "edge" and _EDGE_AVAILABLE:
            success = await self._speak_edge(text)
            if success:
                return
            log.warning("Edge TTS failed — falling back to Piper")

        await self._speak_piper(text)

    async def _speak_edge(self, text: str) -> bool:
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                tmp_path = Path(f.name)

            rate_pct = int((self.speed - 1.0) * 100)
            rate_str = f"+{rate_pct}%" if rate_pct >= 0 else f"{rate_pct}%"

            communicate = edge_tts.Communicate(text, self.voice, rate=rate_str)
            await communicate.save(str(tmp_path))

            if _AUDIO_AVAILABLE and tmp_path.exists() and tmp_path.stat().st_size > 0:
                await asyncio.to_thread(_play_mp3, str(tmp_path))

            tmp_path.unlink(missing_ok=True)
            return True

        except Exception as e:
            log.error(f"Edge TTS failed: {e}")
            if 'tmp_path' in locals():
                Path(tmp_path).unlink(missing_ok=True)
            return False

    async def _speak_piper(self, text: str) -> None:
        if not _PIPER_BIN.exists() or not self._piper_voice_path:
            await self._espeak_fallback(text)
            return

        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_path = Path(f.name)

            env = {
                "LD_LIBRARY_PATH": str(_PIPER_LIB_DIR),
                "ESPEAK_DATA_PATH": str(_PIPER_ESPEAK_DATA),
            }
            env.update({k: v for k, v in os.environ.items() if k not in env})

            proc = await asyncio.create_subprocess_exec(
                str(_PIPER_BIN),
                "--model", str(self._piper_voice_path),
                "--output_file", str(tmp_path),
                "--length_scale", str(1.0 / self.speed),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                env=env,
            )
            await proc.communicate(input=text.encode("utf-8"))

            if _AUDIO_AVAILABLE and tmp_path.exists():
                await asyncio.to_thread(_play_wav, str(tmp_path))

            tmp_path.unlink(missing_ok=True)

        except Exception as e:
            log.error(f"Piper TTS failed: {e}")
            await self._espeak_fallback(text)

    async def _espeak_fallback(self, text: str) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "espeak-ng", "-v", "en", "-s", "150", text,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except FileNotFoundError:
            log.warning("No TTS available (install edge-tts, piper, or espeak-ng)")


def _play_mp3(path: str) -> None:
    try:
        wav_path = path.replace(".mp3", "_conv.wav")
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", path, wav_path],
            capture_output=True, timeout=10
        )
        if result.returncode == 0:
            data, sr = sf.read(wav_path)
            sd.play(data, sr)
            sd.wait()
            Path(wav_path).unlink(missing_ok=True)
            return
    except Exception:
        pass

    for player in [["mpg123", "-q", path], ["aplay", path]]:
        try:
            subprocess.run(player, capture_output=True, timeout=30)
            return
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
