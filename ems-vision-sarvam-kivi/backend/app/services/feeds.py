"""Live feeds. Any number run at once, and each is one of:

browser_camera  The operator's browser sends webcam frames over /ws/ingest/{id}.
edge_camera     edge-sensing/agent.py sends GigE, RTSP or USB frames over the same socket.
ip_camera       The server pulls a reachable MJPEG, snapshot or RTSP URL.
sensor          The browser or agent sends JSON readings. Limits are checked here in code.
plc_trigger     The agent forwards PLC triggers, which inspect the linked camera.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal
from urllib.parse import urlparse

import cv2
import httpx
import numpy as np

from ..config.settings import settings

FeedKind = Literal["browser_camera", "edge_camera", "ip_camera", "sensor", "plc_trigger"]
FeedRole = Literal["aoi_top", "aoi_bottom", "xray", "thermal", "overview", "sensor", "trigger"]
MAX_FRAME_BYTES = 8 * 1024 * 1024
STALE_AFTER_S = 5.0

# (min, max) per reading. None means no bound. Placeholder limits carried over from
# inspector.py: replace with the real spec for each board type.
SENSOR_LIMITS: dict[str, tuple[float | None, float | None]] = {
    "rail_5v_v": (4.75, 5.25),
    "board_temp_c": (None, 65.0),
    "j3_contact_mohm": (None, 50.0),
}


def check_readings(values: dict[str, float]) -> list[dict]:
    out = []
    for name, value in values.items():
        if name in SENSOR_LIMITS:
            lo, hi = SENSOR_LIMITS[name]
            if (lo is not None and value < lo) or (hi is not None and value > hi):
                out.append({"reading": name, "value": value, "min": lo, "max": hi})
    return out


def validate_feed_url(url: str) -> None:
    """Reject schemes and addresses a public server should not be pointed at."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https", "rtsp") or not parsed.hostname:
        raise ValueError("feed URL must be http, https or rtsp")
    if settings.allow_private_feed_urls:
        return
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, parsed.port or 80)}
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve {parsed.hostname}") from exc
    for address in addresses:
        if not ipaddress.ip_address(address).is_global:
            raise ValueError("feed URL points to a private address. Use the edge agent for cameras on a private network")


@dataclass
class FeedState:
    frame: bytes | None = None
    frame_at: float = 0.0
    frames: int = 0
    readings: dict[str, float] = field(default_factory=dict)
    reading_at: float = 0.0
    alerts: list[dict] = field(default_factory=list)
    golden: np.ndarray | None = None
    error: str | None = None
    event: asyncio.Event = field(default_factory=asyncio.Event)

    def status(self) -> dict:
        last = max(self.frame_at, self.reading_at)
        return {"live": bool(last) and time.time() - last < STALE_AFTER_S, "last_seen": last or None, "frames": self.frames,
                "readings": self.readings, "alerts": self.alerts, "has_golden": self.golden is not None, "error": self.error}


class FeedHub:
    def __init__(self) -> None:
        self.states: dict[str, FeedState] = {}
        self.pulls: dict[str, asyncio.Task] = {}

    def state(self, feed_id: str) -> FeedState:
        return self.states.setdefault(feed_id, FeedState())

    def push_frame(self, feed_id: str, jpeg: bytes) -> None:
        if len(jpeg) > MAX_FRAME_BYTES:
            raise ValueError("frame too large")
        if jpeg[:2] != b"\xff\xd8":
            raise ValueError("frames must be JPEG")
        state = self.state(feed_id)
        state.frame, state.frame_at, state.error = jpeg, time.time(), None
        state.frames += 1
        state.event.set()
        state.event = asyncio.Event()

    def push_readings(self, feed_id: str, values: dict[str, float]) -> list[dict]:
        state = self.state(feed_id)
        state.readings, state.reading_at = values, time.time()
        state.alerts = check_readings(values)
        return state.alerts

    def latest_image(self, feed_id: str) -> np.ndarray | None:
        state = self.state(feed_id)
        if state.frame is None:
            return None
        return cv2.imdecode(np.frombuffer(state.frame, np.uint8), cv2.IMREAD_COLOR)

    async def stream(self, feed_id: str):
        """Yield multipart MJPEG, which a plain <img> tag can display."""
        state = self.state(feed_id)
        while True:
            if state.frame:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + state.frame + b"\r\n"
            try:
                await asyncio.wait_for(state.event.wait(), timeout=10)
            except asyncio.TimeoutError:
                continue

    def start_pull(self, feed_id: str, url: str) -> None:
        self.stop_pull(feed_id)
        self.pulls[feed_id] = asyncio.create_task(self._pull(feed_id, url))

    def stop_pull(self, feed_id: str) -> None:
        task = self.pulls.pop(feed_id, None)
        if task:
            task.cancel()

    async def _pull(self, feed_id: str, url: str) -> None:
        pull = _pull_rtsp if url.startswith("rtsp") else _pull_http
        delay = 1.0
        while True:
            try:
                await pull(url, lambda jpeg: self.push_frame(feed_id, jpeg))
                delay = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.state(feed_id).error = f"{type(exc).__name__}: {str(exc)[:160]}"
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)


async def _pull_http(url: str, emit: Callable[[bytes], None]) -> None:
    """Handle both multipart MJPEG streams and single-image snapshot URLs."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(15, read=30), follow_redirects=False) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            kind = response.headers.get("content-type", "")
            if not kind.startswith("multipart"):
                emit(await response.aread())
                await asyncio.sleep(0.5)
                return
            buffer = b""
            async for chunk in response.aiter_bytes():
                buffer += chunk
                while True:
                    start = buffer.find(b"\xff\xd8")
                    end = buffer.find(b"\xff\xd9", start + 2)
                    if start < 0 or end < 0:
                        buffer = buffer[-MAX_FRAME_BYTES:]
                        break
                    emit(buffer[start:end + 2])
                    buffer = buffer[end + 2:]


async def _pull_rtsp(url: str, emit: Callable[[bytes], None]) -> None:
    capture = await asyncio.to_thread(cv2.VideoCapture, url)
    try:
        if not capture.isOpened():
            raise ConnectionError("could not open RTSP stream")
        while True:
            ok, frame = await asyncio.to_thread(capture.read)
            if not ok:
                raise ConnectionError("RTSP stream ended")
            ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                emit(jpeg.tobytes())
            await asyncio.sleep(0.05)
    finally:
        capture.release()


hub = FeedHub()
Broadcast = Callable[[dict], Awaitable[None]]
