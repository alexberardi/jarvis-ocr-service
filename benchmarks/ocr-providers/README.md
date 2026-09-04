# OCR provider benchmark

`BENCHMARK.md` is the report: which OCR provider actually reads a photographed
cookbook page best, measured rather than assumed. It is what the provider
invariants in this repo's `CLAUDE.md` cite.

## What is here, and what is not

`corpus/` holds the five source images: photographs of printed cookbook pages,
straight off an iPhone. They are the input every number in `BENCHMARK.md` was
measured against, committed full size (~16 MB total) rather than downscaled,
because shrinking them would change the results they are supposed to reproduce.

They are photographs of a copyrighted cookbook, included here as benchmark
fixtures. If that ever becomes a problem, note that removing them needs a git
history rewrite, not a delete commit.

`upright/` is **not** stored — generate it with `make_upright.py` (below). It is
derived from `corpus/` by the service's own `_normalize_orientation`, so if that
regresses the benchmark moves with it, which is the signal you want.

**`ground_truth.json` is still missing**, and it is the half that `score.py`
needs. It is a hand transcription of these pages — titles, ingredient lines and
instruction paragraphs — so it reproduces far more of the book's actual text
than a photograph does, and it was left out for that reason.

So the providers can be **run** against this corpus from a clean checkout, but
their output cannot be **scored** without supplying a ground truth. That is a
real limitation, stated here rather than discovered. The format:

```json
{
  "IMG_0001.jpeg": {
    "title": "...",
    "ingredients": ["1/4 cup soy sauce", "2 tablespoons honey"],
    "instruction_paragraphs": ["..."],
    "page_furniture": ["page numbers, running heads"],
    "notes": "glare / curvature / multi-column"
  }
}
```

Only `ingredients` and `title` are scored, so the rest can be left empty.

## Running it

```bash
mkdir -p raw text
python make_upright.py corpus upright         # derive the upright set

# `upright` and `sideways` are just set labels; corpus/ IS the sideways set.
python run_one.py tesseract    upright  upright .
python run_one.py tesseract    sideways corpus  .
python run_paddle3.py          upright  upright . gpu    # 3.x, isolated venv
python run_rapid_gpu.py        upright  upright . rapidocr_gpu cuda
python score.py                               # needs ground_truth.json
```

The two sets are the experiment: `corpus/` is what the camera actually wrote
(EXIF orientation = 6, landscape pixels, "rotate 90 CW" tag), and `upright/` is
the same photos with that rotation baked in. Comparing them is how the report
quantifies what the orientation fix bought — +26 points for easyocr, and the
difference between working and not for tesseract.

**One provider per process is deliberate.** easyocr peaks at 14 GB on a 12 MP
image. An earlier version of this benchmark ran the providers as parallel agents
and helped exhaust a 32 GB machine.

`apple_vision_fixed.py` is a standalone copy of the Vision provider with the two
bugs corrected, kept so the "before the fix / after the fix" rows in the report
can be reproduced against the shipped provider.
