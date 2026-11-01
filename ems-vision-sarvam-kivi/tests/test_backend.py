from __future__ import annotations

import asyncio
import json
import shutil
import socketserver
import struct
import threading
from pathlib import Path

import cv2
import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import languages as L
from app.config.settings import settings
from app.main import app
from app.services import feeds
from app.services.kivi_engine import DictionaryEntry, KiviSpace, apply_dictionary, expand_shortcuts, phonetic_key, spoken_key
from app.services.sarvam_service import SarvamService, dominant_script, split_text
from vision.plc import ModbusTcpTrigger

CODES = [lang.code for lang in L.LANGUAGES]
MAYURA = {"bn-IN", "en-IN", "gu-IN", "hi-IN", "kn-IN", "ml-IN", "mr-IN", "od-IN", "pa-IN", "ta-IN", "te-IN"}
SEED = Path(__file__).resolve().parents[1] / "backend" / "data" / "kivi_space"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def space(tmp_path) -> KiviSpace:
    for f in SEED.glob("*.json"):
        shutil.copy(f, tmp_path)
    return KiviSpace(tmp_path)


def live_service(handler):
    """A service in real-API mode whose HTTP goes to `handler` instead of the network."""
    settings.force_demo_mode = False
    settings.sarvam_api_key = "test"
    return SarvamService(httpx.MockTransport(handler))


@pytest.fixture
def restore_settings():
    demo, key = settings.force_demo_mode, settings.sarvam_api_key
    yield
    settings.force_demo_mode, settings.sarvam_api_key = demo, key


def test_all_23_codes_exist_and_are_unique():
    assert len(CODES) == len(set(CODES)) == 23
    assert {"ks-IN", "brx-IN", "doi-IN", "kok-IN", "mai-IN", "mni-IN", "sat-IN", "sd-IN", "sa-IN"} <= set(CODES)


def test_frontend_language_list_mirrors_backend():
    ts = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "config" / "languages.ts").read_text(encoding="utf-8")
    for lang in L.LANGUAGES:
        assert f'"{lang.code}"' in ts and lang.native in ts


@pytest.mark.parametrize("code", CODES)
def test_translation_routing(code):
    route = L.route_translation(code)
    if code == "en-IN":
        assert route is None
    else:
        assert route == ("sarvam-translate:v1", "formal")
    mixed = L.route_translation(code, prefer_code_mixed=True)
    if code in MAYURA and code != "en-IN":
        assert mixed == ("mayura:v1", "code-mixed")
    elif code != "en-IN":
        assert mixed == ("sarvam-translate:v1", "formal")


@pytest.mark.parametrize("code", CODES)
def test_translate_request_shape(code, restore_settings):
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"translated_text": "ok"})

    result = asyncio.run(live_service(handler).translate("Pin 4 at 350°C", code))
    if code == "en-IN":
        assert result["model"] == "passthrough" and not seen
    else:
        assert seen["target_language_code"] == code and seen["model"] == "sarvam-translate:v1"


def test_mayura_input_is_split_at_its_limit(restore_settings):
    sizes = []

    def handler(request):
        sizes.append(len(json.loads(request.content)["input"]))
        return httpx.Response(200, json={"translated_text": "x"})

    asyncio.run(live_service(handler).translate("Check this joint now. " * 100, "hi-IN", code_mixed=True))
    assert len(sizes) > 1 and max(sizes) <= 1000


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("mode", L.STT_MODES)
def test_stt_routes_every_language_and_mode_with_keyterms(code, mode, space, restore_settings):
    seen = {}

    def handler(request):
        seen["body"] = request.content
        return httpx.Response(200, json={"transcript": "ok", "language_code": code})

    asyncio.run(live_service(handler).transcribe(b"RIFF", "a.wav", "audio/wav", code, mode, space.keyterms()))
    body = seen["body"].decode("utf-8", "ignore")
    assert "saaras:v4" in body and f'"{code}"'.strip('"') in body and mode in body
    assert '"QFN-48"' in body and "keyterms" in body


def test_keyterms_respect_the_api_limits(space):
    terms = space.keyterms()
    assert "QFN-48" in terms and "Tombstoning" in terms
    for i in range(80):
        space.upsert("dictionary", DictionaryEntry(canonical_term=f"TERM{i}"))
    space.upsert("dictionary", DictionaryEntry(canonical_term="x" * 65))
    terms = space.keyterms()
    assert len(terms) == 50 and all(len(t) <= 64 for t in terms)


