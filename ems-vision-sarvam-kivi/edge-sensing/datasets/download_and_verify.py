"""Fetch PCB datasets and check them against their published formats.

Usage:
  python edge-sensing/datasets/download_and_verify.py deeppcb
  python edge-sensing/datasets/download_and_verify.py visa
  python edge-sensing/datasets/download_and_verify.py pku --path D:/PCB_DATASET
  python edge-sensing/datasets/download_and_verify.py roboflow --path D:/solder-yolo-export

PKU-Market-PCB and Roboflow exports need a manual download, so they are verified from --path.
Archives are only extracted, never executed.
"""
from __future__ import annotations

import argparse
import shutil
import tarfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

RAW = Path(__file__).resolve().parent / "raw"
DEEPPCB_URL = "https://codeload.github.com/tangsanli5201/DeepPCB/zip/refs/heads/master"
VISA_URL = "https://amazon-visual-anomaly.s3.us-west-2.amazonaws.com/VisA_20220922.tar"
DEEPPCB_CLASSES = {1: "open", 2: "short", 3: "mousebite", 4: "spur", 5: "copper", 6: "pin-hole"}
PKU_CLASSES = {"missing_hole", "mouse_bite", "open_circuit", "short", "spur", "spurious_copper"}
SOLDER_CLASSES = {"solder_bridge", "insufficient_solder", "excess_solder", "cold_joint",
                  "tombstoning", "missing_component", "polarity_error"}


@dataclass(frozen=True)
class Sample:
    image: Path
    template: Path | None
    boxes: tuple[tuple[int, int, int, int, str], ...]  # x0, y0, x1, y1, class


def _download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest
    partial = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "ems-vision-dataset-fetcher"})
    with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as out:
        shutil.copyfileobj(response, out, 1 << 20)
    partial.replace(dest)
    return dest


def fetch_deeppcb(root: Path = RAW / "deeppcb") -> Path:
    archive = _download(DEEPPCB_URL, RAW / "_archives" / "deeppcb.zip")
    with zipfile.ZipFile(archive) as z:
        members = [m for m in z.namelist() if "/PCBData/" in m and m.lower().endswith((".jpg", ".txt"))]
        for name in members:
            target = (root / name.split("/PCBData/", 1)[1]).resolve()
            if not target.is_relative_to(root.resolve()):
                raise ValueError(f"unsafe path in archive: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(name))
    return root


def fetch_visa(root: Path = RAW / "visa") -> Path:
    archive = _download(VISA_URL, RAW / "_archives" / "visa.tar")
    root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        tar.extractall(root, members=[m for m in tar.getmembers() if m.name.lstrip("./").startswith(("pcb", "split_csv"))], filter="data")
    return root


def iter_deeppcb(root: Path) -> Iterator[Sample]:
    for ann in sorted(root.rglob("*.txt")):
        if ann.parent.name.endswith("_not") and ann.stem.isdigit() or ann.stem.split("_")[0].isdigit() and "_not" in ann.parent.name:
            stem = ann.stem.split("_")[0]
            group = ann.parent.parent
            folder = next((p for p in group.iterdir() if p.is_dir() and not p.name.endswith("_not")), None)
            if folder is None:
                continue
            test, temp = folder / f"{stem}_test.jpg", folder / f"{stem}_temp.jpg"
            if not (test.exists() and temp.exists()):
                continue
            boxes = []
            for line in ann.read_text(encoding="utf-8").splitlines():
                parts = line.replace(",", " ").split()
                if len(parts) == 5:
                    x0, y0, x1, y1, cls = map(int, parts)
                    boxes.append((x0, y0, x1, y1, DEEPPCB_CLASSES[cls]))
            yield Sample(test, temp, tuple(boxes))


def iter_pku(root: Path) -> Iterator[Sample]:
    for xml in sorted(root.rglob("*.xml")):
        tree = ET.parse(xml).getroot()
        boxes = []
        for obj in tree.iter("object"):
            b = obj.find("bndbox")
            boxes.append((int(b.findtext("xmin")), int(b.findtext("ymin")), int(b.findtext("xmax")), int(b.findtext("ymax")), obj.findtext("name").lower()))
        name = tree.findtext("filename") or f"{xml.stem}.jpg"
        hits = list(root.rglob(name if "." in name else f"{name}.jpg"))
        if hits:
            yield Sample(hits[0], None, tuple(boxes))


def iter_yolo_export(root: Path, classes: list[str]) -> Iterator[Sample]:
    """Roboflow "YOLO" export: images/x.jpg with labels/x.txt in normalised cx cy w h."""
    import cv2

    for label in sorted(root.rglob("labels/*.txt")):
        image = next((p for ext in (".jpg", ".jpeg", ".png") if (p := label.parent.parent / "images" / f"{label.stem}{ext}").exists()), None)
        if image is None:
            continue
        h, w = cv2.imread(str(image)).shape[:2]
        boxes = []
        for line in label.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 5:
                c, cx, cy, bw, bh = int(parts[0]), *map(float, parts[1:])
                boxes.append((int((cx - bw / 2) * w), int((cy - bh / 2) * h), int((cx + bw / 2) * w), int((cy + bh / 2) * h), classes[c]))
        yield Sample(image, None, tuple(boxes))


def verify(samples: list[Sample], allowed: set[str], minimum: int = 1) -> dict:
    if len(samples) < minimum:
        raise ValueError(f"expected at least {minimum} samples, found {len(samples)}")
    counts: dict[str, int] = {}
    for s in samples:
        if not s.image.exists():
            raise ValueError(f"missing image {s.image}")
        for x0, y0, x1, y1, cls in s.boxes:
            if cls not in allowed:
                raise ValueError(f"{s.image.name}: unknown class {cls}")
            if x1 <= x0 or y1 <= y0:
                raise ValueError(f"{s.image.name}: empty box")
            counts[cls] = counts.get(cls, 0) + 1
    return {"samples": len(samples), "boxes_by_class": counts}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dataset", choices=["deeppcb", "visa", "pku", "roboflow"])
    parser.add_argument("--path", type=Path)
    args = parser.parse_args()
    if args.dataset == "deeppcb":
        print(verify(list(iter_deeppcb(args.path or fetch_deeppcb())), set(DEEPPCB_CLASSES.values()), 1500))
    elif args.dataset == "visa":
        root = args.path or fetch_visa()
        print({p.name: sum(1 for _ in p.rglob("*.JPG")) for p in sorted(root.glob("pcb*"))})
    elif args.dataset == "pku":
        if args.path is None:
            parser.error("PKU-Market-PCB has no stable direct URL. Download it and pass --path")
        print(verify(list(iter_pku(args.path)), PKU_CLASSES))
    else:
        if args.path is None:
            parser.error("Export from Roboflow in YOLO format and pass --path")
        print(verify(list(iter_yolo_export(args.path, sorted(SOLDER_CLASSES))), SOLDER_CLASSES))


if __name__ == "__main__":
    main()
