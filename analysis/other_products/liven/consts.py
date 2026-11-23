import sys,json,struct,glob,os
sys.path.insert(0,'analysis'); sys.path.insert(0,'tools')
import string_refs, hw_inventory, sonicware_integrity as si
S=os.environ.get('OTHER_OUT', 'work/other/liven')
for p in sys.argv[1:]:
    b=os.path.basename(p)[:-4]
    (_,data),=list(si.inputs([__import__('pathlib').Path(p)]))
    entry,sections,_=hw_inventory.image_sections(data)
    code={}
    for v,a,_ in string_refs.constant_pairs(string_refs.disassemble(sections,entry)):
        code.setdefault(v,[]).append(a)
    img=string_refs.Image(sections,entry)
    dw={}
    for a,w in img.data_words(): dw.setdefault(w,[]).append(a)
    json.dump({'code':{hex(k):v for k,v in code.items()},'data':{hex(k):v[:50] for k,v in dw.items()}},open(f'{S}/{b}.consts.json','w'))
    print(b,len(code),len(dw))
