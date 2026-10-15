import json,sys
d=json.load(open(sys.argv[1]))
docs={x['id']:x for x in d['documents']}
for spec in sys.argv[2:]:
    did,_,pg=spec.partition(':')
    x=docs[did]
    print('=====',did,x['title'],'| type',x['document_type'],'| issuer',x['issuer'],'| belongs',x['belongs_to'],'| ty',x['tax_year'],'| recv',x['received_at'],'| corrected',x.get('marked_corrected'),'| extr',x['extraction'])
    for p in x['pages']:
        if pg and str(p['page'])!=pg: continue
        print(' p',p['page'],':',p['printed_content'])
