"""Synthetic golden-vs-defective PCB generator.

Writes one golden frame, the BOM centroids, a Gerber top copper layer with X2 pad
attributes, and one folder per case holding the warped test frame, an X-ray slice
of BGA1, and truth.json. Frames use 3-angle RGB lighting: each colour channel is
shaded from a height map with an LED ring at a different elevation.

Run: python edge-sensing/datasets/generate_demo_samples.py
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

BOARD_W_MM = 80.0
BOARD_H_MM = 60.0
PX_PER_MM = 25
NET_CYCLE = ["GND", "VCC_3V3", "SPI_CLK", "SPI_MOSI", "SPI_MISO", "I2C_SDA", "I2C_SCL", "UART_TX", "UART_RX", "GPIO_1"]

MASK_BGR = (52, 92, 20)
TRACE_BGR = (70, 130, 40)
TIN_BGR = (205, 205, 200)
COPPER_BGR = (90, 150, 205)
BODY_BGR = (38, 38, 42)
CAP_BGR = (95, 140, 170)
SILK_BGR = (235, 235, 235)


@dataclass
class Pad:
    designator: str
    pin: int
    net: str
    x: float  # centre, mm
    y: float
    w: float
    h: float


@dataclass
class Part:
    designator: str
    package: str
    x: float
    y: float
    w: float  # body size, mm
    h: float
    rotation: int = 0
    pads: list[Pad] = field(default_factory=list)

    @property
    def pin_count(self) -> int:
        return len(self.pads)


def _two_terminal(ref: str, pkg: str, x: float, y: float, w: float, h: float, nets: tuple[str, str]) -> Part:
    part = Part(ref, pkg, x, y, w, h)
    pad_w, pad_h = w * 0.42, h * 1.15
    part.pads = [
        Pad(ref, 1, nets[0], x - w / 2, y, pad_w, pad_h),
        Pad(ref, 2, nets[1], x + w / 2, y, pad_w, pad_h),
    ]
    return part


def _quad(ref: str, pkg: str, x: float, y: float, size: float, per_side: int, pitch: float) -> Part:
    part = Part(ref, pkg, x, y, size, size)
    span = (per_side - 1) * pitch
    pin = 1
    for side in range(4):
        for i in range(per_side):
            off = -span / 2 + i * pitch
            net = NET_CYCLE[(pin - 1) % len(NET_CYCLE)]
            long_, short = 0.8, pitch * 0.55
            if side == 0:
                pad = Pad(ref, pin, net, x - size / 2 - 0.1, y + off, long_, short)
            elif side == 1:
                pad = Pad(ref, pin, net, x + off, y + size / 2 + 0.1, short, long_)
            elif side == 2:
                pad = Pad(ref, pin, net, x + size / 2 + 0.1, y - off, long_, short)
            else:
                pad = Pad(ref, pin, net, x - off, y - size / 2 - 0.1, short, long_)
            part.pads.append(pad)
            pin += 1
    return part


def _bga(ref: str, x: float, y: float, size: float, rows: int) -> Part:
    part = Part(ref, f"BGA-{rows * rows}", x, y, size, size)
    pitch = (size - 1.5) / (rows - 1)
    start = -pitch * (rows - 1) / 2
    for r in range(rows):
        for c in range(rows):
            pin = r * rows + c + 1
            part.pads.append(Pad(ref, pin, NET_CYCLE[(pin - 1) % len(NET_CYCLE)], x + start + c * pitch, y + start + r * pitch, 0.45, 0.45))
    return part


def build_board() -> list[Part]:
    return [
        _quad("U12", "QFN-48", 21, 18, 7.0, 12, 0.5),
        _bga("BGA1", 58, 18, 15.0, 16),
        _two_terminal("C14", "0603", 12, 38, 1.6, 0.8, ("VCC_3V3", "GND")),
        _two_terminal("C45", "0603", 20, 38, 1.6, 0.8, ("VCC_3V3", "GND")),
        _two_terminal("R08", "0603", 30, 38, 1.6, 0.8, ("SPI_CLK", "SPI_CLK_R")),
        _two_terminal("R18", "0603", 38, 38, 1.6, 0.8, ("I2C_SDA", "VCC_3V3")),
        _two_terminal("D3", "SOD-123", 49, 38, 2.7, 1.6, ("VIN", "VIN_PROT")),
        _two_terminal("Q3", "SOT-23", 60, 38, 2.9, 1.3, ("GATE_Q3", "GND")),
        _two_terminal("C19", "0805", 14, 50, 2.0, 1.25, ("VCC_3V3", "GND")),
        _two_terminal("R402", "0603", 26, 50, 1.6, 0.8, ("UART_TX", "UART_TX_R")),
        _quad("U7", "QFP-16", 45, 50, 4.0, 4, 0.8),
    ]


def px(mm: float) -> int:
    return int(round(mm * PX_PER_MM))


def _fill(albedo: np.ndarray, height: np.ndarray, x0: float, y0: float, x1: float, y1: float, color: tuple[int, int, int], h: float) -> None:
    a, b = (px(x0), px(y0)), (px(x1), px(y1))
    cv2.rectangle(albedo, a, b, color, -1)
    cv2.rectangle(height, a, b, h, -1)


def _draw_body(albedo: np.ndarray, height: np.ndarray, part: Part, flipped: bool = False) -> None:
    x0, y0 = part.x - part.w / 2, part.y - part.h / 2
    x1, y1 = x0 + part.w, y0 + part.h
    if part.package in {"0603", "0805"}:
        color = CAP_BGR if part.designator.startswith("C") else BODY_BGR
        _fill(albedo, height, x0, y0, x1, y1, color, 0.5)
        return
    _fill(albedo, height, x0, y0, x1, y1, BODY_BGR, 1.0)
    if part.package == "SOD-123":
        band = part.w * 0.2
        bx0 = x1 - band * 1.3 if flipped else x0 + band * 0.3
        _fill(albedo, height, bx0, y0, bx0 + band, y1, SILK_BGR, 1.0)
    elif part.package.startswith(("QFN", "QFP", "BGA")):
        cv2.circle(albedo, (px(x0 + 0.8), px(y0 + 0.8)), px(0.3), SILK_BGR, -1)
        cv2.putText(albedo, part.package, (px(part.x - part.w * 0.3), px(part.y)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (150, 150, 150), 1, cv2.LINE_AA)


def _draw_pad(albedo: np.ndarray, height: np.ndarray, pad: Pad, soldered: bool = True) -> None:
    color = TIN_BGR if soldered else COPPER_BGR
    _fill(albedo, height, pad.x - pad.w / 2, pad.y - pad.h / 2, pad.x + pad.w / 2, pad.y + pad.h / 2, color, 0.3 if soldered else 0.1)


def render_scene(parts: list[Part], defects: list[dict] | None = None, seed: int = 7) -> np.ndarray:
    """Render the board in a fixed pose. `defects` is a list of {class, designator, ...}."""
    w, h = px(BOARD_W_MM), px(BOARD_H_MM)
    albedo = np.full((h, w, 3), MASK_BGR, np.uint8)
    height = np.zeros((h, w), np.float32)
    layout = np.random.default_rng(42)
    by_class = {(d["designator"], d["class"]): d for d in (defects or [])}

    for _ in range(46):
        a = (int(layout.integers(0, w)), int(layout.integers(0, h)))
        b = (a[0] + int(layout.integers(-500, 500)), a[1])
        c = (b[0], b[1] + int(layout.integers(-300, 300)))
        cv2.polylines(albedo, [np.array([a, b, c])], False, TRACE_BGR, 3, cv2.LINE_AA)
    for fx, fy in [(3, 3), (77, 3), (3, 57), (77, 57)]:
        cv2.circle(albedo, (px(fx), px(fy)), px(1), TIN_BGR, -1, cv2.LINE_AA)
        cv2.circle(height, (px(fx), px(fy)), px(1), 0.2, -1)
    for mx, my in [(70, 42), (70, 50)]:
        cv2.rectangle(albedo, (px(mx - 4), px(my - 3)), (px(mx + 4), px(my + 3)), SILK_BGR, 2)
        cv2.putText(albedo, "EMS-DEMO" if my < 45 else "REV B", (px(mx - 3.5), px(my + 0.5)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, SILK_BGR, 2, cv2.LINE_AA)

    for part in parts:
        ref = part.designator
        missing = (ref, "missing_component") in by_class
        tomb = (ref, "tombstoning") in by_class
        cv2.putText(albedo, ref, (px(part.x - part.w / 2), px(part.y - part.h / 2 - 1.1)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, SILK_BGR, 2, cv2.LINE_AA)
        if part.package.startswith("BGA"):
            _draw_body(albedo, height, part)
            continue
        for pad in part.pads:
            _draw_pad(albedo, height, pad, soldered=not missing)
        if missing:
            continue
        if tomb:
            # Part stands on pad 1: only a sliver of the body stays over that pad and pad 2 is bare.
            x0 = part.x - part.w / 2 - 0.2
            _fill(albedo, height, x0, part.y - part.h / 2, x0 + part.w * 0.3, part.y + part.h / 2, (225, 235, 245), 2.0)
            _draw_pad(albedo, height, part.pads[1], soldered=False)
            continue
        _draw_body(albedo, height, part, flipped=(ref, "polarity_error") in by_class)

    bridge = next((d for d in (defects or []) if d["class"] == "solder_bridge"), None)
    if bridge:
        part = next(p for p in parts if p.designator == bridge["designator"])
        a, b = [next(p for p in part.pads if p.pin == n) for n in bridge["pins"]]
        cv2.ellipse(albedo, (px((a.x + b.x) / 2), px((a.y + b.y) / 2)), (px(0.42), px(abs(a.y - b.y) / 2 + 0.33)), 0, 0, 360, (250, 250, 250), -1, cv2.LINE_AA)
        cv2.ellipse(height, (px((a.x + b.x) / 2), px((a.y + b.y) / 2)), (px(0.42), px(abs(a.y - b.y) / 2 + 0.33)), 0, 0, 360, 0.6, -1)

    return _light(albedo, height, seed)


def _light(albedo: np.ndarray, height: np.ndarray, seed: int) -> np.ndarray:
    height = cv2.GaussianBlur(height, (0, 0), 1.2)
    gx = cv2.Sobel(height, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(height, cv2.CV_32F, 0, 1, ksize=3)
    norm = np.sqrt(gx * gx + gy * gy + 1)
    nx, ny, nz = -gx / norm, -gy / norm, 1 / norm
    out = np.zeros_like(albedo, np.float32)
    # OpenCV order is BGR: blue is the low-angle ring, red the top ring.
    for ch, elevation in zip((2, 1, 0), (75, 45, 15)):
        el = math.radians(elevation)
        lx, ly, lz = math.cos(el) * 0.7, math.cos(el) * 0.7, math.sin(el)
        shade = np.clip(nx * lx + ny * ly + nz * lz, 0, 1) / max(lz, 0.35)
        out[..., ch] = albedo[..., ch].astype(np.float32) * (0.55 + 0.5 * np.clip(shade, 0, 1.6))
    noise = np.random.default_rng(seed).normal(0, 2.0, out.shape)
    return np.clip(out + noise, 0, 255).astype(np.uint8)


def warp_like_fixture(image: np.ndarray, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Apply the small rotation and shift a board gets when seated on a conveyor."""
    rng = np.random.default_rng(seed)
    h, w = image.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), float(rng.uniform(-1.2, 1.2)), 1.0)
    m[:, 2] += rng.uniform(-14, 14, 2)
    return cv2.warpAffine(image, m, (w, h), flags=cv2.INTER_LINEAR, borderValue=(20, 20, 20)), m


