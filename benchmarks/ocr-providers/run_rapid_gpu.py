"""Standalone rapidocr runner, mirroring rapidocr_provider.process()'s parsing.

Kept standalone so it can run on a box that has no jarvis-ocr-service checkout.
Output format matches run_one.py so the same score.py consumes it.
"""
import json, os, sys, time, glob, traceback
import numpy as np
from PIL import Image

image_set, image_dir, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
NAME = sys.argv[4] if len(sys.argv) > 4 else 'rapidocr_gpu'
USE_CUDA = (len(sys.argv) > 5 and sys.argv[5] == 'cuda')

from rapidocr_onnxruntime import RapidOCR
try:
    # RapidOCR's config defaults use_cuda:false in all three sections (Det/Cls/Rec);
    # the CUDAExecutionProvider is only selected when each is switched on explicitly.
    ocr = (RapidOCR(det_use_cuda=True, cls_use_cuda=True, rec_use_cuda=True)
           if USE_CUDA else RapidOCR())
except Exception:
    print(json.dumps({'provider': NAME, 'set': image_set, 'fatal': traceback.format_exc()[-500:]}))
    sys.exit(0)

out = {}
for path in sorted(glob.glob(os.path.join(image_dir, '*.jpeg'))):
    img = os.path.basename(path)
    rec = {'provider': NAME, 'set': image_set, 'image': img, 'bytes': os.path.getsize(path)}
    arr = np.array(Image.open(path))
    for run in ('cold', 'warm'):
        try:
            t0 = time.perf_counter()
            result, _ = ocr(arr)
            rec[f'{run}_s'] = round(time.perf_counter() - t0, 3)
            if run == 'warm':
                texts = [ln[1] for ln in (result or [])]
                scores = [ln[2] for ln in (result or [])]
                rec['text'] = "\n".join(texts)
                rec['n_blocks'] = len(texts)
                rec['mean_conf'] = round(float(sum(scores)/len(scores)), 4) if scores else None
                rec['chars'] = len(rec['text'])
        except Exception:
            rec['error'] = traceback.format_exc().strip().splitlines()[-1]
            rec[f'{run}_s'] = None
            break
    if 'text' in rec:
        open(os.path.join(out_dir, 'text', f'{NAME}__{image_set}__{img}.txt'), 'w').write(rec['text'])
    out[f'{NAME}::{image_set}::{img}'] = rec

json.dump(out, open(os.path.join(out_dir, 'raw', f'{NAME}__{image_set}.json'), 'w'), indent=1)
warm = [v['warm_s'] for v in out.values() if v.get('warm_s')]
print(json.dumps({'provider': NAME, 'set': image_set,
                  'ok': sum(1 for v in out.values() if 'text' in v), 'n': len(out),
                  'warm_avg_s': round(sum(warm)/len(warm), 3) if warm else None}))
