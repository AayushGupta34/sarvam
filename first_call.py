import os
from pathlib import Path

from sarvamai import SarvamAI


def load_env(path=".env"):
    p = Path(__file__).parent / path
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()
client = SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"], timeout=180)

response = client.chat.completions(
    model="sarvam-105b",
    messages=[
        {"role": "system", "content": "You are a post-assembly PCB inspection assistant. Reply in two short sentences."},
        {"role": "user", "content": "Board B-1042 readings: 5V rail 4.62V, board temp 71C after 2 min powered, connector J3 contact resistance 180 mOhm (limit 50). Pass or fail?"},
    ],
    reasoning_effort="low",
    max_tokens=2048,
)
print(response.choices[0].message.content)