def render_xray(part: Part, void_pct: float, seed: int, size: int = 900) -> tuple[np.ndarray, float]:
    """Top-down X-ray slice of the thermal pad. Solder is dark and voids are bright."""
    rng = np.random.default_rng(seed)
    image = np.full((size, size), 205, np.uint8)
    margin = int(size * 0.12)
    pad = np.zeros((size, size), np.uint8)
    cv2.rectangle(pad, (margin, margin), (size - margin, size - margin), 255, -1)
    pad_area = int((pad > 0).sum())
    voids = np.zeros((size, size), np.uint8)
    target = pad_area * void_pct / 100
    radius_hi = max(12, int(size * 0.016 * max(void_pct, 6) ** 0.5))
    guard = 0
    while (voids > 0).sum() < target and guard < 5000:
        guard += 1
        remaining = target - (voids > 0).sum()
        radius = int(min(rng.integers(8, radius_hi + 1), max(3, math.sqrt(remaining / math.pi))))
        lo, hi = margin + radius + 6, size - margin - radius - 6
        centre = (int(rng.integers(lo, hi)), int(rng.integers(lo, hi)))
        trial = np.zeros_like(voids)
        cv2.circle(trial, centre, radius + 4, 255, -1)
        if (trial & voids).any():
            continue
        cv2.circle(voids, centre, radius, 255, -1)
    image[pad > 0] = 62
    image[voids > 0] = 168
    noise = np.random.default_rng(seed + 1).normal(0, 3, image.shape)
    image = np.clip(image.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    actual = 100 * float((voids > 0).sum()) / pad_area
    return image, actual


def defect_bbox(parts: list[Part], defect: dict) -> list[int]:
    part = next(p for p in parts if p.designator == defect["designator"])
    if defect["class"] == "solder_bridge":
        a, b = [next(p for p in part.pads if p.pin == n) for n in defect["pins"]]
        # Same ellipse axes as render_scene, so the label covers the blob actually drawn.
        cx, cy = (a.x + b.x) / 2, (a.y + b.y) / 2
        rx, ry = 0.42, abs(a.y - b.y) / 2 + 0.33
        return [px(cx - rx), px(cy - ry), px(cx + rx), px(cy + ry)]
    pads = part.pads
    x0 = min(p.x - p.w / 2 for p in pads)
    y0 = min(p.y - p.h / 2 for p in pads)
    x1 = max(p.x + p.w / 2 for p in pads)
    y1 = max(p.y + p.h / 2 for p in pads)
    return [px(x0), px(y0), px(x1), px(y1)]


CASES = [
    {"id": "case_01_solder_bridge_u12", "title": "Solder bridge on U12", "serial": "EMS-2411-0001",
     "defects": [{"class": "solder_bridge", "designator": "U12", "pins": [5, 6]}], "void_pct": 7.5},
    {"id": "case_02_tombstone_c14", "title": "Tombstoned capacitor C14", "serial": "EMS-2411-0002",
     "defects": [{"class": "tombstoning", "designator": "C14"}], "void_pct": 9.0},
    {"id": "case_03_missing_r08", "title": "Missing resistor R08", "serial": "EMS-2411-0003",
     "defects": [{"class": "missing_component", "designator": "R08"}], "void_pct": 6.5},
    {"id": "case_04_reversed_d3", "title": "Reversed diode D3", "serial": "EMS-2411-0004",
     "defects": [{"class": "polarity_error", "designator": "D3"}], "void_pct": 8.0},
    {"id": "case_05_bga1_voiding", "title": "BGA1 thermal pad 32% voiding", "serial": "EMS-2411-0005",
     "defects": [], "void_pct": 32.0},
    {"id": "case_06_clean_pass", "title": "Clean board (control)", "serial": "EMS-2411-0006",
     "defects": [], "void_pct": 7.0},
]


def write_bom(parts: list[Part], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Package", "Pin_Count", "X_mm", "Y_mm", "Rotation", "Width_mm", "Height_mm"])
        for p in parts:
            w.writerow([p.designator, p.package, p.pin_count, p.x, p.y, p.rotation, p.w, p.h])


def write_gerber(parts: list[Part], path: Path) -> None:
    """RS-274X with KiCad-style X2 pad attributes. Gerber Y points up, so it is flipped here."""
    apertures: dict[tuple[float, float], int] = {}
    body: list[str] = []
    for part in parts:
        for pad in part.pads:
            key = (round(pad.w, 4), round(pad.h, 4))
            code = apertures.setdefault(key, 10 + len(apertures))
            body += [
                f"%TO.N,{pad.net}*%",
                f"%TO.P,{pad.designator},{pad.pin},{pad.net}*%",
                f"%TO.C,{pad.designator}*%",
                f"D{code}*",
                f"X{round(pad.x * 1e6)}Y{round((BOARD_H_MM - pad.y) * 1e6)}D03*",
                "%TD*%",
            ]
    head = ["%TF.FileFunction,Copper,L1,Top*%", "%FSLAX46Y46*%", "%MOMM*%"]
    head += [f"%ADD{code}R,{w}X{h}*%" for (w, h), code in apertures.items()]
    path.write_text("\n".join(head + body + ["M02*", ""]), encoding="utf-8")


def generate(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    parts = build_board()
    cv2.imwrite(str(out / "golden.jpg"), render_scene(parts, seed=1), [cv2.IMWRITE_JPEG_QUALITY, 93])
    write_bom(parts, out / "bom_centroids.csv")
    write_gerber(parts, out / "top_copper.gbr")
    (out / "board_meta.json").write_text(json.dumps(
        {"board_w_mm": BOARD_W_MM, "board_h_mm": BOARD_H_MM, "px_per_mm": PX_PER_MM, "bga_designator": "BGA1"}, indent=2), encoding="utf-8")
    bga = next(p for p in parts if p.designator == "BGA1")
    for i, case in enumerate(CASES):
        folder = out / case["id"]
        folder.mkdir(exist_ok=True)
        test, _ = warp_like_fixture(render_scene(parts, case["defects"], seed=100 + i), seed=200 + i)
        cv2.imwrite(str(folder / "test.jpg"), test, [cv2.IMWRITE_JPEG_QUALITY, 93])
        xray, void_actual = render_xray(bga, case["void_pct"], seed=300 + i)
        cv2.imwrite(str(folder / "xray.png"), xray)
        truth = {**case, "void_pct": round(void_actual, 2),
                 "defects": [{**d, "bbox": defect_bbox(parts, d)} for d in case["defects"]]}
        (folder / "truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[2] / "backend" / "data" / "sample_pcbs")
    args = parser.parse_args()
    generate(args.out)
    print(f"Wrote golden, BOM, Gerber and {len(CASES)} cases to {args.out}")
