"""Find printed frames near template priors and remove their southern borders."""

import logging
import math

import cv2
import numpy as np

LOG = logging.getLogger(__name__)


def refine_box(ink: np.ndarray, prior: list[int], radius: int) -> dict:
    """Require four long, near-axis frame edges within a bounded template search."""
    x0, y0, x1, y1 = prior
    height, width = ink.shape
    left, top = max(0, x0-radius), max(0, y0-radius)
    right, bottom = min(width, x1+radius+1), min(height, y1+radius+1)
    roi = ink[top:bottom, left:right]
    _, labels = cv2.connectedComponents(roi, connectivity=8)
    edges, supports = {}, []
    component = None
    for name, horizontal, expected in (("north", True, y0), ("south", True, y1),
                                        ("west", False, x0), ("east", False, x1)):
        span = x1-x0 if horizontal else y1-y0
        target = expected
        if name == "south":
            target = (edges["north"][1]+edges["north"][3])/2 + (y1-y0)
        elif name == "east":
            target = (edges["west"][0]+edges["west"][2])/2 + (x1-x0)
        minimum = .55 if horizontal else .4  # Rounded corners shorten vertical sides.
        length = max(8, round(span * minimum))
        lines = cv2.HoughLinesP(roi, 1, np.pi/720, threshold=max(8, length//3),
                                minLineLength=length, maxLineGap=max(2, round(span*.03)))
        candidates = []
        if lines is not None:
            for raw in lines[:, 0]:
                a, b, c, d = map(int, raw)
                a, c, b, d = a+left, c+left, b+top, d+top
                u0, u1, v0, v1 = (a, c, b, d) if horizontal else (b, d, a, c)
                if abs(u1-u0) < length or abs(v1-v0) > max(2, abs(u1-u0)*.045):
                    continue
                start, stop = (x0, x1) if horizontal else (
                    round((edges["north"][1]+edges["north"][3])/2),
                    round((edges["south"][1]+edges["south"][3])/2))
                if stop-start < 4:
                    continue
                slope = (v1-v0)/(u1-u0)
                intercept = v0-slope*u0
                center = slope*((start+stop)/2)+intercept
                if abs(center-expected) > radius:
                    continue
                overlap = max(0, min(max(u0, u1), stop)-max(min(u0, u1), start))/span
                if overlap < minimum:
                    continue
                positions = np.arange(start+2, stop-1)
                cross = np.rint(slope*positions+intercept).astype(int)
                xx, yy = (positions, cross) if horizontal else (cross, positions)
                # Permit antialiasing and a slightly thick frame, while scoring continuity.
                support = np.zeros(len(positions), bool)
                edge_labels = []
                for delta in (-1, 0, 1):
                    xs, ys = (xx, yy+delta) if horizontal else (xx+delta, yy)
                    valid = (xs >= 0) & (xs < width) & (ys >= 0) & (ys < height)
                    support[valid] |= ink[ys[valid], xs[valid]] > 0
                    local = valid & (xs >= left) & (xs < right) & (ys >= top) & (ys < bottom)
                    edge_labels.extend(labels[ys[local]-top, xs[local]-left].tolist())
                confidence = float(np.mean(support))
                if not edge_labels:
                    continue
                counts = np.bincount(edge_labels)
                counts[0] = 0
                label = int(np.argmax(counts))
                if not label or (component is not None and label != component):
                    continue  # Four edges must belong to the same printed frame.
                if confidence >= (.65 if horizontal else .55):
                    score = confidence + .15*overlap - .6*abs(center-target)/max(1, radius)
                    candidates.append((score, confidence, [a, b, c, d], label))
        if not candidates:
            LOG.debug("Frame fallback at %s: no reliable %s edge", prior, name)
            return {"bbox_px": list(prior), "detected": False, "confidence": 0., "edges": {}}
        _, support, line, component = max(candidates, key=lambda item: item[0])
        edges[name] = line
        supports.append(support)
    west, east, north, south = (edges[n] for n in ("west", "east", "north", "south"))
    bounds = [round((west[0]+west[2])/2), round((north[1]+north[3])/2),
              round((east[0]+east[2])/2), round((south[1]+south[3])/2)]
    valid = (0 <= bounds[0] < bounds[2] < width and 0 <= bounds[1] < bounds[3] < height
             and abs((bounds[2]-bounds[0])-(x1-x0)) <= max(4, (x1-x0)*.12)
             and abs((bounds[3]-bounds[1])-(y1-y0)) <= max(4, (y1-y0)*.12))
    if not valid:
        LOG.debug("Frame fallback at %s: inconsistent detected bounds %s", prior, bounds)
        return {"bbox_px": list(prior), "detected": False, "confidence": 0., "edges": {}}
    confidence = min(supports)
    LOG.debug("Refined frame %s -> %s; minimum edge support %.3f", prior, bounds, confidence)
    return {"bbox_px": bounds, "detected": True, "confidence": confidence, "edges": edges}


def southern_mask(ink: np.ndarray, line: list[int], bounds: list[int], dpi: int) -> np.ndarray:
    """Mask only a detected bottom edge, protecting ink that crosses both sides.

    Ink inseparable from the printed line cannot be recovered unambiguously. Protect
    narrow crossing corridors rather than deleting a full horizontal strip.
    """
    x0, y0, x1, y1 = bounds
    crop = ink[y0:y1, x0:x1]
    mask = np.zeros(crop.shape, np.uint8)
    ax, ay, bx, by = line
    if ax == bx:
        return mask
    slope = (by-ay)/(bx-ax)
    # Estimate stroke width from the middle of the long line, robust to sparse handwriting.
    widths = []
    center_rows = []
    for x in range(x0, x1):
        y = round(ay+slope*(x-ax))
        center_rows.append(y)
        if not (0 <= y < ink.shape[0]) or not ink[y, x]:
            continue
        lo = hi = y
        limit = max(2, round(dpi*.6/25.4))
        while lo > max(0, y-limit) and ink[lo-1, x]:
            lo -= 1
        while hi+1 < min(ink.shape[0], y+limit+1) and ink[hi+1, x]:
            hi += 1
        widths.append(hi-lo+1)
    half = max(1, math.ceil(float(np.median(widths))/2)) if widths else 1
    half = min(half+1, max(2, round(dpi*.6/25.4)))
    reach = max(3, round(dpi*.8/25.4))
    drift = max(1, round(dpi*.25/25.4))
    protect = np.zeros(crop.shape[1], np.uint8)
    for column, y in enumerate(center_rows):
        local_y = y-y0
        left, right = max(0, column-drift), min(crop.shape[1], column+drift+1)
        above = crop[max(0, local_y-half-reach):max(0, local_y-half), left:right]
        below = crop[min(crop.shape[0], local_y+half+1):
                     min(crop.shape[0], local_y+half+reach+1), left:right]
        if above.any() and below.any():
            protect[column] = 255
    protect = cv2.dilate(protect[None, :], np.ones((1, 2*drift+1), np.uint8))[0]
    for column, y in enumerate(center_rows):
        if not protect[column]:
            start = max(0, y-y0-half)
            stop = max(0, min(crop.shape[0], y-y0+half+1))
            mask[start:stop, column] = crop[start:stop, column]
    LOG.debug("South border mask: %d pixels, %d crossing columns protected",
              cv2.countNonZero(mask), np.count_nonzero(protect))
    return mask
