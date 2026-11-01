from __future__ import annotations

import asyncio
import base64
import hmac
import json
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Annotated

import cv2
import numpy as np
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from .config.languages import LANGUAGES, STT_MODES
from .config.settings import settings
from .db import Feed, Inspection, ReworkLog, SessionLocal, init_db
from .services import inspection as ins
from .services.feeds import FeedKind, FeedRole, hub, validate_feed_url
from .services.kivi_engine import DictionaryEntry, KiviSpace, Shortcut, Style, apply_dictionary, apply_style, expand_shortcuts
from .services.sarvam_service import SarvamError, sarvam

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
space = KiviSpace(settings.kivi_space)


class ShopfloorSockets:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def broadcast(self, event: dict) -> None:
        for ws in list(self.clients):
            try:
                await ws.send_json(event)
            except (WebSocketDisconnect, RuntimeError):
                self.clients.discard(ws)


sockets = ShopfloorSockets()


def _valid_token(token: str | None) -> bool:
    return not settings.app_access_token or hmac.compare_digest(token or "", settings.app_access_token)


def require_token(x_access_token: Annotated[str | None, Header()] = None, token: Annotated[str | None, Query()] = None) -> None:
    if not _valid_token(x_access_token or token):
        raise HTTPException(401, "invalid access token")


_hits: dict[str, deque[float]] = defaultdict(deque)


def rate_limit(request: Request) -> None:
    """Protect the Sarvam key on a public URL: 60 paid calls a minute per client address."""
    bucket = _hits[request.client.host if request.client else "unknown"]
    now = time.monotonic()
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= 60:
        raise HTTPException(429, "too many requests")
    bucket.append(now)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as db:
        for feed in db.scalars(select(Feed).where(Feed.kind == "ip_camera", Feed.enabled)):
            hub.start_pull(feed.id, feed.url or "")
    yield
    for feed_id in list(hub.pulls):
        hub.stop_pull(feed_id)


app = FastAPI(title="EMS Vision Sarvam Kivi", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                   allow_methods=["*"], allow_headers=["*"])
app.mount("/samples", StaticFiles(directory=settings.data_dir / "sample_pcbs"), name="samples")
secured = [Depends(require_token)]
metered = [Depends(require_token), Depends(rate_limit)]


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "demo_mode": settings.demo_mode, "yolo_active": ins.sample_inspector().yolo.active,
            "auth_required": bool(settings.app_access_token)}


@app.get("/api/languages")
def languages() -> list[dict]:
    return [{"name": l.name, "code": l.code, "native": l.native, "mayura": l.mayura,
             "tts_model": l.tts_model, "tts_bridge": l.tts_bridge} for l in LANGUAGES]


class InspectRequest(BaseModel):
    case_id: str


async def _finish(serial: str, source: str, result) -> dict:
    inspection_id = ins.save(serial, source, result)
    payload = {"id": inspection_id, "serial": serial, "source": source, **result.model_dump(mode="json")}
    await sockets.broadcast({"type": "inspection", "inspection": payload})

    async def enrich() -> None:
        updated = await ins.enrich(inspection_id, result)
        if updated:
            await sockets.broadcast({"type": "diagnosis_updated", "id": inspection_id,
                                     "diagnoses": [d.model_dump(mode="json") for d in updated]})

    asyncio.create_task(enrich())
    return payload


def _inspect_error(exc: Exception) -> HTTPException:
    return HTTPException(422, f"could not align this image to the reference board: {exc}")


@app.get("/api/cases", dependencies=secured)
def cases() -> list[dict]:
    return ins.list_cases()


@app.post("/api/inspect", dependencies=secured)
async def inspect_case(body: InspectRequest) -> dict:
    try:
        test, xray, serial = ins.load_case(body.case_id)
    except FileNotFoundError:
        raise HTTPException(404, "unknown case") from None
    recurrence = ins.recurrence_counts()
    result = await asyncio.to_thread(ins.sample_inspector().inspect, test, xray, None, recurrence)
    payload = await _finish(serial, body.case_id, result)
    return {**payload, "images": {"golden": "/samples/golden.jpg", "test": f"/samples/{body.case_id}/test.jpg",
                                  "xray": f"/samples/{body.case_id}/xray.png"}}


