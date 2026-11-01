# Sarvam Campus Day

An AI layer for post-PCB-assembly inspection in EMS factories. Finished boards are checked by hand in many Indian factories at the point where they get integrated into the product. The idea is sensors plus an AI agent that reads the sensor data and acts as a complete sensing unit at that step. This is also the basis of Aayush's IDEAS Program (IIT Bombay pre-incubation) pitch, with Indian EMS manufacturers as the first market.

## Files

- `first_call.py`: minimal Sarvam chat call, used to confirm the key and endpoint work.
- `inspector.py`: the inspector. `LIMITS` holds spec limits, `BOARDS` holds sample readings, `check()` decides pass/fail, `explain()` calls Sarvam for failures only.
- `.env`: holds `SARVAM_API_KEY`. Gitignored. Never hardcode, print or commit the key.

Run from this folder: `python inspector.py`. Windows, Python 3.14, `pip install sarvamai`.

## Design decisions

- Pass/fail is decided in code against numeric limits. The model never judges whether a reading is in spec.
- Sarvam is called only for boards that fail. It returns structured JSON: `likely_causes` (English), `next_action` (English), `operator_note_hi` (Hindi, for the floor operator).
- The limits in `LIMITS` are placeholders (5V rail 4.75-5.25 V, board temp max 65 C, J3 contact resistance max 50 mOhm). Replace with the real spec per board type.

## Sarvam API notes

- Model: `sarvam-105b`. Call: `client.chat.completions(...)` on `SarvamAI(api_subscription_key=...)`.
- Default SDK timeout is 60 s, which the reasoning model exceeds. Clients here use `timeout=180`.
- Structured output uses `response_format={"type": "json_schema", ...}` with `strict: True`. Reasoning tokens count toward `max_tokens` (2048 here); `reasoning_effort=None` disables thinking if it is too slow.
- Docs: https://docs.sarvam.ai/api/token-factory/chat-completions

## Status

- Verified on Aayush's machine: first call works; `inspector.py` runs end to end and the Hindi note comes out clean. The Hindi in the longer fields was rough, so have a Hindi speaker review it before any demo.
- After the last edit (English for `likely_causes` and `next_action`, "only list causes the readings support") the script has not been re-run.

## Next

- Replace the hardcoded `BOARDS` with a real feed (CSV or serial). Sensors for Campus Day are not decided yet.
- Per-board-type limits instead of one global `LIMITS`.
- Keep extending the idea itself: where the manual gap is, which sensors, what the factory buys.

## Website

`ems-vision-sarvam-kivi/` is the deployable site: Next.js frontend, FastAPI backend, edge agent. See its README and DEPLOY.md. Sarvam facts confirmed live: `bulbul:v4-flash` (no Malayalam or Odia, those use `bulbul:v3`), TTS field is `language_code`, parallel translate calls hit the rate limit.

## Working notes

- Aayush wants minimal, scoped edits, direct technical answers, and docs that do not read as AI-generated.
- Version control is GitHub Desktop on this folder. Do not run git commands that write; leave changes in the working tree for him to commit.
