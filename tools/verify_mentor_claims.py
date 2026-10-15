import json,sys
d=json.load(open(sys.argv[1]))
ev=d['extracted_values']; evi={e['id']:e for e in ev}
docs={x['id']:x for x in d['documents']}
v1,v2,v3=d['return_versions']
L3={l['key']:l for l in v3['lines']}
print('conf>=0.99:',sum(e['confidence']>=0.99 for e in ev),'| conf<0.80:',sum(e['confidence']<0.8 for e in ev), [ (e['id'],e['document_id'],e['label'],e['value'],e['confidence']) for e in ev if e['confidence']<0.8])
print('D09 box15/16/17:',[(e['field'],e['value'],e['confidence']) for e in ev if e['document_id']=='D09' and e['field'].startswith(('box15','box16','box17'))])
qs=d['client']['questionnaire']; print('last qa:',qs[-1]['id'],qs[-1]['question'],'->',qs[-1]['answer'])
q41=[q for q in qs if q['id']=='qa-41']; print('qa-41:',q41)
est=[l for l in v3['lines'] if 'estimat' in l['label'].lower()]
for l in est: print('EST LINE',l['key'],l['label'],l['value'],l['sources'],l['inputs'])
print('IRS transcript:',json.dumps(d['tax_agency_records']['irs_account_transcript_2025'])[:900])
for i in ['D67','D68','D10','D30','D31','D07','D69','D70','D72','D74']:
    x=docs[i]; print(i,x['title'],'| ty',x['tax_year'],'| extr',x['extraction'],'| corrected',x.get('marked_corrected'),'| pages',x['page_count'])
print('D67 pages:',[p['printed_content'][:250] for p in docs['D67']['pages']])
print('D68 evs:',[(e['field'],e['value'],e['confidence']) for e in ev if e['document_id']=='D68'])
print('FTB:',json.dumps(d['tax_agency_records']['ftb_account'])[:700])
ca_pay=[l for l in v3['lines'] if l['jurisdiction']=='california' and ('payment' in l['label'].lower() or 'estimat' in l['label'].lower())]
for l in ca_pay: print('CA PAY',l['key'],l['label'],l['value'],l['sources'])
for dg in v3['diagnostics']+v1['diagnostics']:
    if '71' in dg['message'] or 'Ironwood' in dg['message'] or 'summary' in dg['message'].lower(): print('DIAG',dg['code'],dg['message'][:250])
p32=[p for p in docs['D31']['pages'] if p['page']==32] or [p for p in docs['D30']['pages'] if p['page']==32]
print('page32:',[p['printed_content'][:300] for p in p32])
print('v2->v3 changes:',len(v3['changes_from_previous']),'| v1->v2:',len(v2['changes_from_previous']))
print('F8949 lines v3:',sum(1 for l in v3['lines'] if l['form']=='F8949'))
print('D74 values:',sum(1 for e in ev if e['document_id']=='D74'))
py=d['prior_years']['return_2024']['lines']; print('2024 AGI',py.get('F1040.11'),'wages',py.get('F1040.1a'),'| 2025 AGI',L3['F1040.11']['value'],'wages',L3['F1040.1a']['value'])
print('variance std:',d['firm']['starter_standards']['variance_review'])
print('verification types:',d['firm']['starter_standards']['verification_types'])
print('rules:',d['firm']['starter_standards']['rules'])
print('required steps:',d['firm']['starter_standards']['required_steps'])
print('staff:',[(s['id'],s['name'],s['role'],s['sensitive_data_clearance']) for s in d['firm']['staff']])
print('residency:',d['household']['residency'])