@app.get("/api/inspections", dependencies=secured)
def inspections(limit: int = Query(50, le=500)) -> list[dict]:
    with SessionLocal() as db:
        rows = db.scalars(select(Inspection).order_by(desc(Inspection.id)).limit(limit)).all()
        return [{"id": r.id, "serial": r.serial, "source": r.source, "verdict": r.verdict,
                 "created_at": r.created_at.isoformat(), "result": r.result} for r in rows]


class TranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    target: str
    source: str = "en-IN"
    code_mixed: bool = False


@app.post("/api/translate", dependencies=metered)
async def translate(body: TranslateRequest) -> dict:
    try:
        return await sarvam.translate(body.text, body.target, body.source, body.code_mixed)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except SarvamError as exc:
        raise HTTPException(502, str(exc)) from exc


class TtsRequest(BaseModel):
    text: str = Field(min_length=1)
    language: str


@app.post("/api/tts", dependencies=metered)
async def tts(body: TtsRequest) -> dict:
    try:
        result = await sarvam.speak(body.text, body.language)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return result.__dict__


@app.post("/api/kivi/transcribe", dependencies=metered)
async def kivi_transcribe(audio: Annotated[UploadFile, File()], language: Annotated[str | None, Form()] = None,
                          mode: Annotated[str, Form()] = "codemix", style_id: Annotated[str, Form()] = "rework-operator-log",
                          serial: Annotated[str | None, Form()] = None) -> dict:
    if mode not in STT_MODES:
        raise HTTPException(422, f"mode must be one of {STT_MODES}")
    data = await audio.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "audio too large")
    style = next((s for s in space.styles() if s.id == style_id), None)
    if style is None:
        raise HTTPException(404, "unknown style")
    try:
        stt = await sarvam.transcribe(data, audio.filename or "speech.webm", audio.content_type or "audio/webm",
                                      language, mode, space.keyterms())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except SarvamError as exc:
        raise HTTPException(502, str(exc)) from exc
    return await _kivi_text(stt["transcript"], stt.get("language_code"), style, serial, stt)


class KiviTextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    style_id: str = "rework-operator-log"
    serial: str | None = None
    language: str | None = None


@app.post("/api/kivi/process", dependencies=metered)
async def kivi_process(body: KiviTextRequest) -> dict:
    """The same pipeline without audio, for typed text and previews."""
    style = next((s for s in space.styles() if s.id == body.style_id), None)
    if style is None:
        raise HTTPException(404, "unknown style")
    return await _kivi_text(body.text, body.language, style, body.serial, {})


async def _kivi_text(raw: str, language: str | None, style: Style, serial: str | None, stt: dict) -> dict:
    entries = space.dictionary()
    replaced, changes = apply_dictionary(raw, entries)
    expanded, used = expand_shortcuts(replaced, space.shortcuts(), entries)
    styled, used_llm = await apply_style(expanded, style, sarvam, {"serial": serial})
    with SessionLocal() as db:
        row = ReworkLog(serial=serial, language_code=language, raw_transcript=raw, dictionary_text=replaced,
                        expanded_text=expanded, styled_text=styled, style_id=style.id)
        db.add(row)
        db.commit()
        log_id = row.id
    await sockets.broadcast({"type": "rework_log", "id": log_id, "serial": serial, "text": styled})
    return {"id": log_id, "raw_transcript": raw, "dictionary_text": replaced, "expanded_text": expanded, "styled_text": styled,
            "replacements": [c.__dict__ for c in changes], "shortcuts_used": used, "style_llm": used_llm,
            "keyterms_sent": len(stt.get("keyterms", [])), "language_code": language}


