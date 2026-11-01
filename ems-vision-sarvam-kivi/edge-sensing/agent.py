"""Edge agent. Runs on the factory network and pushes feeds out to the website.

A hosted site cannot reach cameras or PLCs on a private LAN, so this process connects
outward: no inbound ports need opening on the factory side.

Examples:
  python edge-sensing/agent.py --server wss://api.example.com --feed <id> --camera rtsp://10.0.0.5/stream
  python edge-sensing/agent.py --server ws://localhost:8000 --feed <id> --camera folder:backend/data/sample_pcbs
  python edge-sensing/agent.py --server ws://localhost:8000 --feed <id> --camera gige:C:/vendor/producer.cti
  python edge-sensing/agent.py --server ws://localhost:8000 --feed <id> --sensor simulated
  python edge-sensing/agent.py --server ws://localhost:8000 --feed <id> --trigger modbus:10.0.0.9:502:0 --camera-feed <id>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import time
from pathlib import Path

import cv2
import websockets

from vision.camera import Camera, FolderCamera, GigEVisionCamera, OpenCvCamera
from vision.plc import ModbusTcpTrigger, OpcUaTrigger, SimulatedTrigger, Trigger


def open_camera(spec: str) -> Camera:
    if spec.startswith("folder:"):
        return FolderCamera(Path(spec[7:]))
    if spec.startswith("gige:"):
        return GigEVisionCamera(spec[5:])
    return OpenCvCamera(int(spec) if spec.isdigit() else spec)


def open_trigger(spec: str) -> Trigger:
    kind, _, rest = spec.partition(":")
    if kind == "modbus":
        host, port, coil = rest.split(":")
        return ModbusTcpTrigger(host, int(port), int(coil))
    if kind == "opcua":
        url, _, node = rest.rpartition("|")
        return OpcUaTrigger(url, node)
    return SimulatedTrigger(float(rest or 5))


def read_sensors(spec: str) -> dict[str, float]:
    if spec == "simulated":
        return {"rail_5v_v": round(random.gauss(5.0, 0.12), 3), "board_temp_c": round(random.gauss(52, 7), 1),
                "j3_contact_mohm": round(random.gauss(28, 12), 1)}
    # serial:COM3:115200 expects one JSON object per line from the fixture.
    import serial

    _, port, baud = spec.split(":")
    with serial.Serial(port, int(baud), timeout=2) as link:
        return {k: float(v) for k, v in json.loads(link.readline()).items()}


async def run(args: argparse.Namespace) -> None:
    url = f"{args.server.rstrip('/')}/ws/ingest/{args.feed}"
    token = os.environ.get("APP_ACCESS_TOKEN")
    if token:
        url += f"?token={token}"
    camera = open_camera(args.camera) if args.camera else None
    trigger = open_trigger(args.trigger) if args.trigger else None
    period = 1 / args.fps
    while True:
        try:
            async with websockets.connect(url, max_size=None) as ws:
                print("connected")
                while True:
                    started = time.monotonic()
                    if camera:
                        frame = await asyncio.to_thread(camera.grab)
                        if frame is not None:
                            ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, args.quality])
                            if ok:
                                await ws.send(jpeg.tobytes())
                    if args.sensor:
                        values = await asyncio.to_thread(read_sensors, args.sensor)
                        await ws.send(json.dumps({"type": "reading", "values": values}))
                    if trigger and await asyncio.to_thread(trigger.fired):
                        await ws.send(json.dumps({"type": "trigger", "camera_feed_id": args.camera_feed}))
                    await asyncio.sleep(max(0.0, period - (time.monotonic() - started)))
        except (OSError, websockets.ConnectionClosed) as exc:
            print(f"disconnected ({exc}), retrying in 3 s")
            await asyncio.sleep(3)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", required=True)
    parser.add_argument("--feed", required=True)
    parser.add_argument("--camera", help="device index, rtsp:// URL, folder:<path> or gige:<cti file>")
    parser.add_argument("--sensor", help="simulated or serial:<port>:<baud>")
    parser.add_argument("--trigger", help="sim:<seconds>, modbus:<host>:<port>:<coil> or opcua:<url>|<node>")
    parser.add_argument("--camera-feed", help="camera feed to inspect when the trigger fires")
    parser.add_argument("--fps", type=float, default=5)
    parser.add_argument("--quality", type=int, default=85)
    asyncio.run(run(parser.parse_args()))
