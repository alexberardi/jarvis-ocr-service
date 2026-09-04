"""Render BENCHMARK.md from scores.json + raw/*.json."""
import json, glob, os

S = os.path.dirname(os.path.abspath(__file__))
rows = json.load(open(os.path.join(S, 'scores.json')))
raw = {}
peaks = {}
for f in glob.glob(os.path.join(S, 'raw', '*.json')):
    d = json.load(open(f))
    raw.update(d)

agg = {}
for v in rows.values():
    a = agg.setdefault((v['provider'], v['set']),
                       {'n_ing':0,'hit':0,'qty_ok':0,'titles':0,'imgs':0,'chars':0,'t':[],'c':[]})
    a['n_ing'] += v['n_ing']; a['hit'] += v['hit']; a['qty_ok'] += v['qty_ok']
    a['titles'] += int(v['title_ok']); a['imgs'] += 1; a['chars'] += v['chars']
    if v.get('warm_s'): a['t'].append(v['warm_s'])
    if v.get('cold_s'): a['c'].append(v['cold_s'])

fails = {}
for k, v in raw.items():
    key = (v['provider'], v['set'])
    if key not in agg:
        fails[key] = v.get('error') or v.get('fatal') or 'no output'

def rate(a): return a['hit']/a['n_ing']*100 if a['n_ing'] else 0.0

def table(image_set):
    out = ['| Provider | Ingredient recall | Quantity fidelity | Titles | Warm s/img | Cold s/img | Peak RSS |',
           '|---|---:|---:|---:|---:|---:|---:|']
    items = [(k, v) for k, v in agg.items() if k[1] == image_set]
    for (p, _), a in sorted(items, key=lambda kv: -rate(kv[1])):
        t = sum(a['t'])/len(a['t']) if a['t'] else float('nan')
        c = sum(a['c'])/len(a['c']) if a['c'] else float('nan')
        qf = a['qty_ok']/a['hit']*100 if a['hit'] else 0
        pk = peaks.get(p, '')
        out.append(f"| `{p}` | **{rate(a):.1f}%** ({a['hit']}/{a['n_ing']}) | {qf:.1f}% | {a['titles']}/{a['imgs']} | {t:.2f} | {c:.2f} | {pk} |")
    for (p, s_), err in sorted(fails.items()):
        if s_ == image_set:
            out.append(f"| `{p}` | **FAILED — 0/69** | — | 0/5 | — | — | `{str(err)[:60]}` |")
    return '\n'.join(out)

print(table('upright'))
print()
print(table('sideways'))
