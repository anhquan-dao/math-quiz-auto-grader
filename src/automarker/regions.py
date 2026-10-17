"""Find printed frames near template priors and remove their southern borders."""

import logging
import math

import cv2
import numpy as np

LOG = logging.getLogger(__name__)
DEFAULT_HORIZONTAL_DILATION_WIDTH_PX = 15
SOUTH_BORDER_METHODS = ("bidirectional-recovery", "protected-crossings")


def horizontal_bounds(binary: np.ndarray, padding: int, *, frame: dict | None = None,
                      origin: tuple[int, int] = (0, 0), dpi: int = 200) -> tuple[int, int]:
    """Return exclusive east/west content bounds without changing vertical extent.

    Ignore a confidently detected printed frame on a measurement copy only. Keep all
    remaining foreground, including dots and isolated minus signs; do not denoise it.
    """
    ink = cv2.bitwise_not(binary)
    height, width = ink.shape
    if frame is not None and frame.get("detected"):
        ox, oy = origin
        guard = max(1, round(dpi*.4/25.4))
        ignored = np.zeros_like(ink)
        seeds = np.zeros_like(ink)
        for ax, ay, bx, by in frame["edges"].values():
            # Extend the fitted segment: cropping can leave disconnected corner arcs
            # beyond the original Hough endpoints, with the straight edge just outside.
            if abs(bx-ax) >= abs(by-ay) and bx != ax:
                slope = (by-ay)/(bx-ax)
                start = (0, round(ay+slope*(ox-ax)-oy))
                stop = (width-1, round(ay+slope*(ox+width-1-ax)-oy))
            elif by != ay:
                slope = (bx-ax)/(by-ay)
                start = (round(ax+slope*(oy-ay)-ox), 0)
                stop = (round(ax+slope*(oy+height-1-ay)-ox), height-1)
            else:
                continue
            cv2.line(ignored, start, stop, 255, 2*guard+1)
            cv2.line(seeds, start, stop, 255, 2*guard+1)
        # Rounded frame corners remain after straight-line suppression. These zones
        # affect measurement only; no pixels in the saved crop are painted over.
        x0, y0, x1, y1 = frame["bbox_px"]
        radius = max(guard, min(round(dpi*1.5/25.4), (y1-y0)//4))
        for x in (x0-ox, x1-ox):
            for y in (y0-oy, y1-oy):
                cv2.rectangle(ignored, (x-radius, y-radius), (x+radius, y+radius), 255, -1)
        _, labels = cv2.connectedComponents(ink, connectivity=8)
        frame_labels = np.unique(labels[(seeds > 0) & (ink > 0)])
        frame_labels = frame_labels[frame_labels != 0]
        # A disconnected dot or sign in a corner is not part of the printed frame.
        ink[(ignored > 0) & np.isin(labels, frame_labels)] = 0
    columns = np.flatnonzero(np.any(ink > 0, axis=0))
    if not len(columns):
        LOG.debug("East/west tightening skipped: no foreground after frame exclusion")
        return 0, width
    left = max(0, int(columns[0])-padding)
    right = min(width, int(columns[-1])+1+padding)
    LOG.debug("East/west tightening: width %d -> %d, left=%d right=%d, padding=%d px",
              width, right-left, left, right, padding)
    return left, right


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


def estimate_southern_band(ink: np.ndarray, line: list[int], bounds: list[int],
                           dpi: int) -> tuple[np.ndarray, np.ndarray, int]:
    """Shared lower-edge position/thickness estimate; return band, local rows, half-height."""
    x0, y0, x1, y1 = bounds
    if not (0 <= x0 < x1 <= ink.shape[1] and 0 <= y0 < y1 <= ink.shape[0]) or dpi <= 0:
        raise ValueError("South-border bounds must lie inside the image and DPI must be positive")
    band = np.zeros((y1-y0, x1-x0), np.uint8)
    ax, ay, bx, by = line
    if ax == bx:
        return band, np.zeros(x1-x0, int), 0
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
    rows = np.array(center_rows, dtype=int)-y0
    for column, y in enumerate(rows):
        start, stop = max(0, y-half), max(0, min(band.shape[0], y+half+1))
        band[start:stop, column] = 255
    LOG.debug("Estimated south border: half-height=%d px, band height=%d px", half, 2*half+1)
    return band, rows, half


def southern_mask(ink: np.ndarray, line: list[int], bounds: list[int], dpi: int) -> np.ndarray:
    """Mask a detected bottom edge, protecting narrow corridors of crossing strokes."""
    x0, y0, x1, y1 = bounds
    band, rows, half = estimate_southern_band(ink, line, bounds, dpi)
    crop = ink[y0:y1, x0:x1]
    mask = np.zeros(crop.shape, np.uint8)
    if not half:
        return mask
    reach = max(3, round(dpi*.8/25.4))
    drift = max(1, round(dpi*.25/25.4))
    protect = np.zeros(crop.shape[1], np.uint8)
    for column, local_y in enumerate(rows):
        left, right = max(0, column-drift), min(crop.shape[1], column+drift+1)
        above = crop[max(0, local_y-half-reach):max(0, local_y-half), left:right]
        below = crop[min(crop.shape[0], local_y+half+1):
                     min(crop.shape[0], local_y+half+reach+1), left:right]
        if above.any() and below.any():
            protect[column] = 255
    protect = cv2.dilate(protect[None, :], np.ones((1, 2*drift+1), np.uint8))[0]
    mask[(band > 0) & (protect[None, :] == 0)] = crop[(band > 0) & (protect[None, :] == 0)]
    LOG.debug("South border mask: %d pixels, %d crossing columns protected",
              cv2.countNonZero(mask), np.count_nonzero(protect))
    return mask


def estimate_southern_band_edges(ink: np.ndarray, line: list[int], bounds: list[int],
                                 dpi: int) -> tuple[np.ndarray, np.ndarray, int, dict]:
    """Estimate thickness from the 10–25% and 75–90% portions of the detected edge.

    Average contiguous vertical ink runs in each portion and use the larger mean.
    Avoid rounded corners, central writing, and runs that reach the search limit.
    The production median estimator remains separate.
    """
    x0, y0, x1, y1 = bounds
    if not (0 <= x0 < x1 <= ink.shape[1] and 0 <= y0 < y1 <= ink.shape[0]) or dpi <= 0:
        raise ValueError("South-border bounds must lie inside the image and DPI must be positive")
    band = np.zeros((y1-y0, x1-x0), np.uint8)
    ax, ay, bx, by = line
    measurements = {"method": "edge_portions", "portions": [], "estimated_thickness_px": 1.0,
                    "fallback": True}
    if ax == bx:
        return band, np.zeros(x1-x0, int), 0, measurements
    slope = (by-ay)/(bx-ax)
    left, right = sorted((ax, bx))
    limit = max(2, round(dpi*.6/25.4))
    for name, start, stop in (("left", .10, .25), ("right", .75, .90)):
        first = max(0, min(ink.shape[1], round(left+(right-left)*start)))
        last = max(first, min(ink.shape[1], round(left+(right-left)*stop)))
        widths = []
        for x in range(first, last):
            y = round(ay+slope*(x-ax))
            if not 0 <= y < ink.shape[0] or not ink[y, x]:
                continue
            lo = hi = y
            while lo > max(0, y-limit) and ink[lo-1, x]:
                lo -= 1
            while hi+1 < min(ink.shape[0], y+limit+1) and ink[hi+1, x]:
                hi += 1
            if lo == y-limit or hi == y+limit:
                continue  # Unbounded ink is likely a crossing or a vertical frame side.
            widths.append(hi-lo+1)
        measurements["portions"].append({"side": name, "x_range_px": [first, last],
                                         "samples": len(widths),
                                         "mean_thickness_px": float(np.mean(widths)) if widths else None})
    means = [p["mean_thickness_px"] for p in measurements["portions"] if p["samples"]]
    thickness = max(means) if means else 1.0
    measurements["estimated_thickness_px"] = thickness
    measurements["fallback"] = not bool(means)
    half = min(max(1, math.ceil(thickness/2))+1, limit)
    rows = np.array([round(ay+slope*(x-ax))-y0 for x in range(x0, x1)], dtype=int)
    for column, y in enumerate(rows):
        band[max(0, y-half):max(0, min(band.shape[0], y+half+1)), column] = 255
    LOG.debug("South border edge portions: %s; thickness=%.2f px, band=%d px",
              measurements["portions"], thickness, 2*half+1)
    return band, rows, half, measurements


def southern_dilate(ink: np.ndarray, line: list[int], bounds: list[int], dpi: int,
                    dilation_height_px: int | None = None, strip_padding_px: int = 7,
                    horizontal_dilation_width_px: int = DEFAULT_HORIZONTAL_DILATION_WIDTH_PX) -> dict:
    """Erase the lower band, then restore original ink selected by two-sided dilation.

    Input/output images use white foreground (255), black background (0). The default
    1-column kernel is band-height + 2 pixels: a centered kernel equal to the gap height
    leaves one empty middle row. Pass dilation_height_px to compare an exact kernel.
    Thickness comes from the two end portions of the detected lower edge. The strip
    extends strip_padding_px above and below the band. After vertical dilation,
    independently dilate left and right (seven pixels each by default, including the
    source). Sum in uint16 and threshold above 255 to retain only two-sided support.
    This rejects one-sided outer rims while filling short horizontal gaps. Dilation
    creates a selection mask only; intersecting with the original prevents invented ink.
    """
    x0, y0, x1, y1 = bounds
    band, rows, half, thickness_estimate = estimate_southern_band_edges(ink, line, bounds, dpi)
    original = ink[y0:y1, x0:x1]
    masked = original.copy()
    masked[band > 0] = 0
    band_height = 2*half+1 if half else 0
    kernel_height = dilation_height_px if dilation_height_px is not None else max(1, band_height+2)
    if not isinstance(kernel_height, int) or isinstance(kernel_height, bool) or kernel_height < 1:
        raise ValueError("Vertical dilation height must be a positive integer")
    if not isinstance(strip_padding_px, int) or isinstance(strip_padding_px, bool) or strip_padding_px < 0:
        raise ValueError("Strip padding must be a nonnegative integer")
    if (not isinstance(horizontal_dilation_width_px, int) or isinstance(horizontal_dilation_width_px, bool)
            or horizontal_dilation_width_px < 1):
        raise ValueError("Horizontal dilation width must be a positive integer")
    strip = np.zeros_like(masked)
    if band.any():
        strip_half = half + strip_padding_px
        for column, y in enumerate(rows):
            start = max(0, y-strip_half)
            stop = max(0, min(strip.shape[0], y+strip_half+1))
            strip[start:stop, column] = 255
    seeds = cv2.bitwise_and(masked, strip)
    dilated = cv2.dilate(seeds, np.ones((kernel_height, 1), np.uint8),
                          borderType=cv2.BORDER_CONSTANT, borderValue=0)
    vertical_mask = cv2.bitwise_and(dilated, strip)
    left_reach = (horizontal_dilation_width_px-1)//2
    right_reach = horizontal_dilation_width_px//2
    left = cv2.dilate(vertical_mask, np.ones((1, left_reach+1), np.uint8), anchor=(0, 0),
                      borderType=cv2.BORDER_CONSTANT, borderValue=0)
    right = cv2.dilate(vertical_mask, np.ones((1, right_reach+1), np.uint8), anchor=(right_reach, 0),
                       borderType=cv2.BORDER_CONSTANT, borderValue=0)
    left, right = cv2.bitwise_and(left, strip), cv2.bitwise_and(right, strip)
    horizontal_sum = left.astype(np.uint16)+right.astype(np.uint16)
    dilation_mask = cv2.threshold(horizontal_sum, 255, 255, cv2.THRESH_BINARY)[1].astype(np.uint8)
    horizontal_union = cv2.bitwise_or(left, right)
    vertical_recovered = cv2.bitwise_or(masked, cv2.bitwise_and(original, cv2.bitwise_and(vertical_mask, band)))
    restoration = cv2.bitwise_and(cv2.bitwise_and(original, dilation_mask), band)
    recovered = cv2.bitwise_or(masked, restoration)
    restored = cv2.bitwise_and(recovered, cv2.bitwise_not(masked))
    removed = cv2.bitwise_and(original, cv2.bitwise_not(recovered))
    invented = cv2.bitwise_and(recovered, cv2.bitwise_not(original))
    LOG.debug("South dilation: band=%d px, vertical=%dx1, horizontal span=1x%d, sum>255, "
              "rejected rim=%d erased=%d recovered=%d new=%d pixels",
              band_height, kernel_height, horizontal_dilation_width_px,
              cv2.countNonZero(horizontal_union)-cv2.countNonZero(dilation_mask),
              cv2.countNonZero(cv2.bitwise_and(original, band)),
              cv2.countNonZero(restored), cv2.countNonZero(invented))
    return {"masked_ink": masked, "recovered_ink": recovered, "band_mask": band,
            "strip_mask": strip, "vertical_dilation_mask": vertical_mask, "dilation_mask": dilation_mask,
            "left_dilation_mask": left, "right_dilation_mask": right,
            "horizontal_dilation_sum": horizontal_sum, "horizontal_union_mask": horizontal_union,
            "vertical_recovered_ink": vertical_recovered,
            "restored_mask": restored, "removed_mask": removed,
            "new_ink_mask": invented, "band_height_px": band_height,
            "kernel_height_px": kernel_height, "strip_padding_px": strip_padding_px,
            "horizontal_dilation_width_px": horizontal_dilation_width_px,
            "horizontal_sum_threshold": 255,
            "thickness_estimate": thickness_estimate}
