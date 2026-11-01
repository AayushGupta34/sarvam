"""Build backend/data/demo_translations.json from the real API for offline demo mode.

Run once with SARVAM_API_KEY set. Spends translation credits: 22 languages x 4 instructions.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "edge-sensing")]

from app.config.languages import LANGUAGES  # noqa: E402
from app.config.settings import settings  # noqa: E402
from app.services.inspection import list_cases, load_case, sample_inspector  # noqa: E402
from app.services.sarvam_service import SarvamError, sarvam  # noqa: E402


async def main() -> None:
    texts = []
    for case in list_cases():
        test, xray, _ = load_case(case["id"])
        texts += [d.rework_instruction_en for d in sample_inspector().inspect(test, xray).diagnoses]
    out: dict[str, dict[str, str]] = {}
    targets = [lang.code for lang in LANGUAGES if lang.code != "en-IN"]
    for text in dict.fromkeys(texts):
        out[text] = {}
        for code in targets:  # one at a time: parallel calls hit the account rate limit
            for attempt in range(4):
                try:
                    out[text][code] = (await sarvam.translate(text, code))["text"]
                    break
                except SarvamError:
                    await asyncio.sleep(2 ** attempt * 3)
    path = settings.data_dir / "demo_translations.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(out)} instructions x {len(targets)} languages written to {path}")


if __name__ == "__main__":
    asyncio.run(main())
