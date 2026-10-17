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
| Unit, optional local integration, and offline OCR tests | 11 passed |
| Clean checkout without local inputs or weights | 9 passed, 2 optional tests skipped |
| Ruff | Passed |
| Dependency consistency (`pip check`) | Passed |
| Local math OCR | 13 / 13 crops on `capture_01_near_flat` produced LaTeX |
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
