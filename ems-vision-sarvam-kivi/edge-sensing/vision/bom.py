"""Map image regions to components, pins and nets using the BOM and Gerber layer."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from shapely.geometry import box
from shapely.strtree import STRtree

from .schemas import BomHit

_FORMAT = re.compile(r"%FSLAX(\d)(\d)Y(\d)(\d)\*%")
_APERTURE = re.compile(r"%ADD(\d+)([RC]),([\d.]+)(?:X([\d.]+))?\*%")
_PAD_ATTR = re.compile(r"%TO\.P,([^,*]+),([^,*]+)(?:,([^*]*))?\*%")
_NET_ATTR = re.compile(r"%TO\.N,([^*]*)\*%")
_FLASH = re.compile(r"(?:X(-?\d+))?(?:Y(-?\d+))?D03\*")
_SELECT = re.compile(r"^(?:G54)?D(\d{2,})\*$")


@dataclass(frozen=True)
class GerberPad:
    designator: str
    pin: str
    net: str
    x_mm: float
    y_mm: float
    w_mm: float
    h_mm: float


def parse_gerber(path: Path, board_h_mm: float) -> list[GerberPad]:
    """Read flashed pads carrying X2 attributes. Returned Y is image-style, pointing down."""
    decimals = 6
    apertures: dict[int, tuple[float, float]] = {}
    current: tuple[float, float] | None = None
    attr: tuple[str, str] | None = None
    net = ""
    x = y = 0
    pads: list[GerberPad] = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if m := _FORMAT.fullmatch(line):
            decimals = int(m.group(2))
        elif m := _APERTURE.fullmatch(line):
            w = float(m.group(3))
            apertures[int(m.group(1))] = (w, float(m.group(4) or w))
        elif m := _PAD_ATTR.fullmatch(line):
            attr = (m.group(1), m.group(2))
            net = m.group(3) or net
        elif m := _NET_ATTR.fullmatch(line):
            net = m.group(1)
        elif line.startswith("%TD"):
            attr, net = None, ""
        elif m := _SELECT.fullmatch(line):
            current = apertures.get(int(m.group(1)))
        elif m := _FLASH.fullmatch(line):
            x = int(m.group(1)) if m.group(1) else x
            y = int(m.group(2)) if m.group(2) else y
            if attr and current:
                scale = 10 ** decimals
                pads.append(GerberPad(attr[0], attr[1], net, x / scale, board_h_mm - y / scale, *current))
    return pads


@dataclass(frozen=True)
class Component:
    designator: str
    package: str
    pin_count: int
    x_mm: float
    y_mm: float
    rotation: float
    w_mm: float
    h_mm: float


def load_bom(path: Path) -> list[Component]:
    with Path(path).open(newline="", encoding="utf-8") as f:
        return [
            Component(r["Designator"], r["Package"], int(r["Pin_Count"]), float(r["X_mm"]), float(r["Y_mm"]),
                      float(r["Rotation"]), float(r["Width_mm"]), float(r["Height_mm"]))
            for r in csv.DictReader(f)
        ]


@dataclass
class BomMapper:
    components: list[Component]
    pads: list[GerberPad]
    px_per_mm: float
    courtyard_mm: float = 0.6
    pads_by_ref: dict[str, list[GerberPad]] = field(init=False)

    def __post_init__(self) -> None:
        self.pads_by_ref = {}
        for pad in self.pads:
            self.pads_by_ref.setdefault(pad.designator, []).append(pad)
        self._boxes = [self.courtyard(c) for c in self.components]
        self._tree = STRtree(self._boxes)

    def courtyard(self, c: Component):
        rects = [box(c.x_mm - c.w_mm / 2, c.y_mm - c.h_mm / 2, c.x_mm + c.w_mm / 2, c.y_mm + c.h_mm / 2)]
        rects += [_pad_box(p) for p in self.pads_by_ref.get(c.designator, [])]
        x0 = min(r.bounds[0] for r in rects) - self.courtyard_mm
        y0 = min(r.bounds[1] for r in rects) - self.courtyard_mm
        x1 = max(r.bounds[2] for r in rects) + self.courtyard_mm
        y1 = max(r.bounds[3] for r in rects) + self.courtyard_mm
        return box(x0, y0, x1, y1)

    def component(self, designator: str) -> Component:
        return next(c for c in self.components if c.designator == designator)

    def to_mm(self, bbox: tuple[int, int, int, int]) -> tuple[float, float, float, float]:
        return tuple(v / self.px_per_mm for v in bbox)  # type: ignore[return-value]

    def to_px(self, shape) -> tuple[int, int, int, int]:
        x0, y0, x1, y1 = shape.bounds
        return tuple(int(round(v * self.px_per_mm)) for v in (x0, y0, x1, y1))  # type: ignore[return-value]

    def footprint_px(self, designator: str) -> tuple[int, int, int, int]:
        boxes = [_pad_box(p).bounds for p in self.pads_by_ref[designator]]
        x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
        return self.to_px(box(x0, y0, x1, y1))

    def locate(self, bbox: tuple[int, int, int, int]) -> BomHit | None:
        """Return the component with the largest overlap, or None for bare board."""
        region = box(*self.to_mm(bbox))
        best, best_area = None, 0.0
        for i in self._tree.query(region):
            area = region.intersection(self._boxes[int(i)]).area
            if area > best_area:
                best, best_area = self.components[int(i)], area
        if best is None:
            return None
        hit = sorted(
            # A pad counts only when mostly covered, so a box grazing a neighbour does not name its pin.
            (p for p in self.pads_by_ref.get(best.designator, [])
             if region.intersection(_pad_box(p)).area >= 0.5 * _pad_box(p).area),
            key=lambda p: int(p.pin) if p.pin.isdigit() else 0,
        )
        return BomHit(
            designator=best.designator,
            package=best.package,
            pins=[int(p.pin) for p in hit if p.pin.isdigit()],
            nets=list(dict.fromkeys(p.net for p in hit)),
        )


def _pad_box(p: GerberPad):
    return box(p.x_mm - p.w_mm / 2, p.y_mm - p.h_mm / 2, p.x_mm + p.w_mm / 2, p.y_mm + p.h_mm / 2)
