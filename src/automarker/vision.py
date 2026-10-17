"""ArUco detection, robust planar registration, and illumination correction."""

import logging

import cv2
import numpy as np

LOG = logging.getLogger(__name__)
DICTIONARIES = [f"DICT_{bits}X{bits}_1000" for bits in (4, 5, 6, 7)] + ["DICT_ARUCO_ORIGINAL"]


def normalize_light(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    # A broad closing estimates paper illumination without erasing thin writing.
    size = max(15, int(min(gray.shape) * 0.035) | 1)
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE,
                                 cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size)))
    corrected = cv2.divide(gray, np.maximum(background, 1), scale=255)
    return cv2.fastNlMeansDenoising(corrected, h=5, templateWindowSize=7, searchWindowSize=21)


def detect_markers(image: np.ndarray, dictionary: str) -> dict[int, np.ndarray]:
    if not dictionary.startswith("DICT_") or not hasattr(cv2.aruco, dictionary):
        raise ValueError(f"Unknown ArUco dictionary: {dictionary}")
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    params.adaptiveThreshWinSizeMax = 73
    detector = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dictionary)), params
    )
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    result = {}
    for stage in (gray, normalize_light(gray)):
        corners, ids, _ = detector.detectMarkers(stage)
        if ids is None:
            continue
        for marker_id, points in zip(ids.flatten(), corners):
            key = int(marker_id)
            # Repeated IDs in one detection are ambiguous, never choose one silently.
            if np.count_nonzero(ids == marker_id) > 1:
                raise ValueError(f"Duplicate ArUco ID {key}; page markers must have unique IDs")
            result.setdefault(key, points.reshape(4, 2))
    LOG.debug("%s detected IDs %s", dictionary, sorted(result))
    return result


def find_dictionary(image: np.ndarray, requested: str = "auto") -> tuple[str, dict]:
    names = DICTIONARIES if requested == "auto" else [requested]
    candidates = [(name, detect_markers(image, name)) for name in names]
    name, markers = max(candidates, key=lambda item: len(item[1]))
    if len(markers) < 2:
        raise ValueError("Reference needs at least two unique, well-separated ArUco tags")
    LOG.info("Using %s, reference marker IDs %s", name, sorted(markers))
    return name, markers


def marker_overlay(image: np.ndarray, markers: dict) -> np.ndarray:
    out = image.copy()
    if markers:
        ids = np.array(list(markers), dtype=np.int32).reshape(-1, 1)
        corners = [np.array(v, dtype=np.float32).reshape(1, 4, 2) for v in markers.values()]
        cv2.aruco.drawDetectedMarkers(out, corners, ids)
    return out


def calibrate_markers(reference: np.ndarray, capture: np.ndarray,
                      dictionary: str = "auto") -> tuple[str, dict, np.ndarray, dict]:
    """Locate tags relative to an untagged PDF using printed content, once per template."""
    name, observed = find_dictionary(capture, dictionary)
    sift = cv2.SIFT_create(nfeatures=8000)
    ref_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    cap_gray = cv2.cvtColor(capture, cv2.COLOR_BGR2GRAY)
    ref_points, ref_desc = sift.detectAndCompute(ref_gray, None)
    cap_points, cap_desc = sift.detectAndCompute(cap_gray, None)
    if ref_desc is None or cap_desc is None:
        raise ValueError("Calibration failed: insufficient printed features")
    pairs = cv2.BFMatcher().knnMatch(cap_desc, ref_desc, k=2)
    good = [pair[0] for pair in pairs if len(pair) == 2 and pair[0].distance < 0.65 * pair[1].distance]
    if len(good) < 20:
        raise ValueError("Calibration needs at least 20 distinctive print feature matches")
    source = np.float32([cap_points[m.queryIdx].pt for m in good])
    target = np.float32([ref_points[m.trainIdx].pt for m in good])
    matrix, mask = cv2.findHomography(source, target, cv2.RANSAC, 3.0)
    if matrix is None or mask is None:
        raise ValueError("Calibration could not estimate a homography")
    inliers = mask.ravel().astype(bool)
    if inliers.sum() < 20 or inliers.mean() < 0.4:
        raise ValueError("Calibration rejected: too few consistent printed features")
    height, width = reference.shape[:2]
    coverage = cv2.contourArea(cv2.convexHull(target[inliers])) / (width * height)
    if coverage < 0.15:
        raise ValueError("Calibration rejected: print matches cover too little of the page")
    markers = {k: cv2.perspectiveTransform(v.reshape(1, 4, 2), matrix)[0]
               for k, v in observed.items()}
    if any(np.any(v < 0) or np.any(v[:, 0] >= width) or np.any(v[:, 1] >= height)
           for v in markers.values()):
        raise ValueError("Calibrated markers lie outside the reference page")
    selected = [m for m, keep in zip(good, inliers) if keep][:150]
    overlay = cv2.drawMatches(capture, cap_points, reference, ref_points, selected, None,
                              flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS)
    projected = cv2.perspectiveTransform(source[inliers].reshape(1, -1, 2), matrix)[0]
    error = float(np.sqrt(np.mean(np.sum((projected-target[inliers]) ** 2, axis=1))))
    metrics = {"method": "SIFT print registration", "inlier_matches": int(inliers.sum()),
               "print_coverage": coverage, "reprojection_rmse_px": error}
    LOG.info("Calibrated tags from %d print matches, RMSE %.3fpx", inliers.sum(), error)
    return name, markers, overlay, metrics


