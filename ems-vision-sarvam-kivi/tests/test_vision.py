from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from datasets.generate_demo_samples import CASES, build_board, generate, render_xray
from vision.bom import parse_gerber
from vision.inspector import BoardContext, Inspector
from vision.schemas import Defect
from vision.root_cause import diagnose
from vision.xray import measure_voids
from vision.yolo_detector import YoloDetector


@pytest.fixture(scope="module")
def samples(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("samples")
    generate(out)
    return out


@pytest.fixture(scope="module")
def inspector(samples) -> Inspector:
    return Inspector(BoardContext.load(samples), yolo=YoloDetector(weights=Path("does-not-exist.pt")))


def run_case(samples: Path, inspector: Inspector, case_id: str):
    folder = samples / case_id
    truth = json.loads((folder / "truth.json").read_text(encoding="utf-8"))
    return truth, inspector.inspect(cv2.imread(str(folder / "test.jpg")), cv2.imread(str(folder / "xray.png"), cv2.IMREAD_GRAYSCALE))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_each_case_finds_exactly_the_expected_defect(samples, inspector, case):
    truth, result = run_case(samples, inspector, case["id"])
    found = sorted((d.defect_class, d.bom.designator if d.bom else None) for d in result.defects)
    expected = sorted((d["class"], d["designator"]) for d in truth["defects"])
    if truth["void_pct"] > 25:
        expected = sorted(expected + [("bga_voiding", "BGA1")])
    assert found == expected
    assert result.verdict == ("FAIL" if expected else "PASS")


def test_bridge_maps_to_pins_and_nets(samples, inspector):
    _, result = run_case(samples, inspector, "case_01_solder_bridge_u12")
    bom = result.defects[0].bom
    assert bom.designator == "U12" and bom.package == "QFN-48"
    assert bom.pins == [5, 6]
    assert bom.nets == ["SPI_MISO", "I2C_SDA"]


def test_gerber_round_trip_matches_layout(samples):
    pads = parse_gerber(samples / "top_copper.gbr", 60.0)
    source = {(p.designator, str(p.pin)): p for part in build_board() for p in part.pads}
    assert len(pads) == len(source)
    for pad in pads:
        want = source[(pad.designator, pad.pin)]
        assert pad.net == want.net
        assert pad.x_mm == pytest.approx(want.x)
        assert pad.y_mm == pytest.approx(want.y)


@pytest.mark.parametrize("target", [5.0, 18.0, 25.0, 32.0, 45.0])
def test_void_percentage_tracks_ground_truth(target):
    part = next(p for p in build_board() if p.designator == "BGA1")
    image, actual = render_xray(part, target, seed=int(target))
    report = measure_voids(image)
    assert report.void_pct == pytest.approx(actual, abs=1.0)


def test_void_math_on_known_geometry():
    image = np.full((400, 400), 220, np.uint8)
    cv2.rectangle(image, (100, 100), (299, 299), 40, -1)  # 200 x 200 = 40000 px
    cv2.rectangle(image, (150, 150), (249, 249), 200, -1)  # 100 x 100 = 10000 px
    report = measure_voids(image)
    assert report.void_pct == pytest.approx(25.0, abs=0.6)
    assert report.void_count == 1


def test_void_limit_is_strictly_greater_than():
    image = np.full((400, 400), 220, np.uint8)
    cv2.rectangle(image, (100, 100), (299, 299), 40, -1)
    assert measure_voids(image).failed is False


def test_llm_cannot_add_a_fault_or_change_class():
    defect = Defect(defect_class="tombstoning", bbox=(0, 0, 10, 10), score=1, source="template")
    invented = {"process_stage": "x", "fault": "Aliens", "evidence": "y", "corrective_action": "z", "confidence": 0.9}
    assert diagnose(defect, lambda s, p: {"hypotheses": [invented]}).source == "heuristic"
    assert diagnose(defect, lambda s, p: {"nonsense": 1}).source == "heuristic"
    def boom(s, p):
        raise RuntimeError("down")
    assert diagnose(defect, boom).defect_class == "tombstoning"
