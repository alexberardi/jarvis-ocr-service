# OCR provider benchmark

`BENCHMARK.md` is the report: which OCR provider actually reads a photographed
cookbook page best, measured rather than assumed. It is what the provider
invariants in this repo's `CLAUDE.md` cite.

## What is here, and what is not

The report and the harness are committed. **The corpus and the ground truth are
not**, deliberately:

- **The images** are five personal photos of pages from a copyrighted cookbook.
  They are not ours to redistribute, and they are not in any repo.
- **`ground_truth.json`** is a hand transcription of those pages — ingredient
  lines, titles and instruction paragraphs. Same reason.

So `score.py` cannot be run as-is from a clean checkout. That is a real
limitation and it is stated here rather than discovered. To reproduce you need
your own corpus of document photos plus a matching `ground_truth.json`:

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
run_one.py <provider> <set> <image_dir> <out_dir>   # one provider per process
run_paddle3.py <set> <image_dir> <out_dir> [device] # paddleocr 3.x, isolated venv
run_rapid_gpu.py <set> <image_dir> <out_dir> [name] [cuda]
score.py                                            # scores.json + the report tables
```

**One provider per process is deliberate.** easyocr peaks at 14 GB on a 12 MP
image. An earlier version of this benchmark ran the providers as parallel agents
and helped exhaust a 32 GB machine.

`apple_vision_fixed.py` is a standalone copy of the Vision provider with the two
bugs corrected, kept so the "before the fix / after the fix" rows in the report
can be reproduced against the shipped provider.