@app.get("/api/kivi/history", dependencies=secured)
def kivi_history(limit: int = Query(100, le=500)) -> list[dict]:
    with SessionLocal() as db:
        rows = db.scalars(select(ReworkLog).order_by(desc(ReworkLog.id)).limit(limit)).all()
        return [{"id": r.id, "serial": r.serial, "language_code": r.language_code, "raw_transcript": r.raw_transcript,
                 "styled_text": r.styled_text, "style_id": r.style_id, "created_at": r.created_at.isoformat()} for r in rows]


@app.get("/api/kivi/dictionary", dependencies=secured)
def get_dictionary() -> dict:
    return {"entries": [e.model_dump() for e in space.dictionary()], "keyterms": space.keyterms()}


@app.post("/api/kivi/dictionary", dependencies=secured)
def put_dictionary(entry: DictionaryEntry) -> dict:
    space.upsert("dictionary", entry)
    return entry.model_dump()


@app.delete("/api/kivi/dictionary/{item_id}", dependencies=secured)
def delete_dictionary(item_id: str) -> dict:
    if not space.delete("dictionary", item_id):
        raise HTTPException(404, "not found")
    return {"deleted": item_id}


@app.get("/api/kivi/shortcuts", dependencies=secured)
def get_shortcuts() -> list[dict]:
    return [s.model_dump() for s in space.shortcuts()]


@app.post("/api/kivi/shortcuts", dependencies=secured)
def put_shortcut(item: Shortcut) -> dict:
    space.upsert("shortcuts", item)
    return item.model_dump()


@app.delete("/api/kivi/shortcuts/{item_id}", dependencies=secured)
def delete_shortcut(item_id: str) -> dict:
    if not space.delete("shortcuts", item_id):
        raise HTTPException(404, "not found")
    return {"deleted": item_id}


@app.get("/api/kivi/styles", dependencies=secured)
def get_styles() -> list[dict]:
    return [s.model_dump() for s in space.styles()]


@app.post("/api/kivi/styles", dependencies=secured)
def put_style(item: Style) -> dict:
    space.upsert("styles", item)
    return item.model_dump()


class FeedCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    kind: FeedKind
    role: FeedRole = "aoi_top"
    url: str | None = None


def _feed_json(feed: Feed) -> dict:
    return {"id": feed.id, "name": feed.name, "kind": feed.kind, "role": feed.role, "url": feed.url,
            "enabled": feed.enabled, **hub.state(feed.id).status()}


@app.get("/api/feeds", dependencies=secured)
def list_feeds() -> list[dict]:
    with SessionLocal() as db:
        return [_feed_json(f) for f in db.scalars(select(Feed).order_by(Feed.created_at))]


@app.post("/api/feeds", dependencies=secured)
async def create_feed(body: FeedCreate) -> dict:
    if body.kind == "ip_camera":
        if not body.url:
            raise HTTPException(422, "ip_camera needs a url")
        try:
            await asyncio.to_thread(validate_feed_url, body.url)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    feed = Feed(id=uuid.uuid4().hex[:12], name=body.name, kind=body.kind, role=body.role, url=body.url)
    with SessionLocal() as db:
        db.add(feed)
        db.commit()
    if feed.kind == "ip_camera":
        hub.start_pull(feed.id, feed.url or "")
    return _feed_json(feed)


@app.delete("/api/feeds/{feed_id}", dependencies=secured)
def delete_feed(feed_id: str) -> dict:
    with SessionLocal() as db:
        feed = db.get(Feed, feed_id)
        if feed is None:
            raise HTTPException(404, "not found")
        db.delete(feed)
        db.commit()
    hub.stop_pull(feed_id)
    hub.states.pop(feed_id, None)
    return {"deleted": feed_id}


def _require_feed(feed_id: str) -> None:
    with SessionLocal() as db:
        if db.get(Feed, feed_id) is None:
            raise HTTPException(404, "unknown feed")


