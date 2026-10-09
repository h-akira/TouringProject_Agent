#!/usr/bin/env python3
"""Ask the agent a question locally, as the Backend would, without a device.

Builds the prompt and payload in the shape of docs-parent/03_units_contracts.md
UC-5 (date, position, address, heading, then the question) and runs it through
the agent code in app/ - the real model on Bedrock and the real tools - then
prints which tools were called and the answer.

The address line is only added when --address is given: resolving it is the
Backend's job, and this is about what the agent does with the facts it gets.

Use public landmarks, never a real position from a device.

Usage (from Agent/app/agentcore_trg_dev_ask, with its .venv):
    eval "$(aws configure export-credentials --profile touring --format env)"
    .venv/bin/python ../../scripts/ask_local.py "右手に見える公園は？" \\
        --lat 35.6812 --lon 139.7671 --heading 0 --address 東京都千代田区丸の内
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

APP_DIR = Path(__file__).resolve().parents[1] / "app" / "agentcore_trg_dev_ask"
sys.path.insert(0, str(APP_DIR))

JST = timezone(timedelta(hours=9))
_WEEKDAYS = "月火水木金土日"
_COMPASS = (
    "北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東",
    "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西",
)


def _compass(degrees: float) -> str:
    return _COMPASS[int((degrees % 360) / 22.5 + 0.5) % 16]


def build_prompt(
    question: str,
    lat: Optional[float],
    lon: Optional[float],
    heading: Optional[float],
    address: Optional[str],
) -> str:
    """The prompt in the contract's shape (UC-5)."""
    now = datetime.now(JST)
    lines = [
        f"【現在日時: {now.year}年{now.month}月{now.day}日（{_WEEKDAYS[now.weekday()]}）"
        f"{now.hour}時{now.minute:02d}分（日本時間）】"
    ]
    if lat is not None and lon is not None:
        lines.append(f"現在地: 緯度 {lat}, 経度 {lon}")
        if address:
            lines.append(f"現在地の住所: {address}（この住所は正確です。自分で座標から推測しないこと）")
        if heading is not None:
            lines.append(f"進行方向: {_compass(heading)}（真北から{round(heading)}度）")
            lines.append(
                f"ライダーから見て右手は{_compass(heading + 90)}、"
                f"左手は{_compass(heading - 90)}の方角"
            )
    return "\n".join(lines) + f"\n\n質問: {question}"


def build_payload(prompt: str, lat, lon, heading) -> dict:
    payload: dict = {"question": prompt}
    if lat is not None and lon is not None:
        payload["location"] = {"latitude": lat, "longitude": lon}
        if heading is not None:
            payload["location"]["headingDegrees"] = heading
    return payload


async def run(payload: dict, session_id: str) -> None:
    import main  # noqa: PLC0415 - needs APP_DIR on sys.path first

    context = SimpleNamespace(session_id=session_id)
    answer = ""
    async for event in main.invoke(payload, context):
        if "error" in event:
            print(f"error: {event['error']}")
            return
        inner = event.get("event", {})
        start = inner.get("contentBlockStart", {}).get("start", {})
        if "toolUse" in start:
            print(f"[tool] {start['toolUse'].get('name')}")
            # Same rule as the Backend: text before the last tool call is dropped.
            answer = ""
        text = inner.get("contentBlockDelta", {}).get("delta", {}).get("text")
        if text:
            answer += text

    agent = main._SESSION_AGENTS[session_id]
    for message in agent.messages:
        for block in message.get("content", []):
            if "toolUse" in block:
                print(f"[tool input] {json.dumps(block['toolUse'].get('input'), ensure_ascii=False)}")
            if "toolResult" in block:
                for part in block["toolResult"].get("content", []):
                    if "text" in part:
                        print("[tool result]\n" + part["text"])
    print("\n[answer]\n" + answer.strip())


def main_cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("question")
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lon", type=float)
    parser.add_argument("--heading", type=float, help="degrees from north")
    parser.add_argument("--address", help="what the Backend would have resolved")
    parser.add_argument("--session", default="local-ask-" + "0" * 24)
    parser.add_argument("--show-prompt", action="store_true")
    args = parser.parse_args()

    prompt = build_prompt(args.question, args.lat, args.lon, args.heading, args.address)
    payload = build_payload(prompt, args.lat, args.lon, args.heading)
    if args.show_prompt:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    asyncio.run(run(payload, args.session))


if __name__ == "__main__":
    main_cli()
