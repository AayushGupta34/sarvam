"""Frame sources for the edge agent. All return BGR arrays from grab()."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

import cv2
import numpy as np


class Camera(Protocol):
    def grab(self) -> np.ndarray | None: ...


class FolderCamera:
    """Loops over images in a folder, standing in for a GigE camera on a dev machine."""

    def __init__(self, folder: Path) -> None:
        self.files = sorted(p for p in Path(folder).rglob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
        if not self.files:
            raise FileNotFoundError(f"no images in {folder}")
        self.index = 0

    def grab(self) -> np.ndarray | None:
        image = cv2.imread(str(self.files[self.index % len(self.files)]))
        self.index += 1
        return image


class OpenCvCamera:
    """USB device index or RTSP URL."""

    def __init__(self, source: int | str) -> None:
        self.capture = cv2.VideoCapture(source)
        if not self.capture.isOpened():
            raise ConnectionError(f"could not open {source}")

    def grab(self) -> np.ndarray | None:
        ok, frame = self.capture.read()
        return frame if ok else None


class GigEVisionCamera:
    """GenICam camera through Harvesters. Needs `pip install harvesters` and the vendor's .cti producer."""

    def __init__(self, cti_file: str, device_index: int = 0) -> None:
        from harvesters.core import Harvester

        self.harvester = Harvester()
        self.harvester.add_file(cti_file)
        self.harvester.update()
        self.acquirer = self.harvester.create(device_index)
        self.acquirer.start()

    def grab(self) -> np.ndarray | None:
        with self.acquirer.fetch(timeout=5) as buffer:
            component = buffer.payload.components[0]
            frame = component.data.reshape(component.height, component.width, -1).copy()
        return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR) if frame.shape[2] == 3 else cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
