"""Short real-API check: translate, speak and transcribe once, plus the structured chat call."""
from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "edge-sensing")]

from app.services.kivi_engine import KiviSpace  # noqa: E402
from app.config.settings import settings  # noqa: E402
from app.services.sarvam_service import SarvamError, sarvam  # noqa: E402

TEXT = "Check pin 4 of U12."


async def step(name, call):
    try:
        print(name, "OK", await call())
    except (SarvamError, KeyError, ValueError) as exc:
        print(name, "FAILED", str(exc)[:300])


async def main() -> None:
    print("demo mode:", settings.demo_mode)
    for code in ("hi-IN", "ks-IN", "sat-IN"):
        await step(f"translate {code}", lambda: sarvam.translate(TEXT, code))
    await step("translate mayura", lambda: sarvam.translate(TEXT, "ta-IN", code_mixed=True))
    for code in ("hi-IN", "ml-IN", "doi-IN"):
        async def speak(code=code):
            text = (await sarvam.translate(TEXT, code))["text"]
            r = await sarvam.speak(text, code)
            return r.engine, r.spoken_language, r.note, len(r.audio_base64 or "")
        await step(f"tts {code}", speak)

    async def stt():
        audio = base64.b64decode((await sarvam.speak("U12 has a solder bridge", "en-IN")).audio_base64)
        out = []
        for mode in ("transcribe", "codemix"):
            r = await sarvam.transcribe(audio, "a.wav", "audio/wav", "en-IN", mode, KiviSpace(settings.kivi_space).keyterms())
            out.append((mode, r["transcript"]))
        return out
    await step("stt", stt)
    schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False}
    await step("chat", lambda: sarvam.chat_json("Reply with the word ok.", json.dumps({"q": "ping"}), schema))


if __name__ == "__main__":
    asyncio.run(main())
