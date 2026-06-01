"""
Vision Watcher — background thread reading webcam, emitting events on face/gesture detection.
"""
import asyncio
import base64
import logging
import threading
import time
from typing import Callable, Optional

log = logging.getLogger("mimir.vision")

_FACE_ENTER_THRESHOLD = 8
_FACE_LEAVE_THRESHOLD = 15
_GESTURE_COOLDOWN = 3.0


class VisionWatcher:
    def __init__(self, on_event: Callable[[str, dict], None], device: int = 0):
        self._on_event = on_event
        self._device = device
        self._thread: Optional[threading.Thread] = None
        self._running = False

        self.face_present = False
        self.last_gesture: Optional[str] = None
        self._last_gesture_time: float = 0.0

    def start(self) -> bool:
        if self._running:
            return True
        try:
            import cv2
        except ImportError:
            log.error("opencv-python not installed — vision unavailable")
            return False
        cap = cv2.VideoCapture(self._device)
        ok = cap.isOpened()
        cap.release()
        if not ok:
            log.error("Cannot open camera device %d", self._device)
            return False
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="vision-watcher")
        self._thread.start()
        log.info("Vision watcher started (device=%d)", self._device)
        return True

    def stop(self):
        self._running = False
        log.info("Vision watcher stopped")

    def snap(self) -> Optional[str]:
        try:
            import cv2
        except ImportError:
            return None
        cap = cv2.VideoCapture(self._device)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return None
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return base64.b64encode(buf.tobytes()).decode()

    @property
    def running(self) -> bool:
        return self._running

    def _run(self):
        try:
            import cv2
            import mediapipe as mp
        except ImportError:
            log.error("opencv-python or mediapipe not installed — vision unavailable")
            self._running = False
            return

        mp_face  = mp.solutions.face_detection
        mp_hands = mp.solutions.hands

        face_det  = mp_face.FaceDetection(model_selection=0, min_detection_confidence=0.6)
        hands_det = mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.5,
        )

        cap = cv2.VideoCapture(self._device)
        face_streak    = 0
        no_face_streak = 0
        fail_count     = 0

        while self._running:
            ret, frame = cap.read()
            if not ret:
                fail_count += 1
                time.sleep(0.1)
                if fail_count >= 30:
                    log.warning("Webcam lost signal — reconnecting")
                    cap.release()
                    time.sleep(2)
                    cap = cv2.VideoCapture(self._device)
                    fail_count = 0
                continue
            fail_count = 0

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            face_res = face_det.process(rgb)
            face_now = bool(face_res.detections)

            if face_now:
                face_streak    += 1
                no_face_streak  = 0
                if face_streak == _FACE_ENTER_THRESHOLD and not self.face_present:
                    self.face_present = True
                    score = round(face_res.detections[0].score[0], 2)
                    log.info("Face detected (score=%.2f)", score)
                    self._on_event("face_detected", {"confidence": score})
            else:
                no_face_streak += 1
                face_streak     = 0
                if no_face_streak == _FACE_LEAVE_THRESHOLD and self.face_present:
                    self.face_present = False
                    log.info("Face lost")
                    self._on_event("face_lost", {})

            hand_res = hands_det.process(rgb)
            if hand_res.multi_hand_landmarks:
                gesture = self._classify(hand_res.multi_hand_landmarks[0])
                now = time.time()
                if gesture and (gesture != self.last_gesture or
                                now - self._last_gesture_time > _GESTURE_COOLDOWN):
                    self.last_gesture       = gesture
                    self._last_gesture_time = now
                    log.info("Gesture: %s", gesture)
                    self._on_event("gesture", {"gesture": gesture})
            else:
                self.last_gesture = None

        cap.release()

    def _classify(self, landmarks) -> Optional[str]:
        lm = landmarks.landmark

        def y(i): return lm[i].y

        thumb_tip   = y(4)
        index_tip   = y(8);  index_pip  = y(6)
        middle_tip  = y(12); middle_pip = y(10)
        ring_tip    = y(16); ring_pip   = y(14)
        pinky_tip   = y(20); pinky_pip  = y(18)

        fingers_curled = (
            index_tip  > index_pip  and
            middle_tip > middle_pip and
            ring_tip   > ring_pip   and
            pinky_tip  > pinky_pip
        )

        if thumb_tip < index_pip and fingers_curled:
            return "thumbs_up"

        fingers_open = (
            index_tip  < index_pip  and
            middle_tip < middle_pip and
            ring_tip   < ring_pip   and
            pinky_tip  < pinky_pip
        )
        if fingers_open:
            return "wave"

        return None
