import json,sys,re
d=json.load(open(sys.argv[1]))
pat=re.compile(sys.argv[2])
evi={e['id']:e for e in d['extracted_values']}
vs=d['return_versions']
L={v['version']:{l['key']:l for l in v['lines']} for v in vs}
keys=[k for k in L['v3'] if pat.search(k) or pat.search(L['v3'][k]['label'])]
for k in keys:
    l=L['v3'][k]
    vals=[L[v].get(k,{}).get('value') for v in ('v1','v2','v3')]
    srcs=[(s, evi[s]['document_id']+':'+evi[s]['field']+'='+str(evi[s]['value'])) if s in evi else s for s in l['sources']]
    print(k,'|',l['label'],'| v1/v2/v3',vals,'| rule',l['rule'],'| in',l['inputs'][:8],'| src',srcs[:6], '| note',l.get('note',''))
