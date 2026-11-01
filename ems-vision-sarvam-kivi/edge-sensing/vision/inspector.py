"""Two-stage inspection: detect and locate in code, then diagnose upstream cause."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .bom import BomMapper, load_bom, parse_gerber
from .registration import register
from .root_cause import LlmCall, diagnose
from .schemas import Defect, InspectionResult, Registration, VoidReport
from .template_diff import detect
from .xray import measure_voids
from .yolo_detector import YoloDetector


@dataclass
class BoardContext:
    golden: np.ndarray
    mapper: BomMapper
    bga_designator: str

    @classmethod
    def load(cls, folder: Path) -> "BoardContext":
        folder = Path(folder)
        meta = json.loads((folder / "board_meta.json").read_text(encoding="utf-8"))
        golden = cv2.imread(str(folder / "golden.jpg"))
        if golden is None:
            raise FileNotFoundError(folder / "golden.jpg")
        pads = parse_gerber(folder / "top_copper.gbr", meta["board_h_mm"])
        mapper = BomMapper(load_bom(folder / "bom_centroids.csv"), pads, meta["px_per_mm"])
        return cls(golden, mapper, meta["bga_designator"])


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def merge_yolo(template: list[Defect], yolo: list[Defect], mapper: BomMapper) -> list[Defect]:
    """Keep template boxes and add YOLO boxes on components the template did not flag."""
    merged = list(template)
    flagged = {d.bom.designator for d in template if d.bom}
    for det in yolo:
        hit = mapper.locate(det.bbox)
        if any(_iou(det.bbox, t.bbox) > 0.3 for t in template):
            continue
        if hit and hit.designator in flagged:
            continue
        merged.append(det.model_copy(update={"bom": hit}))
    return merged


class Inspector:
    def __init__(self, context: BoardContext, yolo: YoloDetector | None = None) -> None:
        self.context = context
        self.yolo = yolo or YoloDetector()

    def inspect(self, test: np.ndarray, xray: np.ndarray | None = None, llm: LlmCall | None = None,
                recurrence: dict[str, int] | None = None) -> InspectionResult:
        start = time.perf_counter()
        ctx, recurrence = self.context, recurrence or {}
        aligned = register(ctx.golden, test)
        defects = detect(ctx.golden, aligned.image, aligned.valid, ctx.mapper)
        if self.yolo.active:
            defects = merge_yolo(defects, self.yolo.detect(aligned.image), ctx.mapper)

        report: VoidReport | None = None
        if xray is not None:
            report = measure_voids(xray, ctx.bga_designator)
            if report.failed:
                c = ctx.mapper.component(ctx.bga_designator)
                courtyard = ctx.mapper.courtyard(c)
                defects.append(Defect(defect_class="bga_voiding", bbox=ctx.mapper.to_px(courtyard),
                                      score=1.0, source="xray", bom=ctx.mapper.locate(ctx.mapper.to_px(courtyard))))
                defects[-1].bom.pins = []  # type: ignore[union-attr]
                defects[-1].bom.nets = []  # type: ignore[union-attr]

        verdict = "FAIL" if defects else "PASS"
        latency = (time.perf_counter() - start) * 1000
        diagnoses = [
            diagnose(d, llm, recurrence.get(d.bom.designator if d.bom else "", 0),
                     report.void_pct if report else None, report.limit_pct if report else 25.0)
            for d in defects
        ]
        return InspectionResult(
            verdict=verdict, defects=defects, diagnoses=diagnoses, void_report=report,
            registration=Registration(inliers=aligned.inliers, reprojection_error_px=round(aligned.reprojection_error_px, 3),
                                      homography=aligned.homography.tolist()),
            latency_ms=round(latency, 1), yolo_active=self.yolo.active,
        )
