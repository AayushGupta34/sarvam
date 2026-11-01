"""BGA void measurement from an X-ray slice, using OpenCV contour areas."""
from __future__ import annotations

import cv2
import numpy as np

from .schemas import VoidReport

VOID_LIMIT_PCT = 25.0


def measure_voids(xray: np.ndarray, designator: str = "BGA1", limit_pct: float = VOID_LIMIT_PCT) -> VoidReport:
    """Void % = sum of hole contour areas / outer solder contour area.

    Solder absorbs X-rays and images dark, so voids are bright holes in a dark pad.
    """
    gray = cv2.cvtColor(xray, cv2.COLOR_BGR2GRAY) if xray.ndim == 3 else xray
    gray = cv2.medianBlur(gray, 5)
    _, solder = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, hierarchy = cv2.findContours(solder, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if hierarchy is None:
        raise ValueError("no solder region found in X-ray")
    tree = hierarchy[0]
    outers = [i for i in range(len(contours)) if tree[i][3] == -1]
    pad = max(outers, key=lambda i: cv2.contourArea(contours[i]))
    # Contours run through boundary pixel centres, and a hole's contour runs through the solder
    # around it. Half the perimeter corrects both to true pixel area, in opposite directions.
    pad_area = cv2.contourArea(contours[pad]) + cv2.arcLength(contours[pad], True) / 2 + 1
    if pad_area <= 1:
        raise ValueError("solder region has no area")

    holes = [contours[i] for i in range(len(contours)) if tree[i][3] == pad]
    void_area = sum(max(0.0, cv2.contourArea(h) - cv2.arcLength(h, True) / 2 + 1) for h in holes)
    pct = 100 * void_area / pad_area
    return VoidReport(designator=designator, void_pct=round(pct, 2), limit_pct=limit_pct,
                      failed=pct > limit_pct, void_count=len(holes))