@pytest.mark.parametrize("code", CODES)
def test_tts_never_fails_for_any_language(code, restore_settings):
    calls = []

    def handler(request):
        if request.url.path == "/translate":
            return httpx.Response(200, json={"translated_text": "हिंदी"})
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"audios": ["QUJD"]})

    lang = L.get_language(code)
    text = {"DEVANAGARI": "जाँच करें"}.get("DEVANAGARI") if lang.tts_bridge == "hi-IN" else "যাচাই করুন"
    result = asyncio.run(live_service(handler).speak(text, code))
    assert result.audio_base64 == "QUJD"
    if lang.tts_model:
        assert (result.engine, result.spoken_language, result.note) == (lang.tts_model, code, None)
    else:
        assert result.note and calls[-1]["language_code"] == lang.tts_bridge


def test_tts_flash_is_not_sent_unsupported_languages():
    for code in ("ml-IN", "od-IN"):
        assert L.get_language(code).tts_model == "bulbul:v3"


@pytest.mark.parametrize("text", ["ᱡᱟᱹᱧᱪ ᱢᱮ", "جانچ کریں"])
def test_tts_translates_scripts_no_voice_can_read(text, restore_settings):
    calls = []

    def handler(request):
        if request.url.path == "/translate":
            return httpx.Response(200, json={"translated_text": "जाँच करें"})
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"audios": ["QUJD"]})

    result = asyncio.run(live_service(handler).speak(text, "sat-IN"))
    assert calls[0]["text"] == "जाँच करें" and "Hindi translation" in result.note


def test_tts_falls_back_to_browser_when_sarvam_is_down(restore_settings):
    result = asyncio.run(live_service(lambda r: httpx.Response(503, text="down")).speak("hello", "en-IN"))
    assert result.audio_base64 is None and result.engine == "web-speech"


def test_script_detection_and_sentence_splitting():
    assert dominant_script("पिन 4 जाँचें") == "DEVANAGARI" and dominant_script("جانچ") == "ARABIC"
    assert all(len(c) <= 50 for c in split_text("One two three. " * 30, 50))


@pytest.mark.parametrize("heard,wrote", [
    ("q f n forty eight", "QFN-48"), ("cue eff en forty eight", "QFN-48"), ("qfn 48", "QFN-48"),
    ("tomb stoning", "Tombstoning (IPC-A-610 Defect)"), ("are four oh two", "R402"), ("you twelve", "U12"),
    ("see nineteen", "C19"), ("flucks", "Flux"), ("desoldering wick", "Desoldering Wick"),
])
def test_dictionary_writes_canonical_term(heard, wrote, space):
    text, changes = apply_dictionary(heard, space.dictionary())
    assert text == wrote and changes


def test_fuzzy_match_catches_unlisted_spelling(space):
    text, changes = apply_dictionary("found a soldar bridge here", space.dictionary())
    assert "Solder Bridge" in text and changes[0].match == "fuzzy"


@pytest.mark.parametrize("heard,wrote", [
    ("U12 has a solder bridge on pin 5.", "U12 has a Solder Bridge on pin 5."),
    ("Apply flux, then use desoldering wick.", "Apply Flux, then use Desoldering Wick."),
    ("R402 is missing, check the stencil.", "R402 is missing, check the Stencil."),
    ("QFN 48 on the AOI reject list.", "QFN-48 on the AOI reject list."),
])
def test_fuzzy_match_never_swallows_neighbouring_words(heard, wrote, space):
    assert apply_dictionary(heard, space.dictionary())[0] == wrote


def test_fuzzy_match_never_changes_a_number(space):
    assert apply_dictionary("r four zero three", space.dictionary())[0] != "R402"
    assert "R402" not in apply_dictionary("R403 is fine", space.dictionary())[0]


def test_plain_words_and_hindi_pass_through(space):
    sentence = "मैंने U12 ठीक किया and you can see the board"
    assert "मैंने" in apply_dictionary(sentence, space.dictionary())[0]
    assert apply_dictionary("you can see the board", space.dictionary())[0] == "you can see the board"


def test_shortcut_expands_inside_a_sentence(space):
    entries = space.dictionary()
    text, _ = apply_dictionary("u twelve done, log bridge fixed.", entries)
    expanded, used = expand_shortcuts(text, space.shortcuts(), entries)
    assert expanded.startswith("U12") and "1.5mm copper braid at 360°C" in expanded and used == ["bridge-fixed"]


def test_spoken_keys():
    assert spoken_key("Q F N forty-eight") == spoken_key("QFN-48") == "qfn48"
    assert phonetic_key("flucks") == phonetic_key("flux")


def test_api_inspect_flow_and_persistence(client):
    cases = client.get("/api/cases").json()
    assert len(cases) == 6
    with client.websocket_connect("/ws/shopfloor") as ws:
        body = client.post("/api/inspect", json={"case_id": "case_02_tombstone_c14"}).json()
        assert ws.receive_json()["type"] == "inspection"
    assert body["verdict"] == "FAIL" and body["defects"][0]["bom"]["designator"] == "C14"
    assert body["diagnoses"][0]["hypotheses"][0]["fault"] == "Reflow Thermal Zone Ramp Rate"
    assert client.get("/api/inspections").json()[0]["serial"] == body["serial"]
    assert client.post("/api/inspect", json={"case_id": "../../secrets"}).status_code == 404


