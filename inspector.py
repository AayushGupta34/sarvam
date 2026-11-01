"""Post-assembly board inspector.

Pass/fail is decided in code against spec limits. The model is only used to
explain failures: likely causes, a next action, and a Hindi note for the operator.
"""
import json
import os
from pathlib import Path

from sarvamai import SarvamAI

# (min, max) per reading. None means no bound. Placeholder limits: replace with
# the real spec for each board type.
LIMITS = {
    "rail_5v_v": (4.75, 5.25),
    "board_temp_c": (None, 65.0),
    "j3_contact_mohm": (None, 50.0),
}

BOARDS = [
    {"id": "B-1042", "rail_5v_v": 4.62, "board_temp_c": 71.0, "j3_contact_mohm": 180.0},
    {"id": "B-1043", "rail_5v_v": 5.02, "board_temp_c": 48.5, "j3_contact_mohm": 22.0},
]

SCHEMA = {
    "type": "object",
    "properties": {
        "likely_causes": {"type": "array", "items": {"type": "string"}},
        "next_action": {"type": "string"},
        "operator_note_hi": {"type": "string"},
    },
    "required": ["likely_causes", "next_action", "operator_note_hi"],
    "additionalProperties": False,
}


def load_env(path=".env"):
    p = Path(__file__).parent / path
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def check(board):
    out = []
    for name, (lo, hi) in LIMITS.items():
        v = board[name]
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            out.append({"reading": name, "value": v, "min": lo, "max": hi})
    return out


def explain(client, board, violations):
    r = client.chat.completions(
        model="sarvam-105b",
        messages=[
            {"role": "system", "content": (
                "You assist a technician after PCB assembly in an EMS factory. "
                "The board has already failed. Given the violated readings, list likely "
                "root causes (most likely first), one concrete next action, and a short "
                "operator note in Hindi (Devanagari). Write likely_causes and next_action in "
                "English. Only list causes the readings support."
            )},
            {"role": "user", "content": json.dumps({"board": board["id"], "violations": violations})},
        ],
        reasoning_effort="low",
        max_tokens=2048,
        response_format={"type": "json_schema", "json_schema": {
            "name": "failure_report", "strict": True, "schema": SCHEMA}},
    )
    return json.loads(r.choices[0].message.content)


if __name__ == "__main__":
    load_env()
    client = SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"], timeout=180)
    for b in BOARDS:
        v = check(b)
        if not v:
            print(f"{b['id']}: PASS")
            continue
        print(f"{b['id']}: FAIL {json.dumps(v)}")
        print(json.dumps(explain(client, b, v), ensure_ascii=False, indent=2))
