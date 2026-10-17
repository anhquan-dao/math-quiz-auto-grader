# Pipeline and coordinate contract

1. Read explicit empty answer `tcolorbox` dimensions from UTF-8 TeX.
2. Render the compiled PDF at a fixed DPI and match vector box extents to those dimensions.
3. Record canonical ArUco corners in the same top-left pixel coordinate system.
4. Detect matching tag IDs in a phone image. Estimate a homography from photo pixels
   into canonical pixels, retaining each marker's decoded corner order.
5. Warp the photo, normalize illumination, denoise, and optionally binarize it.
6. Crop canonical box interiors and run a locally provisioned formula recognizer.
7. Compare recognized LaTeX/decimal literals with an explicit key for human review.

Coordinates use `[x0,y0,x1,y1]`, origin top-left. Pixel crop upper bounds are exclusive.
PDF dimensions are in 72-point inches; TeX `pt` is converted from 72.27 points/inch.
Manifest `dpi / 72` maps PDF coordinates to pixels. Homographies map photo -> template.

The default two-tag arrangement is adequate for this initial planar prototype but has
little redundancy and can extrapolate poorly at unmarked corners. Four unique tags
near the page corners improve coverage and allow stronger outlier checks. For production,
add calibrated lens correction, more tags, explicit page/template IDs, crop-level quality
and blank-answer detection, representative handwriting evaluation, and review UI.

Review the template overlay when changing the TeX/PDF. Regenerate templates after any
layout change. Model revision and source hashes are stored for provenance; alignment
RMSE measures marker consistency, not OCR correctness or absolute crop accuracy.
