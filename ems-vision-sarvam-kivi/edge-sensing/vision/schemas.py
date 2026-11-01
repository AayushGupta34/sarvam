from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DefectClass = Literal[
    "solder_bridge", "insufficient_solder", "excess_solder", "cold_joint",
    "tombstoning", "missing_component", "polarity_error", "bga_voiding", "unclassified_anomaly",
]
YOLO_CLASSES: list[str] = [
    "solder_bridge", "insufficient_solder", "excess_solder", "cold_joint",
    "tombstoning", "missing_component", "polarity_error",
]


class BomHit(BaseModel):
    designator: str
    package: str
    pins: list[int] = Field(default_factory=list)
    nets: list[str] = Field(default_factory=list)


class Defect(BaseModel):
    defect_class: DefectClass
    bbox: tuple[int, int, int, int]  # x0, y0, x1, y1 in golden-frame pixels
    score: float = Field(ge=0, le=1)
    source: Literal["template", "yolo", "xray"]
    bom: BomHit | None = None


class Hypothesis(BaseModel):
    process_stage: str
    fault: str
    evidence: str
    corrective_action: str
    confidence: float = Field(ge=0, le=1)


class Diagnosis(BaseModel):
    designator: str | None
    defect_class: DefectClass
    hypotheses: list[Hypothesis]
    rework_instruction_en: str
    source: Literal["heuristic", "llm"] = "heuristic"


class VoidReport(BaseModel):
    designator: str
    void_pct: float
    limit_pct: float
    failed: bool
    void_count: int


class Registration(BaseModel):
    inliers: int
    reprojection_error_px: float
    homography: list[list[float]]  # test frame to golden frame


class InspectionResult(BaseModel):
    verdict: Literal["PASS", "FAIL"]
    defects: list[Defect]
    diagnoses: list[Diagnosis]
    void_report: VoidReport | None
    registration: Registration
    latency_ms: float
    yolo_active: bool
