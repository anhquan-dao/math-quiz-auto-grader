# Validation on the supplied dataset

Run on 17–18 October 2026 with Windows, Python 3.12, and the updated tagged PDF.

| Check | Result |
| --- | --- |
| TeX answer specifications matched to PDF vector boxes | 13 / 13 |
| Detected reference tags | IDs 0 and 1, `DICT_4X4_1000` |
| Captures successfully aligned and cropped | 20 / 20 |
| Answer regions extracted | 260 |
| Crop variants saved | 780 (raw, normalized, binary) |
| Marker reprojection RMSE, min / median / max | 0.065 / 0.140 / 0.278 canonical pixels |
| Unit, local integration, OCR, HTML, CSV, crop refinement, CLI, local review service, and opt-in browser tests | 144 passed |
| Ruff | Passed |
| Dependency consistency (`pip check`) | Passed |
| Local math OCR | 260 / 260 crops across 20 captures produced LaTeX |
| Explicit network prohibition | Local model loaded and generated with socket connections blocked |

The capture set includes tilt, rotation, perspective, dim/warm/cool illumination,
desk shadow, grain, and soft focus. Example box overlays and normalized crops were
visually inspected. These checks establish working extraction on these synthetic
captures, not general performance on real phone photographs or OCR accuracy.

Generated evidence is under `templates/generated/quiz_gt2/` and `outputs/quiz_gt2/`.
Batch outcomes are in `outputs/quiz_gt2/summary.json`; each capture has its own
`extraction.json` and intermediate images. These generated directories are ignored
by Git and can be reproduced with the README commands.

OCR output contains transcription errors on the synthetic writing and requires review.
No labeled crop transcription set was provided, so character/formula accuracy was not
measured. A comparison run with the illustrative answer key also completed; its results
are not real student grades.

The provisioned math model is `breezedeus/pix2text-mfr`, revision
`bea257edb2653f2ae413b084f2ac0e8299d08df0`. PyTorch is constrained to 2.6.x because
the pinned Optimum API imports ONNX helpers removed in newer PyTorch releases.
The model uses pre-exported ONNX encoder/decoder files; no model export is required.
The test run emits one upstream ONNX exporter registration warning; inference completes.

The `run` workflow was also checked on two local captures: template creation,
extraction, offline OCR, and candidate key comparison completed for both papers
(26 answers). Evidence is in `outputs/run_smoke/`. The local input files are not
tracked in Git; the corresponding integration test skips when they are unavailable.

The HTML archive in `outputs/quiz_gt2/archive/` contains 20 photo-named pages and
260 answer rows, with intentionally made-up expectations labeled as demo values.
Its ZIP was extracted to a separate directory and every page was opened in headless
Chrome while HTTP/HTTPS requests were blocked. All crop images loaded, no script errors
or external requests occurred, and desktop/mobile layouts had no horizontal page overflow.
Of the 520 OCR/expected formula previews, 519 rendered; one malformed OCR result showed
the intended raw-TeX fallback. The index and paper layouts were visually inspected.

The `run` command's automatic HTML export was exercised on an additional single-paper
run. The updated quick run in `outputs/auto_verdict_smoke/` produced 13 automatic CSV
verdicts with empty human-review timestamps. A wheel build also verified that the renderer,
review service, stylesheet, license, and all 20 WOFF2 font files are included in the package.

The HTML reviewer automatically uses its quiz archive's `assessment.csv`. Its 260 answer
rows have automatic binary verdicts before human review; the viewer shows these verdicts
and uses mutually exclusive tick/cross buttons for corrections. Browser checks covered
draft edits, cancellation, explicit approval, save-and-next navigation, restoration on
reopening, and conflicting edits from another reviewer. Drafts and cancellation left the
CSV byte for byte unchanged; approved saves preserved all other papers' records. Quoted
multiline Vietnamese notes round-tripped through the actual CSV and Python reader.
Programmatic clicks on the approval button were rejected.

The repeatable opt-in browser test uses the real loopback review service and an isolated
temporary CSV; it never modifies the quiz assessment file. Server tests verify mandatory
page approval, quiz identity, request origin and token checks, binary verdict validation,
locked-file handling, and version conflicts. Browser file selection is no longer required.
The service serves one archive on localhost and requires no internet connection.

