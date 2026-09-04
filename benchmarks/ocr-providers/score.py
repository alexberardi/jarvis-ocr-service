"""Score OCR output against ground truth.

The metric that matters is NOT character accuracy: this text is fed to an LLM
that extracts a structured recipe. What counts is whether an ingredient line
survived intact enough to be recognisable, and whether its quantity survived.
"""
import json, glob, os, re, sys, unicodedata
from difflib import SequenceMatcher
from rapidfuzz import fuzz

S = os.path.dirname(os.path.abspath(__file__))
GT = json.load(open(os.path.join(S, 'ground_truth.json')))

FRACTIONS = {'¼':'1/4','½':'1/2','¾':'3/4','⅓':'1/3','⅔':'2/3','⅛':'1/8','⅜':'3/8','⅝':'5/8','⅞':'7/8'}
QTY = re.compile(r'(\d+\s*/\s*\d+|\d+(?:\.\d+)?)\s*'
                 r'(cups?|tablespoons?|teaspoons?|tbsp|tsp|ounces?|oz|pounds?|lbs?|lb|'
                 r'cloves?|grams?|g|ml|pints?|quarts?|cans?|slices?|sprigs?|pinch(?:es)?)?', re.I)

def norm(s):
    s = unicodedata.normalize('NFKC', s or '')
    for k, v in FRACTIONS.items():
        s = s.replace(k, v)
    s = s.lower()
    s = s.replace('—', '-').replace('–', '-').replace('’', "'").replace('“','"').replace('”','"')
    s = re.sub(r'[^a-z0-9/\.\s-]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()

def best_match(line, haystack):
    """Best fuzzy placement of one ground-truth ingredient line in the OCR text.

    Layout-agnostic on purpose: providers differ wildly in how they emit line
    breaks (Apple Vision one block per visual line, easyocr a single run-on
    string), and a line-oriented matcher would score that formatting difference
    rather than the recognition quality. partial_ratio finds the best-matching
    window of the haystack, so credit depends on the line surviving contiguously.
    """
    n = norm(line)
    if not n:
        return None, 0.0
    al = fuzz.partial_ratio_alignment(n, haystack)
    if al is None:
        return None, 0.0
    return haystack[al.dest_start:al.dest_end], al.score / 100.0

def qty_of(s):
    m = QTY.search(norm(s))
    if not m: return None
    num = re.sub(r'\s+', '', m.group(1))
    return (num, (m.group(2) or '').rstrip('s'))

rows = {}
for path in sorted(glob.glob(os.path.join(S, 'text', '*.txt'))):
    base = os.path.basename(path)[:-4]
    provider, image_set, image = base.split('__')
    gt = GT.get(image)
    if not gt:
        continue
    out = open(path, errors='ignore').read()
    out_lines = [norm(l) for l in out.splitlines() if norm(l)]
    joined = ' '.join(out_lines)

    ings = gt.get('ingredients', [])
    hit = qty_ok = 0
    for line in ings:
        m, r = best_match(line, joined)
        if r >= 0.75:
            hit += 1
            gq, mq = qty_of(line), qty_of(m or '')
            if gq and mq and gq[0] == mq[0] and (not gq[1] or gq[1] == mq[1]):
                qty_ok += 1
            elif not gq:
                qty_ok += 1
    title = gt.get('title')
    title_ok = bool(title) and SequenceMatcher(None, norm(title), joined).find_longest_match(
        0, len(norm(title)), 0, len(joined)).size >= max(6, int(len(norm(title)) * 0.7))

    rows[f'{provider}::{image_set}::{image}'] = {
        'provider': provider, 'set': image_set, 'image': image,
        'n_ing': len(ings), 'hit': hit, 'qty_ok': qty_ok,
        'title_ok': title_ok, 'chars': len(out),
    }

# fold in latency / errors from the raw records
raw = {}
for f in glob.glob(os.path.join(S, 'raw', '*.json')):
    raw.update(json.load(open(f)))
for k, v in rows.items():
    v['warm_s'] = raw.get(k, {}).get('warm_s')
    v['cold_s'] = raw.get(k, {}).get('cold_s')

json.dump(rows, open(os.path.join(S, 'scores.json'), 'w'), indent=1)

# aggregate
agg = {}
for v in rows.values():
    key = (v['provider'], v['set'])
    a = agg.setdefault(key, {'n_ing':0,'hit':0,'qty_ok':0,'titles':0,'imgs':0,'chars':0,'t':[]})
    a['n_ing'] += v['n_ing']; a['hit'] += v['hit']; a['qty_ok'] += v['qty_ok']
    a['titles'] += int(v['title_ok']); a['imgs'] += 1; a['chars'] += v['chars']
    if v['warm_s']: a['t'].append(v['warm_s'])

# providers that produced NO text at all still deserve a row
for f in glob.glob(os.path.join(S, 'raw', '*.json')):
    for k, v in json.load(open(f)).items():
        key = (v['provider'], v['set'])
        if key not in agg:
            agg[key] = {'n_ing':0,'hit':0,'qty_ok':0,'titles':0,'imgs':0,'chars':0,'t':[],
                        'error': v.get('error') or v.get('fatal')}

print(f"{'provider':22s} {'set':9s} {'ingr recall':>12s} {'qty fidelity':>13s} {'titles':>7s} {'warm s/img':>11s} {'chars':>7s}")
print('-' * 88)
for (p, s_), a in sorted(agg.items(), key=lambda kv: (-((kv[1]['hit']/kv[1]['n_ing']) if kv[1]['n_ing'] else -1), kv[0])):
    if a['n_ing'] == 0:
        print(f"{p:22s} {s_:9s} {'FAILED':>12s}  {str(a.get('error',''))[:44]}")
        continue
    rec = a['hit']/a['n_ing']*100
    qf  = a['qty_ok']/a['hit']*100 if a['hit'] else 0
    t   = sum(a['t'])/len(a['t']) if a['t'] else float('nan')
    print(f"{p:22s} {s_:9s} {a['hit']:3d}/{a['n_ing']:<3d} {rec:5.1f}% {qf:11.1f}% {a['titles']:4d}/{a['imgs']:<2d} {t:10.2f} {a['chars']:7d}")