def align(image: np.ndarray, page: dict, dictionary: str) -> tuple[np.ndarray, dict, dict]:
    observed = detect_markers(image, dictionary)
    reference = {int(k): np.array(v, np.float32) for k, v in page["markers"].items()}
    shared = sorted(reference.keys() & observed.keys())
    if len(shared) < 2:
        raise ValueError(f"Need >=2 shared ArUco tags; found {shared}")
    source = np.concatenate([observed[k] for k in shared]).astype(np.float32)
    target = np.concatenate([reference[k] for k in shared]).astype(np.float32)
    width, height = page["size_px"]
    threshold = max(3.0, width * 0.002)
    matrix, mask = cv2.findHomography(source, target, cv2.RANSAC, threshold)
    if matrix is None or mask is None or not np.isfinite(matrix).all():
        raise ValueError("Could not estimate a finite page homography")
    inliers = mask.ravel().astype(bool)
    # Require evidence from every shared tag, not a single tiny marker patch.
    if any(inliers[i * 4:(i + 1) * 4].sum() < 3 for i in range(len(shared))):
        raise ValueError("Alignment rejected: inconsistent marker corners")
    hull_area = cv2.contourArea(cv2.convexHull(target[inliers]))
    if hull_area / (width * height) < 0.015:
        raise ValueError("Alignment rejected: markers too close together")
    predicted = cv2.perspectiveTransform(source.reshape(1, -1, 2), matrix)[0]
    error = float(np.sqrt(np.mean(np.sum((predicted[inliers] - target[inliers]) ** 2, axis=1))))
    if error > threshold:
        raise ValueError(f"Alignment error too large: {error:.2f}px")
    # Reject transforms mapping the canonical page to a folded/degenerate quadrilateral.
    page_corners = np.float32([[[0, 0], [width-1, 0], [width-1, height-1], [0, height-1]]])
    projected = cv2.perspectiveTransform(page_corners, np.linalg.inv(matrix))[0]
    if not np.isfinite(projected).all() or not cv2.isContourConvex(projected):
        raise ValueError("Alignment rejected: invalid projected page boundary")
    aligned = cv2.warpPerspective(image, matrix, (width, height),
                                  flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))
    coverage = cv2.warpPerspective(np.full(image.shape[:2], 255, np.uint8), matrix,
                                   (width, height), flags=cv2.INTER_NEAREST)
    for box in page["boxes"]:
        x0, y0, x1, y1 = box["bbox_px"]
        if np.mean(coverage[y0:y1, x0:x1] > 0) < 0.995:
            raise ValueError(f"Answer {box['id']} falls outside the captured image")
    metrics = {"shared_marker_ids": shared, "inlier_corners": int(inliers.sum()),
               "reprojection_rmse_px": error, "homography": matrix.tolist()}
    LOG.info("Aligned with %s: RMSE %.3fpx, %d corners", shared, error, inliers.sum())
    return aligned, metrics, observed