Report regeneration was verified to preserve an unchanged CSV byte for byte. Migration
tests verify that legacy unreviewed rows gain automatic verdicts without losing prior
reviewer corrections or duplicating rows. The packaged wheel includes the browser
reviewer script and Python assessment helpers. The ZIP remains a snapshot and must be
regenerated after saving reviews to share the newest CSV.

The bounding-box branch was additionally checked on eight real phone photos (104
answer regions), with evidence under `outputs/bounding_boxes_preview/real/`. The
detector accepted 85 frames and used the template fallback for 19. These are detection
outcomes, not a measured localization accuracy: ground-truth frame coordinates were
not supplied. Frame edges must come from the same connected printed structure, stay
within the bounded prior search, and retain approximately the expected dimensions.

Crop tests cover shifted and sloped frames, adjacent-box confusion, fallback when no
reliable frame is present, page/neighbor expansion limits, border-crossing vertical and
diagonal strokes, optional mask disabling, and removal-mask bounds. The real-photo
inspection included an answer whose handwritten `y` descends through the lower border;
its below-border stroke remains visible after masking. The method cannot reliably
separate ink that is indistinguishable from the printed frame.

An additional real-photo quick run in `outputs/bounding_boxes_final/` completed template
creation, frame refinement, expanded crops, local OCR for 13 answers, automatic CSV
verdicts, and HTML export. Existing `outputs/run/` assessments were left untouched.
The README option reference is checked against every subcommand's generated help.

Compact output tests cover all three selected variants, HTML generation from a
binary-only capture, OCR against retained crop paths, and a clear error for an omitted
variant. A debug-to-compact rerun preserves the final crop bytes, removes obsolete known
stage images and alternate crops, and retains unrelated annotations and notes. Detailed
images now require `--debug-images`; text DEBUG logs remain enabled. A 13-answer quick
run in `outputs/compact_smoke/` contains 31 per-paper files instead of 78, with the same
HTML review and CSV workflow.

East/west tightening is checked after binary processing and lower-border
masking. Tests cover dots and isolated minus signs, below-border content, blank crops,
edge-touching writing, padding limits, rounded frame fragments, and uncertain-frame
fallback. Integration checks verify unchanged vertical coordinates, matching bounds
across all saved variants and masks, and pixel-identical horizontal slices without
additional output files. CLI checks verify both options reach the batch workflow.
Real-photo evidence is under `outputs/tightened_smoke/`; no recognition accuracy claim
is made from changing crop widths.

Dynamic tightening defaults to enabled with 1.5 mm of padding on each side. CLI checks
cover these settings, `--no-tighten-ew`, and explicit overrides for both `run` and
`extract`. Crop checks verify that the Python default matches explicit 1.5 mm padding
and keeps more horizontal space than the earlier 0.5 mm setting, with unchanged vertical
bounds. The real-photo extraction check is under `outputs/default_tighten_smoke/`.

The default mode now runs a static 1.5 mm cut per side before dynamic whitespace
tightening with 1.5 mm padding. Modes `static`, `dynamic`, and `both` are tested through
both CLI commands. Tests verify exact static slices in every crop variant and mask,
static-before-dynamic ordering when edge ink is removed, zero static cuts, disabling
both stages, invalid distances/modes, and rejecting a cut that would empty a crop.
Real-photo evidence under `outputs/static_dynamic_smoke/` contains 13 answers, each with
an exact 12-pixel static cut per side at 200 DPI. The total cut equals the sum of both
stages, and vertical bounds and compact output counts are unchanged.

Normalized review PNGs now color the applied south-border mask red. Tests verify an
exact match between red pixels and the removal mask, unchanged unmasked strokes, no
red annotation when border removal is disabled, and the HTML legend. OCR tests verify
pixel-identical clean input with red pixels restored to white, cleanup of temporary
inputs on success and failure, and unchanged preview bytes afterward. Real-photo
inspection evidence is under `outputs/red_mask_preview/`; the crossing handwritten
descender remains black while removed border pixels are red. The compact file count
does not increase.

