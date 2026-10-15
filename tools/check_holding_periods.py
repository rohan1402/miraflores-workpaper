import json,sys,re,datetime
from collections import defaultdict
d=json.load(open(sys.argv[1]))
ev=d['extracted_values']
v3={l['key']:l for l in d['return_versions'][2]['lines']}
for doc in ['D74','D31','D28','D35']:
    lots=defaultdict(dict)
    for e in ev:
        if e['document_id']!=doc: continue
        m=re.match(r'^([A-Z]+\d+)_(\w+)$',e['field'])
        if m: lots[m.group(1)][m.group(2)]=e['value']
    bad=[]
    for k,l in lots.items():
        acq=l.get('acq') or l.get('acquired'); sold=l.get('sold'); term=l.get('term')
        if not acq or not sold or not term: continue
        try: a=datetime.date.fromisoformat(acq); s=datetime.date.fromisoformat(sold)
        except: continue
        # long-term if held more than one year
        try: anniv=a.replace(year=a.year+1)
        except ValueError: anniv=a.replace(year=a.year+1,day=28)
        lt = s>anniv
        if (term=='long')!=lt: bad.append((k,acq,sold,term,l.get('proceeds'),l.get('basis')))
    print(doc,'lots',len(lots),'term mismatches',len(bad)); 
    for b in bad: print('  ',b)
# Meridian lot lines in v3
for k,l in v3.items():
    if re.match(r'F8949\.[A-Z]\.M\d+',k): print(k,l['label'][:150],l['value'])
