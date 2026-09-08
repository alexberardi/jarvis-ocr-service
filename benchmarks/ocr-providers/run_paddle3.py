"""paddleocr 3.7.0 runner — the 3.x API, in its own venv.

Mirrors run_one.py's output format so score.py treats it like any other provider.
3.x breaks the 2.x call shape three ways (the reason PR #24 is stuck):
  - no `use_gpu=` kwarg (ValueError in parse_common_args)
  - `ocr(..., cls=True)` -> `predict()`, angle handling is now a constructor flag
  - result is [{'res': {'rec_texts': [...], 'rec_scores': [...]}}], not [[bbox,(text,score)]]
"""
import json, os, sys, time, glob, traceback

image_set, image_dir, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
DEVICE = sys.argv[4] if len(sys.argv) > 4 else None      # 'gpu' | 'cpu' | None (auto)
NAME = sys.argv[5] if len(sys.argv) > 5 else 'paddleocr3'

from paddleocr import PaddleOCR

try:
    kw = {'lang': 'en', 'use_textline_orientation': True}
    if DEVICE:
        kw['device'] = DEVICE      # 3.x replaced 2.x's use_gpu= with device=
    ocr = PaddleOCR(**kw)
except Exception:
    print(json.dumps({'provider': NAME, 'set': image_set, 'fatal': traceback.format_exc()[-600:]}))
    sys.exit(0)

out = {}
for path in sorted(glob.glob(os.path.join(image_dir, '*.jpeg'))):
    img = os.path.basename(path)
    rec = {'provider': NAME, 'set': image_set, 'image': img, 'bytes': os.path.getsize(path)}
    for run in ('cold', 'warm'):
        try:
            t0 = time.perf_counter()
            res = ocr.predict(path)
            rec[f'{run}_s'] = round(time.perf_counter() - t0, 3)
            if run == 'warm':
                texts, scores = [], []
                for page in res:
                    r = page['res'] if isinstance(page, dict) and 'res' in page else page
                    texts.extend(r.get('rec_texts', []))
                    scores.extend(r.get('rec_scores', []))
                rec['text'] = "\n".join(texts)
                rec['n_blocks'] = len(texts)
                rec['mean_conf'] = round(sum(scores)/len(scores), 4) if scores else None
                rec['chars'] = len(rec['text'])
        except Exception:
            rec['error'] = traceback.format_exc().strip().splitlines()[-1]
            rec[f'{run}_s'] = None
            break
    if 'text' in rec:
        open(os.path.join(out_dir, 'text', f'{NAME}__{image_set}__{img}.txt'), 'w').write(rec['text'])
    out[f'{NAME}::{image_set}::{img}'] = rec

json.dump(out, open(os.path.join(out_dir, 'raw', f'{NAME}__{image_set}.json'), 'w'), indent=1)
ok = sum(1 for v in out.values() if 'text' in v)
warm = [v['warm_s'] for v in out.values() if v.get('warm_s')]
print(json.dumps({'provider': NAME, 'set': image_set, 'ok': ok, 'n': len(out),
                  'warm_avg_s': round(sum(warm)/len(warm), 2) if warm else None}))