@app.get("/api/feeds/{feed_id}/latest.jpg", dependencies=secured)
def latest_frame(feed_id: str) -> Response:
    frame = hub.state(feed_id).frame
    if frame is None:
        raise HTTPException(404, "no frame yet")
    return Response(frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/feeds/{feed_id}/stream.mjpg", dependencies=secured)
def stream_frames(feed_id: str) -> StreamingResponse:
    _require_feed(feed_id)
    return StreamingResponse(hub.stream(feed_id), media_type="multipart/x-mixed-replace; boundary=frame")


@app.post("/api/feeds/{feed_id}/golden", dependencies=secured)
def capture_golden(feed_id: str) -> dict:
    image = hub.latest_image(feed_id)
    if image is None:
        raise HTTPException(409, "no frame from this feed yet")
    hub.state(feed_id).golden = image
    return {"has_golden": True}


class FeedInspect(BaseModel):
    serial: str = Field(default_factory=lambda: f"LIVE-{int(time.time())}", max_length=64)
    use_sample_board: bool = False


async def _inspect_feed(feed_id: str, body: FeedInspect) -> dict:
    image = hub.latest_image(feed_id)
    if image is None:
        raise HTTPException(409, "no frame from this feed yet")
    golden = hub.state(feed_id).golden
    if golden is None and not body.use_sample_board:
        raise HTTPException(409, "capture a golden frame from this feed first")
    inspector = ins.sample_inspector() if body.use_sample_board else ins.live_inspector(golden)
    try:
        result = await asyncio.to_thread(inspector.inspect, image)
    except RuntimeError as exc:
        raise _inspect_error(exc) from exc
    return await _finish(body.serial, f"feed:{feed_id}", result)


@app.post("/api/feeds/{feed_id}/inspect", dependencies=secured)
async def inspect_feed(feed_id: str, body: FeedInspect) -> dict:
    return await _inspect_feed(feed_id, body)


@app.websocket("/ws/ingest/{feed_id}")
async def ingest(ws: WebSocket, feed_id: str, token: str | None = None) -> None:
    """Binary messages are JPEG frames. Text messages are JSON readings or triggers."""
    await ws.accept()
    with SessionLocal() as db:
        known = db.get(Feed, feed_id) is not None
    if not known or not _valid_token(token):
        await ws.close(code=4401)
        return
    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("bytes"):
                try:
                    hub.push_frame(feed_id, message["bytes"])
                except ValueError as exc:
                    await ws.send_json({"error": str(exc)})
            elif message.get("text"):
                await _ingest_json(ws, feed_id, message["text"])
    except WebSocketDisconnect:
        return


async def _ingest_json(ws: WebSocket, feed_id: str, text: str) -> None:
    try:
        event = json.loads(text)
        if event.get("type") == "reading":
            values = {str(k): float(v) for k, v in event["values"].items()}
            alerts = hub.push_readings(feed_id, values)
            await sockets.broadcast({"type": "sensor_reading", "feed_id": feed_id, "values": values, "alerts": alerts})
        elif event.get("type") == "trigger":
            await sockets.broadcast({"type": "plc_trigger", "feed_id": feed_id, "serial": event.get("serial")})
            camera = event.get("camera_feed_id")
            if camera:
                await _inspect_feed(camera, FeedInspect(serial=event.get("serial") or f"PLC-{int(time.time())}"))
    except (KeyError, TypeError, ValueError) as exc:
        await ws.send_json({"error": f"bad message: {exc}"})
    except HTTPException as exc:
        await ws.send_json({"error": exc.detail})


@app.websocket("/ws/shopfloor")
async def shopfloor(ws: WebSocket, token: str | None = None) -> None:
    await ws.accept()
    if not _valid_token(token):
        await ws.close(code=4401)
        return
    sockets.clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        sockets.clients.discard(ws)


@app.post("/api/inspect/upload", dependencies=secured)
async def inspect_upload(image: Annotated[UploadFile, File()], serial: Annotated[str, Form()] = "") -> dict:
    data = await image.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "image too large")
    decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if decoded is None:
        raise HTTPException(422, "not an image")
    try:
        result = await asyncio.to_thread(ins.sample_inspector().inspect, decoded)
    except RuntimeError as exc:
        raise _inspect_error(exc) from exc
    return await _finish(serial or f"UPLOAD-{int(time.time())}", "upload", result)
