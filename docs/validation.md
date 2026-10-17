# Validation on the supplied dataset

Run on 17 October 2026 with Windows, Python 3.12, and the updated tagged PDF.

| Check | Result |
| --- | --- |
| TeX answer specifications matched to PDF vector boxes | 13 / 13 |
| Detected reference tags | IDs 0 and 1, `DICT_4X4_1000` |
| Captures successfully aligned and cropped | 20 / 20 |
| Answer regions extracted | 260 |
| Crop variants saved | 780 (raw, normalized, binary) |
| Marker reprojection RMSE, min / median / max | 0.065 / 0.140 / 0.278 canonical pixels |
| Unit, local integration, OCR, HTML, CSV, local review service, and opt-in browser tests | 39 passed |
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
