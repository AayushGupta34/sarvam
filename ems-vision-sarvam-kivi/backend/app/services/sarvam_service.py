"""Sarvam translate, speech-to-text, text-to-speech and chat, with an offline demo mode."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import re
import struct
import unicodedata
import wave
from dataclasses import dataclass

import httpx

from ..config.languages import (MAX_KEYTERM_CHARS, MAX_KEYTERMS, STT_MODEL, STT_MODES, TRANSLATE_MAYURA,
                                get_language, route_translation)
from ..config.settings import settings

MAX_CHARS = {TRANSLATE_MAYURA: 1000, "sarvam-translate:v1": 2000}
TTS_MAX_CHARS = 2500
TIMEOUT = httpx.Timeout(60, connect=15)


class SarvamError(RuntimeError):
    pass


@dataclass
class TtsResult:
    audio_base64: str | None
    engine: str  # model id, "demo-tone" or "web-speech"
    spoken_language: str
    note: str | None = None


def dominant_script(text: str) -> str:
    counts: dict[str, int] = {}
    for ch in text:
        if ch.isalpha():
            name = unicodedata.name(ch, "OTHER").split(" ")[0]
            counts[name] = counts.get(name, 0) + 1
    return max(counts, key=counts.get) if counts else "LATIN"  # type: ignore[arg-type]


def split_text(text: str, limit: int) -> list[str]:
    """Split on sentence ends so that no chunk exceeds the model's input limit."""
    chunks, current = [], ""
    for sentence in re.split(r"(?<=[.!?।])\s+", text):
        while len(sentence) > limit:
            chunks.append(sentence[:limit])
            sentence = sentence[limit:]
        if current and len(current) + len(sentence) + 1 > limit:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    return chunks + ([current] if current else [])


def demo_wave(text: str, seconds: float = 1.6, rate: int = 16000) -> str:
    """Base64 WAV of a shaped tone, so the audio player has something real to play offline."""
    frames = bytearray()
    base = 150 + (sum(map(ord, text)) % 80)
    for i in range(int(seconds * rate)):
        t = i / rate
        envelope = max(0.0, math.sin(math.pi * t * 7)) * min(1.0, (seconds - t) * 4)
        sample = 0.5 * math.sin(2 * math.pi * base * t) + 0.3 * math.sin(4 * math.pi * base * t)
        frames += struct.pack("<h", int(sample * envelope * 18000))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return base64.b64encode(buffer.getvalue()).decode()


