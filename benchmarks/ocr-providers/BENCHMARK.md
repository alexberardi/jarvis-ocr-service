# OCR provider benchmark — jarvis-ocr-service

**Date:** 2026-08-23 · **Host:** MacBook Pro M2 Max (32GB), Apple Silicon
**Corpus:** 5 real iPhone photos of printed cookbook pages — multi-column, coloured
headings, shot at a slight angle, some glare and page curvature.
**Ground truth:** 69 ingredient lines across the 5 images, transcribed by hand.

## Sample size

Five images. Every number here should be read as an order-of-magnitude signal, not a
precise ranking. Differences of a few points (rapidocr upright 75.4% vs sideways 79.7%)
are inside the noise floor; differences of 25+ points and 50x latency ratios are not.

## The metric

These pages are OCR'd so an LLM can extract a structured recipe. Character accuracy on
page furniture is irrelevant. **Ingredient-line recall** is the number that matters: did
a ground-truth ingredient line survive contiguously enough to be recognisable
(fuzzy partial match >= 0.75, unicode fractions normalised)? **Quantity fidelity** is the
share of matched lines whose number and unit both survived — "1/4 cup" read as "V4 cup"
breaks downstream parsing even though the line matched.

Matching is deliberately layout-agnostic. Providers differ wildly in line breaking —
Apple Vision emits one block per visual line, easyocr returns the whole page as a single
run-on string — and a line-oriented matcher would score that formatting difference rather
than recognition quality.

## Results — upright set (EXIF orientation applied)

| Provider | Ingredient recall | Quantity fidelity | Warm s/img | Peak RSS | Verdict |
|---|---:|---:|---:|---:|---|
| `apple_vision` **(after fix)** | **100.0%** (69/69) | 100.0% | 1.64 | 1.0 GB | Best on every axis |
| `paddleocr3` (3.7.0) | 88.4% (61/69) | 82.0% | 56.37 | — | Accurate, unusably slow |
| `rapidocr` | 75.4% (52/69) | 78.8% | **1.05** | 1.9 GB | Best local fallback |
| `tesseract` | 60.9% (42/69) | 76.2% | 2.98 | 0.6 GB | Lightest, mediocre |
| `easyocr` | 43.5% (30/69) | 73.3% | 18.33 | **14 GB** | Worst on every axis |
| `apple_vision` (as shipped) | **FAILED 0/69** | — | — | — | Raises on every call |
| `paddleocr` (2.10.0) | **TIMEOUT** | — | >3800 | — | 106 min CPU, never finished |

## Results — sideways set (raw originals, pre-orientation-fix behaviour)

| Provider | Ingredient recall | Delta vs upright |
|---|---:|---:|
| `apple_vision` (after fix) | **100.0%** (69/69) | 0.0 — orientation-immune |
| `paddleocr3` | 87.0% (60/69) | −1.4 |
| `rapidocr` | 79.7% (55/69) | +4.3 (inside noise) |
| `easyocr` | 17.4% (12/69) | **−26.1** |
| `tesseract` | **FAILED** | total loss |

The orientation fix is worth most to easyocr (+26 points) and is the difference between
working and not for tesseract. Apple Vision and rapidocr detect text orientation
themselves and barely notice.

## Three bugs found

**1. `apple_vision` could never succeed.** PyObjC's `performRequests_error_` has an
`NSError**` out-parameter, so it returns a `(success, error)` tuple — `(True, None)` on
success. The provider did `error = handler.performRequests_error_(...)` then
`if error: raise`. A 2-tuple is always truthy, so every successful recognition raised
`Apple Vision OCR failed: (True, None)`.

It shipped broken because the unit-test stub returned bare `None` on success instead of
`(True, None)` — the tests encoded the wrong contract and passed against a
100%-broken provider. Fixing the stub turned three pre-existing tests red.

**2. `apple_vision` recognition level was inverted.** Vision's constants are
Accurate = 0, Fast = 1. The provider set `1` and commented it `# 0 = fast, 1 = accurate`.
Measured on one cookbook page: level 0 → 94 observations / 3057 chars; level 1 → 1
observation / 8 chars. Each of these two bugs independently makes the provider useless.

**3. `tesseract` fails on every raw iPhone photo.** Phone cameras write **MPO**
(Multi-Picture Object — a JPEG container with two frames). Pillow surfaces that as
`MpoImageFile`, which pytesseract rejects with `TypeError: Unsupported image format/type`.
Isolated cleanly: the same pixels via `.convert("RGB")` work fine.

Tesseract is tier 1, so the most common input this service receives — a phone photo —
silently fell through to easyocr: 18s, 14GB, 43.5% recall. The EXIF fix masks this for
*rotated* photos, because re-encoding happens to flatten MPO to JPEG; a photo needing no
rotation is returned byte-for-byte unchanged by design and still breaks.

All three are fixed with regression tests. Suite: 575 passing.

## Recommendations

**paddleocr — DROP, close PR #24.** 2.10.0 never finished the corpus (106 min CPU on 5
images). 3.7.0 installs and runs on Apple Silicon — note `paddleocr` does *not* pull in
`paddlepaddle`, which must be installed separately; 3.3.1 works on ARM — but at 56s/image
it is 54x slower than rapidocr for a workload where Apple Vision is both more accurate and
34x faster. Combined with `is_available()` swallowing init exceptions (a broken tier
vanishes silently) and paddlepaddle's install weight, it does not earn its place.

**Worth chasing separately:** paddleocr3's 88.4% is the best *Linux-native* number
measured, 13 points above rapidocr. rapidocr runs PP-OCR models on ONNXRuntime but ships
an older/mobile tier than paddle 3.7's PP-OCRv5. Pointing rapidocr at PP-OCRv5 ONNX
exports could plausibly buy ~88% at ~1s with no paddlepaddle dependency at all. That is
the single highest-value follow-up here.

**Tier order.** Current `DEFAULT_TIER_ORDER` is
`tesseract → easyocr → paddleocr → rapidocr → apple_vision → llm_local → llm_cloud`.
That puts the 14GB/18s/43% provider second and the 1.6s/100% provider fifth, behind two
that cannot complete. Evidence-based order:

    apple_vision (or remote) → rapidocr → tesseract → llm_local → llm_cloud

with `easyocr` and `paddleocr` dropped. **Not applied** — `DEFAULT_TIER_ORDER` is
unchanged pending review.

**Maintenance hazard.** The auto order is hardcoded in `provider_manager.py:281` *and*
declared in `DEFAULT_TIER_ORDER` in `tier_mapping.py`, with different names for the LLM
tiers (`llm_proxy_vision` vs `llm_local`). Two sources of truth that can drift.

## Reproducing

    run_one.py <provider> <set> <image_dir> <out_dir>   # one provider per process
    run_paddle3.py <set> <image_dir> <out_dir>          # 3.x, isolated venv
    score.py                                            # scores.json + the tables above

One provider per process is deliberate: easyocr peaks at 14GB. An earlier version of this
benchmark ran the providers as parallel agents and helped exhaust a 32GB machine.