Bidirectional Recovery (`southern_dilate()`) retains the detected line position but estimates
thickness from the 10–25% and 75–90% end portions of the south edge. It uses the larger
of the two mean vertical ink-run widths, excluding runs reaching the search limit;
missing samples use the other portion or a documented 1-pixel fallback. It erases the
complete band and dilates foreground vertically within a strip extending 7 pixels
above and below the removal band, followed by independent seven-pixel leftward and
rightward dilations including their source pixels. Both are clipped to the strip,
summed in uint16, and thresholded above 255 to require two-sided support. This rejects
outer rims from a horizontal union while filling short internal gaps. The result selects original ink for
restoration inside the band, so the recovered image is a subset of the original.
Tests cover
reconnecting a vertical crossing, the one-pixel gap with an exact band-height kernel,
unchanged pixels outside the strip, removal of bare borders, blank/outside-border
cases, no invented ink near non-crossing strokes, sloped bands, invalid kernel heights,
strip extents independent of kernel height, and invalid strip padding. Additional
checks cover central handwriting exclusion, unequal end thicknesses, arithmetic means,
unbounded crossing rejection, missing end samples, explicit fallback, horizontal
dilation ordering, width overrides, invalid horizontal kernels, one-sided rim rejection,
internal-gap recovery, non-overflowing sums, and a separate vertical-only recovery.
The larger default horizontal span (15 pixels, formerly 3) is tested on an 8-shaped
loop intersecting a printed border. It recovers additional actual loop pixels while
keeping the removal band and vertical mask identical. The production CLI exposes
`--horizontal-dilation-width-px` for tuning.
Before retiring the standalone comparison tool, it checked 85 detected crops across
eight real photos and skipped 19 uncertain frames. The representative contact sheet
is preserved in `docs/assets/comparison.png` and embedded in the README. Temporary
comparison pages, metadata, and duplicate inputs were retired from active outputs,
and the generator removed after
both methods became production options. Every compared crop had zero
added foreground pixels outside the original. All 85 crops have usable edge samples;
three have a different band height from the Protected Crossings median estimate. The overlap
threshold rejects 26,000 one-sided selection-mask pixels across the visible crops;
35 crops restore additional original pixels compared with vertical-only recovery
(2,158 restored pixels versus 1,674 in total; the earlier 1-pixel reach restored 1,683).
A Chrome check loaded all 1,360
embedded images, verified five comparison columns and the overlap-mask details,
and checked the layout at desktop and 390-pixel mobile widths.
Some original border fragments may be
restored near writing; this is not an OCR accuracy result.

Production extraction now defaults to Bidirectional Recovery. `run` and `extract`
accept `--south-border-method bidirectional-recovery` or `protected-crossings` and
`--horizontal-dilation-width-px` (15 by default). Integration checks verify both
CLI paths and batch forwarding, selected-method masks before tightening, saved binary
pixels and red normalized overlays, unchanged compact file counts, the keep-border
override, uncertain-frame fallback, and validation before writing any capture files.
Extraction metadata records the selection and recovery geometry for inspection.

The default production workflow was rerun on all eight real photos at 200 DPI.
All eight succeeded, with 104 nonempty OCR results and no truncated generations.
Saved binary crops and red normalized overlays were checked pixel for pixel against
Bidirectional Recovery on the same pre-tightening bounds. Masking was applied to
85 confidently detected frames; 19 uncertain frames retained their original pixels.
Each capture retains the compact 31-file output, with no temporary OCR folders left.
The regenerated `outputs/run/archive/index.html` contains eight paper pages and
`assessment.csv` has 104 automatic verdicts using clearly labeled demo expectations.
The preserved method comparison is `docs/assets/comparison.png`; its five
columns include Protected Crossings, vertical-only recovery, and Bidirectional Recovery.
These checks establish successful processing and consistent masks, not OCR accuracy.

Paper reviews now hide the recognized LaTeX column by default. Browser checks verify
show/hide controls, accessible pressed state, reset on the next paper, and both
visibility states at mobile width. The eight real-paper reports were regenerated
without rerunning OCR; their archive identity and assessment CSV bytes were preserved.
All 104 recognition cells were checked hidden and revealed, with three visible
columns filling the desktop table when recognition is hidden. The border-removal
illustration is tracked at `docs/assets/comparison.png`. Retired experiment outputs
and old test artifacts are recoverable under the ignored `.tools/` directory.