class SarvamService:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(base_url=settings.sarvam_base_url, timeout=TIMEOUT, transport=transport,
                                         headers={"api-subscription-key": settings.sarvam_api_key})
        self._cache_path = settings.data_dir / "demo_translations.json"
        self._cache: dict[str, dict[str, str]] | None = None

    @property
    def demo(self) -> bool:
        return settings.demo_mode

    def _demo_translations(self) -> dict[str, dict[str, str]]:
        if self._cache is None:
            exists = self._cache_path.exists()
            self._cache = json.loads(self._cache_path.read_text(encoding="utf-8")) if exists else {}
        return self._cache

    async def _post(self, path: str, **kwargs) -> dict:
        try:
            response = await self._client.post(path, **kwargs)
        except httpx.HTTPError as exc:
            raise SarvamError(f"{path}: {exc}") from exc
        if response.status_code >= 400:
            raise SarvamError(f"{path}: HTTP {response.status_code}: {response.text[:300]}")
        return response.json()

    async def translate(self, text: str, target: str, source: str = "en-IN", code_mixed: bool = False) -> dict:
        route = route_translation(target, code_mixed)
        if route is None or source == target:
            return {"text": text, "model": "passthrough", "mode": None, "demo": False}
        model, mode = route
        if self.demo:
            cached = self._demo_translations().get(text, {}).get(target)
            return {"text": cached or f"[{target} demo] {text}", "model": "demo-cache" if cached else "demo-tag", "mode": mode, "demo": True}
        parts = []
        for chunk in split_text(text, MAX_CHARS[model]):
            body = {"input": chunk, "source_language_code": source, "target_language_code": target, "model": model, "mode": mode}
            parts.append((await self._post("/translate", json=body))["translated_text"])
        return {"text": " ".join(parts), "model": model, "mode": mode, "demo": False}

    async def transcribe(self, audio: bytes, filename: str, content_type: str, language: str | None = None,
                         mode: str = "codemix", keyterms: list[str] | None = None) -> dict:
        if mode not in STT_MODES:
            raise ValueError(f"unsupported STT mode: {mode}")
        if language not in (None, "unknown"):
            get_language(language)
        terms = [t for t in (keyterms or []) if len(t) <= MAX_KEYTERM_CHARS][:MAX_KEYTERMS]
        if self.demo:
            return {"transcript": "u twelve pin five six solder bridge theek kar diya, log bridge fixed",
                    "language_code": language or "hi-IN", "model": "demo", "keyterms": terms, "demo": True}
        data = {"model": STT_MODEL, "mode": mode, "language_code": language or "unknown"}
        if terms:
            data["keyterms"] = json.dumps(terms, ensure_ascii=False)
        reply = await self._post("/speech-to-text", data=data, files={"file": (filename, audio, content_type)})
        return {"transcript": reply["transcript"], "language_code": reply.get("language_code"),
                "model": STT_MODEL, "keyterms": terms, "demo": False}

    async def _bulbul(self, text: str, code: str, model: str) -> str:
        body = {"text": text, "language_code": code, "model": model}
        reply = await self._post("/text-to-speech", json=body)
        return reply["audios"][0]

    async def speak(self, text: str, code: str) -> TtsResult:
        """Native voice, then a voice for the same script, then Hindi, then the browser."""
        if len(text) > TTS_MAX_CHARS:
            raise ValueError(f"text exceeds {TTS_MAX_CHARS} characters")
        lang = get_language(code)
        if self.demo:
            return TtsResult(demo_wave(text), "demo-tone", code, "Demo tone. Set SARVAM_API_KEY for real speech.")
        try:
            if lang.tts_model:
                return TtsResult(await self._bulbul(text, code, lang.tts_model), lang.tts_model, code)
            script = dominant_script(text)
            if script in ("DEVANAGARI", "BENGALI"):
                bridge = "hi-IN" if script == "DEVANAGARI" else "bn-IN"
                model = get_language(bridge).tts_model
                note = f"No {lang.name} voice yet. Read aloud by the {get_language(bridge).name} voice from the same script."
                return TtsResult(await self._bulbul(text, bridge, model), model, bridge, note)
            hindi = await self.translate(text, "hi-IN", source=code)
            model = get_language("hi-IN").tts_model
            note = f"No {lang.name} voice for this script yet. This audio is a Hindi translation."
            return TtsResult(await self._bulbul(hindi["text"], "hi-IN", model), model, "hi-IN", note)
        except SarvamError as exc:
            return TtsResult(None, "web-speech", code, f"Sarvam TTS unavailable, using browser speech: {exc}")

    async def chat_json(self, system: str, user: str, schema: dict, name: str = "reply") -> dict:
        """Structured chat. Blocking SDK call, so it runs on a worker thread."""
        if self.demo:
            raise SarvamError("chat is unavailable in demo mode")

        def call() -> dict:
            from sarvamai import SarvamAI

            client = SarvamAI(api_subscription_key=settings.sarvam_api_key, timeout=180)
            reply = client.chat.completions(
                model=settings.chat_model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                reasoning_effort="low",
                max_tokens=2048,
                response_format={"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
            )
            return json.loads(reply.choices[0].message.content)

        try:
            return await asyncio.to_thread(call)
        except Exception as exc:
            raise SarvamError(f"chat failed: {type(exc).__name__}") from exc


sarvam = SarvamService()