def test_api_demo_language_and_kivi(client):
    assert len(client.get("/api/languages").json()) == 23
    assert client.post("/api/translate", json={"text": "x", "target": "zz-IN"}).status_code == 422
    assert client.post("/api/tts", json={"text": "x", "language": "sat-IN"}).json()["audio_base64"]
    reply = client.post("/api/kivi/transcribe", files={"audio": ("a.webm", b"x", "audio/webm")}).json()
    assert "U12" in reply["styled_text"] and "copper braid" in reply["styled_text"] and reply["keyterms_sent"] == 20
    assert client.get("/api/kivi/history").json()[0]["id"] == reply["id"]


def _jpeg(fill: int = 90) -> bytes:
    rng = np.random.default_rng(5)
    image = rng.integers(0, 255, (300, 400, 3), np.uint8)
    image = cv2.GaussianBlur(image, (5, 5), 0)
    image[:40, :40] = fill
    return cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()


def test_many_feeds_run_at_once(client):
    ids = [client.post("/api/feeds", json={"name": f"cam {i}", "kind": "browser_camera"}).json()["id"] for i in range(4)]
    sensor = client.post("/api/feeds", json={"name": "fixture", "kind": "sensor", "role": "sensor"}).json()["id"]
    sockets = [client.websocket_connect(f"/ws/ingest/{i}") for i in ids]
    for ws in sockets:
        ws.__enter__().send_bytes(_jpeg())
    with client.websocket_connect(f"/ws/ingest/{sensor}") as ws:
        ws.send_text(json.dumps({"type": "reading", "values": {"rail_5v_v": 4.5, "board_temp_c": 40}}))
        ws.send_text("not json")
        assert "bad message" in ws.receive_json()["error"]
    for ws in sockets:
        ws.__exit__(None, None, None)
    feeds_now = {f["id"]: f for f in client.get("/api/feeds").json()}
    assert all(feeds_now[i]["live"] and feeds_now[i]["frames"] == 1 for i in ids)
    assert feeds_now[sensor]["alerts"] == [{"reading": "rail_5v_v", "value": 4.5, "min": 4.75, "max": 5.25}]
    assert client.get(f"/api/feeds/{ids[0]}/latest.jpg").content[:2] == b"\xff\xd8"


def test_live_feed_golden_then_inspect(client):
    feed = client.post("/api/feeds", json={"name": "bench", "kind": "browser_camera"}).json()["id"]
    assert client.post(f"/api/feeds/{feed}/inspect", json={}).status_code == 409
    with client.websocket_connect(f"/ws/ingest/{feed}") as ws:
        ws.send_bytes(_jpeg())
        ws.send_text(json.dumps({"type": "reading", "values": {}}))
    assert client.post(f"/api/feeds/{feed}/golden").status_code == 200
    assert client.post(f"/api/feeds/{feed}/inspect", json={"serial": "B-1"}).json()["verdict"] == "PASS"


def test_ingest_rejects_unknown_feed_and_non_jpeg(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/ingest/nope") as ws:
            ws.receive_text()
    with pytest.raises(ValueError):
        feeds.hub.push_frame("x", b"not a jpeg")


def test_private_urls_blocked_on_public_host():
    settings.allow_private_feed_urls = False
    try:
        for url in ("http://127.0.0.1/x", "http://169.254.169.254/latest", "rtsp://192.168.1.9/s"):
            with pytest.raises(ValueError):
                feeds.validate_feed_url(url)
    finally:
        settings.allow_private_feed_urls = True
    with pytest.raises(ValueError):
        feeds.validate_feed_url("file:///etc/passwd")


def test_access_token_is_enforced(client):
    settings.app_access_token = "secret"
    try:
        assert client.get("/api/feeds").status_code == 401
        assert client.get("/api/feeds", headers={"x-access-token": "secret"}).status_code == 200
        assert client.get("/api/health").status_code == 200
    finally:
        settings.app_access_token = ""


def test_modbus_rising_edge_against_a_real_socket():
    states = iter([0, 1, 1, 0, 1])

    class Plc(socketserver.BaseRequestHandler):
        def handle(self):
            head = self.request.recv(12)
            tid = struct.unpack(">H", head[:2])[0]
            self.request.sendall(struct.pack(">HHHBBBB", tid, 0, 4, 1, 1, 1, next(states)))

    server = socketserver.TCPServer(("127.0.0.1", 0), Plc)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    trigger = ModbusTcpTrigger("127.0.0.1", server.server_address[1])
    assert [trigger.fired() for _ in range(5)] == [False, True, False, False, True]
    server.shutdown()
