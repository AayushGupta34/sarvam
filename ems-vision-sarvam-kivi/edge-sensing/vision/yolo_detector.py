"""YOLOv11 wrapper. Inactive when ultralytics or the weights file is not available."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .schemas import YOLO_CLASSES, Defect

DEFAULT_WEIGHTS = Path(__file__).resolve().parents[1] / "weights" / "pcb_yolo11n.pt"


class YoloDetector:
    def __init__(self, weights: Path = DEFAULT_WEIGHTS, conf: float = 0.35, imgsz: int = 960) -> None:
        self.conf, self.imgsz = conf, imgsz
        self.model = None
        if not Path(weights).exists():
            return
        try:
            from ultralytics import YOLO
        except ImportError:
            return
        self.model = YOLO(str(weights))

    @property
    def active(self) -> bool:
        return self.model is not None

    def detect(self, image: np.ndarray) -> list[Defect]:
        if self.model is None:
            return []
        result = self.model.predict(image, conf=self.conf, imgsz=self.imgsz, verbose=False)[0]
        out = []
        for xyxy, cls, score in zip(result.boxes.xyxy.tolist(), result.boxes.cls.tolist(), result.boxes.conf.tolist()):
            name = YOLO_CLASSES[int(cls)]
            out.append(Defect(defect_class=name, bbox=tuple(int(v) for v in xyxy), score=float(score), source="yolo"))  # type: ignore[arg-type]
        return out
