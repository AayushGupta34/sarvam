"""Bridges the edge-sensing pipeline into the API: persistence and LLM enrichment."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
from sqlalchemy import func, select

from ..config.settings import REPO_DIR, settings
from ..db import Board, DefectLog, Inspection, SessionLocal
from .sarvam_service import SarvamError, sarvam

sys.path.insert(0, str(REPO_DIR / "edge-sensing"))

from vision.bom import BomMapper  # noqa: E402
from vision.inspector import BoardContext, Inspector  # noqa: E402
from vision.root_cause import LLM_SCHEMA, diagnose  # noqa: E402
from vision.schemas import Defect, Diagnosis, InspectionResult  # noqa: E402

SAMPLES = settings.data_dir / "sample_pcbs"
_inspector: Inspector | None = None


def sample_inspector() -> Inspector:
    global _inspector
    if _inspector is None:
        _inspector = Inspector(BoardContext.load(SAMPLES))
    return _inspector


def live_inspector(golden: np.ndarray) -> Inspector:
    """Inspector for a captured golden frame. With no BOM, regions are reported by position only."""
    mapper = BomMapper([], [], px_per_mm=1.0)
    return Inspector(BoardContext(golden, mapper, ""), sample_inspector().yolo)


def list_cases() -> list[dict]:
    cases = []
    for path in sorted(SAMPLES.glob("case_*/truth.json")):
        truth = json.loads(path.read_text(encoding="utf-8"))
        cases.append({"id": truth["id"], "title": truth["title"], "serial": truth["serial"]})
    return cases


def load_case(case_id: str) -> tuple[np.ndarray, np.ndarray, str]:
    folder = (SAMPLES / case_id).resolve()
    if not folder.is_relative_to(SAMPLES.resolve()) or not (folder / "truth.json").exists():
        raise FileNotFoundError(case_id)
    truth = json.loads((folder / "truth.json").read_text(encoding="utf-8"))
    return cv2.imread(str(folder / "test.jpg")), cv2.imread(str(folder / "xray.png"), cv2.IMREAD_GRAYSCALE), truth["serial"]


def recurrence_counts() -> dict[str, int]:
    with SessionLocal() as db:
        rows = db.execute(select(DefectLog.designator, func.count()).group_by(DefectLog.designator)).all()
    return {ref: count for ref, count in rows if ref}


def save(serial: str, source: str, result: InspectionResult) -> int:
    with SessionLocal() as db:
        if db.get(Board, serial) is None:
            db.add(Board(serial=serial))
            db.flush()
        row = Inspection(serial=serial, source=source, verdict=result.verdict, result=result.model_dump(mode="json"))
        row.defects = [DefectLog(defect_class=d.defect_class, designator=d.bom.designator if d.bom else None, score=d.score)
                       for d in result.defects]
        db.add(row)
        db.commit()
        return row.id


async def enrich(inspection_id: int, result: InspectionResult) -> list[Diagnosis] | None:
    """Run the Sarvam diagnostic agent for failed boards. The rule diagnosis already stands."""
    if sarvam.demo or result.verdict == "PASS":
        return None
    enriched: list[Diagnosis] = []
    for defect, base in zip(result.defects, result.diagnoses):
        enriched.append(await _ask(defect, base, result))
    if not any(d.source == "llm" for d in enriched):
        return None
    with SessionLocal() as db:
        row = db.get(Inspection, inspection_id)
        if row:
            row.result = {**row.result, "diagnoses": [d.model_dump(mode="json") for d in enriched]}
            db.commit()
    return enriched


async def _ask(defect: Defect, base: Diagnosis, result: InspectionResult) -> Diagnosis:
    reply: dict = {}

    async def fetch(system: str, payload: dict) -> None:
        nonlocal reply
        try:
            reply = await sarvam.chat_json(system, payload["payload"], LLM_SCHEMA, "root_cause")
        except SarvamError:
            reply = {}

    captured: list[tuple[str, dict]] = []
    diagnose(defect, lambda s, p: captured.append((s, p)) or {}, void_pct=result.void_report.void_pct if result.void_report else None)
    await fetch(*captured[0])
    if not reply:
        return base
    updated = diagnose(defect, lambda s, p: reply, void_pct=result.void_report.void_pct if result.void_report else None)
    return updated.model_copy(update={"rework_instruction_en": base.rework_instruction_en})
