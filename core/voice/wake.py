"""
Wake word detection — OpenWakeWord
Listens continuously, triggers callback on detected wake word.
"""
import asyncio
import logging
import threading
import time
from typing import Callable, Optional

log = logging.getLogger("mimir.wake")

try:
    import numpy as np
    import sounddevice as sd
    import openwakeword
    from openwakeword.model import Model as OWWModel
    _OWW_AVAILABLE = True
except (ImportError, OSError):
    _OWW_AVAILABLE = False
    log.warning("OpenWakeWord not installed — use HTTP /wake as trigger")


class WakeDetector:
    def __init__(self, wake_word: str = "hey mimir", sensitivity: float = 0.7):
        self.wake_word = wake_word.lower()
        self.sensitivity = sensitivity
        self._callback: Optional[Callable] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._model: Optional[object] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def on_wake(self, callback: Callable) -> None:
        self._callback = callback

    def _trigger(self) -> None:
        log.info(f"Wake word detected: '{self.wake_word}'")
        if self._callback and self._loop:
            asyncio.run_coroutine_threadsafe(self._callback(), self._loop)

    def start(self) -> None:
        if not _OWW_AVAILABLE:
            log.info("Wake detection inactive (OpenWakeWord not installed)")
            return

        try:
            self._loop = asyncio.get_event_loop()
        except RuntimeError:
            self._loop = None

        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        log.info(f"Wake detector started (sensitivity: {self.sensitivity})")

    def stop(self) -> None:
        self._running = False

    def _listen_loop(self) -> None:
        try:
            self._model = OWWModel(
                wakeword_models=["hey_jarvis"],
                inference_framework="onnx"
            )

            chunk_size = 1280
            with sd.InputStream(
                samplerate=16000,
                channels=1,
                dtype="int16",
                blocksize=chunk_size,
            ) as stream:
                while self._running:
                    audio_chunk, _ = stream.read(chunk_size)
                    audio_flat = audio_chunk.flatten()
                    predictions = self._model.predict(audio_flat)
                    for model_name, score in predictions.items():
                        if score >= self.sensitivity:
                            log.info(f"Wake word! ({model_name}: {score:.2f})")
                            self._trigger()
                            time.sleep(2)
                            self._model.reset()
                            break
        except Exception as e:
            log.error(f"Wake loop failed: {e}", exc_info=True)
