"""Golden-template subtraction and rule-based classification of each changed region."""
from __future__ import annotations

import cv2
import numpy as np

from .bom import BomMapper, Component
from .schemas import BomHit, Defect

DIFF_THRESHOLD = 38
MIN_REGION_PX = 60
ASYMMETRY_LIMIT = 30
POLARISED = ("SOD", "DO-", "SMA", "SMB")
TWO_TERMINAL = ("0201", "0402", "0603", "0805", "1206", "SOD", "SMA", "SMB")


def changed_regions(golden: np.ndarray, aligned: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, list[tuple[int, int, int, int]]]:
    diff = cv2.absdiff(cv2.GaussianBlur(golden, (5, 5), 0), cv2.GaussianBlur(aligned, (5, 5), 0)).max(axis=2)
    _, mask = cv2.threshold(diff, DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)
    mask = cv2.bitwise_and(mask, cv2.erode(valid, np.ones((15, 15), np.uint8)))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    boxes = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if area >= MIN_REGION_PX:
            boxes.append((int(x), int(y), int(x + w), int(y + h)))
    return mask, boxes


def binary_regions(golden: np.ndarray, test: np.ndarray, tolerance_px: int = 3, pad_px: int = 12,
                   min_area: int = 6) -> list[tuple[int, int, int, int]]:
    """Bare-board comparison for binarised images such as DeepPCB.

    Corrects the global shift, then flags copper missing or added beyond a tolerance band,
    so that edges a pixel or two out of place are not reported as defects.
    """
    g = cv2.cvtColor(golden, cv2.COLOR_BGR2GRAY)
    t = cv2.cvtColor(test, cv2.COLOR_BGR2GRAY)
    (dx, dy), _ = cv2.phaseCorrelate(g.astype(np.float32), t.astype(np.float32))
    shift = np.float32([[1, 0, -dx], [0, 1, -dy]])
    t = cv2.warpAffine(t, shift, t.shape[::-1], flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_REPLICATE)
    _, gb = cv2.threshold(g, 128, 255, cv2.THRESH_BINARY)
    _, tb = cv2.threshold(t, 128, 255, cv2.THRESH_BINARY)
    band = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * tolerance_px + 1, 2 * tolerance_px + 1))
    mask = cv2.bitwise_or(cv2.bitwise_and(tb, cv2.bitwise_not(cv2.dilate(gb, band))),
                          cv2.bitwise_and(gb, cv2.bitwise_not(cv2.dilate(tb, band))))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    h, w = g.shape
    boxes = []
    for i in range(1, count):
        x, y, bw, bh, area = stats[i]
        if area >= min_area:
            boxes.append((max(0, int(x) - pad_px), max(0, int(y) - pad_px),
                          min(w, int(x + bw) + pad_px), min(h, int(y + bh) + pad_px)))
    return boxes


def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    a = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32).ravel()
    b = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32).ravel()
    a -= a.mean()
    b -= b.mean()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(a @ b) / denom if denom else 0.0


def _body_crop(image: np.ndarray, c: Component, px_per_mm: float) -> np.ndarray:
    x0 = int((c.x_mm - c.w_mm / 2) * px_per_mm)
    y0 = int((c.y_mm - c.h_mm / 2) * px_per_mm)
    return image[y0:int(y0 + c.h_mm * px_per_mm), x0:int(x0 + c.w_mm * px_per_mm)]


def _pad_asymmetry(image: np.ndarray, hit: BomHit, mapper: BomMapper) -> float:
    """Mean colour difference between the footprint's two end pads, mirrored onto each other."""
    a, b = sorted(mapper.pads_by_ref[hit.designator], key=lambda p: (p.x_mm, p.y_mm))[:2]
    crops = []
    for pad in (a, b):
        x0 = int((pad.x_mm - pad.w_mm / 2) * mapper.px_per_mm)
        y0 = int((pad.y_mm - pad.h_mm / 2) * mapper.px_per_mm)
        crops.append(image[y0:int(y0 + pad.h_mm * mapper.px_per_mm), x0:int(x0 + pad.w_mm * mapper.px_per_mm)])
    return float(cv2.absdiff(crops[0], cv2.flip(crops[1], 1)).mean())


def classify_component(golden: np.ndarray, aligned: np.ndarray, hit: BomHit, mapper: BomMapper) -> tuple[str, float]:
    """Return (class, score) for a changed component.

    Score is the margin of the measurement that decided the class, not a calibrated probability.
    """
    c = mapper.component(hit.designator)
    g_body = _body_crop(golden, c, mapper.px_per_mm)
    t_body = _body_crop(aligned, c, mapper.px_per_mm)

    if c.package.startswith(POLARISED):
        same, flipped = _ncc(g_body, t_body), _ncc(g_body, cv2.rotate(t_body, cv2.ROTATE_180))
        if flipped - same > 0.25:
            return "polarity_error", min(1.0, flipped - same)

    if c.package.startswith(TWO_TERMINAL):
        kept = float((cv2.absdiff(g_body, t_body).max(axis=2) < 40).mean())
        if kept < 0.85:
            # With the body gone both pads match; a part standing on one end leaves them unequal.
            if _pad_asymmetry(aligned, hit, mapper) > ASYMMETRY_LIMIT:
                return "tombstoning", 1 - kept
            return "missing_component", 1 - kept

    if len(hit.pins) >= 2:
        return "solder_bridge", min(1.0, 0.6 + 0.1 * len(hit.pins))
    return "unclassified_anomaly", 0.5


def detect(golden: np.ndarray, aligned: np.ndarray, valid: np.ndarray, mapper: BomMapper) -> list[Defect]:
    _, boxes = changed_regions(golden, aligned, valid)
    grouped: dict[str, list[tuple[int, int, int, int]]] = {}
    defects: list[Defect] = []
    for bbox in boxes:
        hit = mapper.locate(bbox)
        if hit is None:
            defects.append(Defect(defect_class="unclassified_anomaly", bbox=bbox, score=0.5, source="template"))
        else:
            grouped.setdefault(hit.designator, []).append(bbox)
    for ref, parts in grouped.items():
        bbox = (min(b[0] for b in parts), min(b[1] for b in parts), max(b[2] for b in parts), max(b[3] for b in parts))
        hit = mapper.locate(bbox)
        assert hit is not None
        cls, score = classify_component(golden, aligned, hit, mapper)
        if cls in ("missing_component", "tombstoning", "polarity_error"):
            bbox = mapper.footprint_px(ref)  # the whole part is the defect, not just the changed pixels
        defects.append(Defect(defect_class=cls, bbox=bbox, score=score, source="template", bom=hit))
    return defects
