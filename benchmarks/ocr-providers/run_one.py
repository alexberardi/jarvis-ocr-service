"""Run ONE provider over ONE image set, then exit.

Deliberately one provider per process: easyocr/paddleocr each pull a torch or
paddle model into memory, and the previous run of this benchmark loaded several
at once inside parallel agents on a machine that was already out of RAM.
Serialising means peak footprint is a single model, and the OS reclaims it
between providers.
"""
import json, os, sys, time, traceback, glob, resource

sys.path.insert(0, '/Users/alexanderberardi/jarvis/jarvis-ocr-service')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PROVIDERS = {
    'tesseract':    ('app.providers.tesseract_provider',   'TesseractProvider'),
    'easyocr':      ('app.providers.easyocr_provider',     'EasyOCRProvider'),
    'paddleocr':    ('app.providers.paddleocr_provider',   'PaddleOCRProvider'),
    'rapidocr':     ('app.providers.rapidocr_provider',    'RapidOCRProvider'),
    'apple_vision': ('app.providers.apple_vision_provider','AppleVisionProvider'),
    'apple_vision_fixed': ('apple_vision_fixed','AppleVisionFixedProvider'),
}

name, image_set, image_dir, out_dir = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
mod_name, cls_name = PROVIDERS[name]

out = {}
try:
    mod = __import__(mod_name, fromlist=[cls_name])
    prov = getattr(mod, cls_name)()
    avail = prov.is_available()
except Exception:
    print(json.dumps({'provider': name, 'set': image_set, 'fatal': traceback.format_exc()}))
    sys.exit(0)

if not avail:
    print(json.dumps({'provider': name, 'set': image_set, 'fatal': 'is_available() returned False'}))
    sys.exit(0)

for path in sorted(glob.glob(os.path.join(image_dir, '*.jpeg'))):
    img = os.path.basename(path)
    raw = open(path, 'rb').read()
    rec = {'provider': name, 'set': image_set, 'image': img, 'bytes': len(raw)}
    for run in ('cold', 'warm'):
        try:
            t0 = time.perf_counter()
            res = prov.process(raw, language_hints=['en'], return_boxes=True, mode='document')
            rec[f'{run}_s'] = round(time.perf_counter() - t0, 3)
            if run == 'warm':
                rec['text'] = res.text
                rec['n_blocks'] = len(res.blocks or [])
                confs = [b.confidence for b in (res.blocks or []) if b.confidence is not None]
                rec['mean_conf'] = round(sum(confs) / len(confs), 4) if confs else None
                rec['chars'] = len(res.text or '')
        except Exception:
            rec['error'] = traceback.format_exc().strip().splitlines()[-1]
            rec[f'{run}_s'] = None
            break
    if 'text' in rec:
        with open(os.path.join(out_dir, 'text', f'{name}__{image_set}__{img}.txt'), 'w') as fh:
            fh.write(rec['text'])
    out[f'{name}::{image_set}::{img}'] = rec

rec_path = os.path.join(out_dir, 'raw', f'{name}__{image_set}.json')
json.dump(out, open(rec_path, 'w'), indent=1)
peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576
ok = sum(1 for v in out.values() if 'text' in v)
warm = [v['warm_s'] for v in out.values() if v.get('warm_s')]
print(json.dumps({'provider': name, 'set': image_set, 'ok': ok, 'n': len(out),
                  'warm_avg_s': round(sum(warm)/len(warm), 2) if warm else None,
                  'peak_rss_gb': round(peak_mb, 2)}))
