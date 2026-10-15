import json,sys,re
from collections import defaultdict
d=json.load(open(sys.argv[1]))
ev=d['extracted_values']; docs={x['id']:x for x in d['documents']}
def evs(doc): return [e for e in ev if e['document_id']==doc]
# D30 vs D31 differences
a={e['field']:e['value'] for e in evs('D30')}; b={e['field']:e['value'] for e in evs('D31')}
print('D30 vs D31 field diffs:')
for k in sorted(set(a)|set(b)):
    if a.get(k)!=b.get(k): print('  ',k,a.get(k),'->',b.get(k))
# summary fields D31 and D74
for doc in ['D31','D74','D28']:
    s=[e for e in evs(doc) if not re.match(r'^[A-Z]+\d+_',e['field'])]
    print(doc,'non-lot fields:',[(e['field'],e['value']) for e in s][:40])
# Brightpath lots tie
lots=defaultdict(dict)
for e in evs('D74'):
    m=re.match(r'^([A-Z]+\d+)_(\w+)$',e['field'])
    if m: lots[m.group(1)][m.group(2)]=e['value']
print('D74 lots',len(lots),'fields',sorted({k for l in lots.values() for k in l}))
tot=defaultdict(float)
for l in lots.values():
    for k in ('proceeds','basis','wash'):
        if isinstance(l.get(k),(int,float)): tot[k]+=l[k]
print('D74 lot sums',{k:round(v,2) for k,v in tot.items()})
# term split
st=defaultdict(float)
for l in lots.values(): st[(l.get('term'),l.get('covered'))]+=l.get('proceeds') or 0
print('D74 by term/covered',dict(st))
print([p['printed_content'][:600] for p in docs['D74']['pages'][:1]])
print([p['printed_content'][:600] for p in docs['D74']['pages'][-1:]])
