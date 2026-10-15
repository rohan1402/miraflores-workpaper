import json,sys,re,datetime
d=json.load(open(sys.argv[1]))
ev=d['extracted_values']
docs={x['id']:x for x in d['documents']}
page={(x['id'],p['page']):p['printed_content'] for x in d['documents'] for p in x['pages']}
def nums(s):
    out=set()
    for m in re.finditer(r'\(?-?\$?\d[\d,]*\.?\d*\)?',s):
        t=m.group(0); neg=t.startswith('(') or '-' in t
        t=t.strip('()$-').replace(',','').replace('$','')
        try:
            v=float(t); out.add(round(v,2)); out.add(round(-v,2))
        except: pass
    return out
def datestrs(v):
    try: dt=datetime.date.fromisoformat(v)
    except: return [v]
    return [dt.strftime('%m/%d/%Y'),dt.isoformat(),dt.strftime('%B %-d, %Y'),dt.strftime('%b %-d, %Y'),f'{dt.month}/{dt.day}/{dt.year}',dt.strftime('%m/%d/%y'),f'{dt.month}/{dt.day}/{dt.strftime("%y")}']
bad=[]
for e in ev:
    pc=page.get((e['document_id'],e['page']),'')
    v=e['value']; t=e['value_type']
    if v is None: continue
    ok=True
    if t in ('money','integer','quantity','percent'):
        ok = round(float(v),2) in nums(pc) or (t=='percent' and round(float(v)*100,2) in nums(pc))
    elif t=='date':
        ok = any(s in pc for s in datestrs(v))
    elif t in ('text','code','ein','ssn','account_number'):
        ok = str(v).lower() in pc.lower() or (e['text_as_read'] and e['text_as_read'].lower() in pc.lower())
    if not ok: bad.append(e)
print('values not found on printed page:',len(bad))
from collections import Counter
print(Counter(e['document_id'] for e in bad).most_common())
for e in bad[:80]:
    print(' ',e['id'],e['document_id'],'p',e['page'],e['field'],'|',e['label'],'| val',e['value'],'| read',repr(e['text_as_read']),'| conf',e['confidence'])
