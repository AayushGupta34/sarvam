"""Evaluate the pipeline and log metrics.

python edge-sensing/evaluate_pipeline.py                  synthetic cases and offline Kivi WER
python edge-sensing/evaluate_pipeline.py --deeppcb PATH   add real DeepPCB template/test pairs
python edge-sensing/evaluate_pipeline.py --live-kivi      add spoken WER through Sarvam (spends credits)
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "edge-sensing"), str(ROOT / "backend")]

from datasets.download_and_verify import iter_deeppcb  # noqa: E402
from vision.inspector import BoardContext, Inspector  # noqa: E402
from vision.template_diff import binary_regions  # noqa: E402

SAMPLES = ROOT / "backend" / "data" / "sample_pcbs"
IOU_THRESHOLDS = [round(0.5 + 0.05 * i, 2) for i in range(10)]

# Reference text, then what a recogniser without domain terms tends to produce.
KIVI_CORPUS = [
    ("U12 has a Solder Bridge on pin 5", "you twelve has a sodar bridge on pin 5"),
    ("C14 shows Tombstoning (IPC-A-610 Defect) after Reflow", "see fourteen shows tom stoning after re flow"),
    ("R402 is missing check the Stencil", "are four oh two is missing check the stensil"),
    ("apply Flux then use Desoldering Wick", "apply flucks then use de soldering wick"),
    ("QFN-48 on the AOI reject list", "cue eff en forty eight on the ay oh eye reject list"),
    ("BGA Void above limit on AXI", "b g a voiding above limit on ax ray"),
    ("D3 reversed check Squeegee and IPC-A-610", "dee three reversed check squeegy and ipc a six ten"),
    ("R08 missing near C19", "are oh eight missing near see nineteen"),
]


def iou(a, b) -> float:
    ix, iy = max(0, min(a[2], b[2]) - max(a[0], b[0])), max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def average_precision(preds: list[tuple[int, float, tuple]], truths: dict[int, list[tuple]], threshold: float) -> tuple[float, float, float]:
    """All-point interpolated AP over preds of (image, score, box). Returns (ap, precision, recall)."""
    total = sum(len(v) for v in truths.values())
    if not total:
        return 0.0, 0.0, 0.0
    used = {k: [False] * len(v) for k, v in truths.items()}
    tp = np.zeros(len(preds))
    for i, (image, _, box) in enumerate(sorted(preds, key=lambda p: -p[1])):
        scored = [(iou(box, t), j) for j, t in enumerate(truths.get(image, []))]
        best, j = max(scored, default=(0.0, -1))
        if best >= threshold and not used[image][j]:
            used[image][j] = True
            tp[i] = 1
    tps, fps = np.cumsum(tp), np.cumsum(1 - tp)
    recall = tps / total
    precision = tps / np.maximum(tps + fps, 1)
    envelope = np.maximum.accumulate(np.r_[precision, 0][::-1])[::-1]
    ap = float(np.sum(np.diff(np.r_[0, recall]) * envelope[:len(recall)])) if len(recall) else 0.0
    return ap, float(precision[-1]) if len(precision) else 0.0, float(recall[-1]) if len(recall) else 0.0


def summarise(preds, truths) -> dict:
    aps = [average_precision(preds, truths, t)[0] for t in IOU_THRESHOLDS]
    _, precision, recall = average_precision(preds, truths, 0.5)
    return {"mAP@50": round(aps[0], 4), "mAP@50-95": round(float(np.mean(aps)), 4),
            "precision@50": round(precision, 4), "recall@50": round(recall, 4)}


def evaluate_synthetic() -> dict:
    inspector = Inspector(BoardContext.load(SAMPLES))
    preds, truths, voids, latency = [], {}, [], []
    for i, path in enumerate(sorted(SAMPLES.glob("case_*/truth.json"))):
        truth = json.loads(path.read_text(encoding="utf-8"))
        test = cv2.imread(str(path.parent / "test.jpg"))
        xray = cv2.imread(str(path.parent / "xray.png"), cv2.IMREAD_GRAYSCALE)
        result = inspector.inspect(test, xray)
        latency.append(result.latency_ms)
        truths[i] = [tuple(d["bbox"]) for d in truth["defects"]]
        preds += [(i, d.score, d.bbox) for d in result.defects if d.source != "xray"]
        voids.append({"case": truth["id"], "true_pct": truth["void_pct"], "measured_pct": result.void_report.void_pct,
                      "failed_over_25pct": result.void_report.failed})
    return {"images": len(latency), **summarise(preds, truths), "latency_ms_mean": round(float(np.mean(latency)), 1), "bga_voids": voids}


def evaluate_deeppcb(root: Path, limit: int | None, split: str = "holdout", **params) -> dict:
    """Class-agnostic: template subtraction localises defects but does not name DeepPCB's classes.

    Every third image is the tuning split. Only the other two thirds are reported.
    """
    samples = [s for i, s in enumerate(iter_deeppcb(root)) if (i % 3 == 0) == (split == "tune")][:limit]
    preds, truths, latency = [], {}, []
    for i, sample in enumerate(samples):
        golden, test = cv2.imread(str(sample.template)), cv2.imread(str(sample.image))
        start = time.perf_counter()
        boxes = binary_regions(golden, test, **params)
        latency.append((time.perf_counter() - start) * 1000)
        truths[i] = [b[:4] for b in sample.boxes]
        preds += [(i, min(1.0, (b[2] - b[0]) * (b[3] - b[1]) / 4000), b) for b in boxes]
    return {"images": len(samples), "split": split, "note": "real data, class-agnostic localisation",
            **summarise(preds, truths), "latency_ms_mean": round(float(np.mean(latency)), 1)}


def wer(reference: str, hypothesis: str) -> float:
    r, h = reference.lower().split(), hypothesis.lower().split()
    row = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, row[0] = row[0], i
        for j, hw in enumerate(h, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (rw != hw))
    return row[-1] / max(len(r), 1)


def _space():
    from app.config.settings import settings
    from app.services.kivi_engine import KiviSpace

    return KiviSpace(settings.kivi_space)


def evaluate_kivi_offline() -> dict:
    from app.services.kivi_engine import apply_dictionary

    entries = _space().dictionary()
    before = [wer(r, h) for r, h in KIVI_CORPUS]
    after = [wer(r, apply_dictionary(h, entries)[0]) for r, h in KIVI_CORPUS]
    return {"note": "scripted recogniser errors, dictionary replacer only; not a spoken-audio measurement",
            "wer_without_dictionary": round(float(np.mean(before)), 4), "wer_with_dictionary": round(float(np.mean(after)), 4)}


async def evaluate_kivi_live() -> dict:
    """Speak the corpus with bulbul, then transcribe with and without keyterms."""
    from app.services.kivi_engine import apply_dictionary
    from app.services.sarvam_service import sarvam

    space = _space()
    entries, terms = space.dictionary(), space.keyterms()
    plain, keyed, full = [], [], []
    for reference, _ in KIVI_CORPUS:
        spoken = (await sarvam.speak(reference.split(" (")[0], "en-IN")).audio_base64
        audio = base64.b64decode(spoken)
        a = await sarvam.transcribe(audio, "a.wav", "audio/wav", "en-IN", "transcribe", None)
        b = await sarvam.transcribe(audio, "a.wav", "audio/wav", "en-IN", "transcribe", terms)
        plain.append(wer(reference, a["transcript"]))
        keyed.append(wer(reference, b["transcript"]))
        full.append(wer(reference, apply_dictionary(b["transcript"], entries)[0]))
    return {"note": "bulbul audio through saaras:v4, small corpus", "wer_no_keyterms": round(float(np.mean(plain)), 4),
            "wer_keyterms": round(float(np.mean(keyed)), 4), "wer_keyterms_plus_dictionary": round(float(np.mean(full)), 4)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--deeppcb", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--live-kivi", action="store_true")
    args = parser.parse_args()
    report = {"synthetic_vision": evaluate_synthetic(), "kivi_offline": evaluate_kivi_offline()}
    if args.deeppcb:
        report["deeppcb_vision"] = evaluate_deeppcb(args.deeppcb, args.limit)
    if args.live_kivi:
        report["kivi_live"] = asyncio.run(evaluate_kivi_live())
    print(json.dumps(report, indent=2))
    (ROOT / "edge-sensing" / "evaluation_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
