"""Align a test frame to the golden frame with ORB features and a RANSAC homography."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


class RegistrationError(RuntimeError):
    pass


@dataclass
class Aligned:
    image: np.ndarray
    valid: np.ndarray  # 255 where warped pixels came from inside the test frame
    homography: np.ndarray
    inliers: int
    reprojection_error_px: float


def register(golden: np.ndarray, test: np.ndarray, features: int = 6000, min_inliers: int = 25) -> Aligned:
    orb = cv2.ORB_create(nfeatures=features, fastThreshold=10)
    kp_g, des_g = orb.detectAndCompute(cv2.cvtColor(golden, cv2.COLOR_BGR2GRAY), None)
    kp_t, des_t = orb.detectAndCompute(cv2.cvtColor(test, cv2.COLOR_BGR2GRAY), None)
    if des_g is None or des_t is None:
        raise RegistrationError("no ORB features found")

    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(des_t, des_g, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
    if len(good) < min_inliers:
        raise RegistrationError(f"only {len(good)} feature matches")

    src = np.float32([kp_t[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp_g[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    homography, mask = cv2.findHomography(src, dst, cv2.RANSAC, 2.5)
    if homography is None or int(mask.sum()) < min_inliers:
        raise RegistrationError("homography rejected by RANSAC")

    keep = mask.ravel().astype(bool)
    projected = cv2.perspectiveTransform(src[keep], homography)
    error = float(np.linalg.norm(projected - dst[keep], axis=2).mean())

    h, w = golden.shape[:2]
    warped = cv2.warpPerspective(test, homography, (w, h), flags=cv2.INTER_LINEAR)
    valid = cv2.warpPerspective(np.full(test.shape[:2], 255, np.uint8), homography, (w, h), flags=cv2.INTER_NEAREST)
    return Aligned(warped, valid, homography, int(mask.sum()), error)
