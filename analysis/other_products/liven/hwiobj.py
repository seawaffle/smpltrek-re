import sys
sys.path.insert(0,'analysis')
import init_data
b=sys.argv[1]
d=init_data.InitData(f'firmware/other/{b}.syx')
def word(a):
    for r in d.regions:
        if r['kind']=='initialised' and r['start']<=a<r['start']+len(r['data'])-3:
            o=a-r['start']; return int.from_bytes(r['data'][o:o+4],'little')
    return None
for r in d.regions:
    if r['kind']!='initialised': continue
    i=r['data'].find((0x4b3d0824).to_bytes(4,'little'))
    if i>=0:
        ms=r['start']+i-4
        print(b,'module state',hex(ms),'istp',hex(word(ms+32)))
        for n in range(16):
            h=word(ms+44+4*n)
            if h:
                obj=[word(h+4*k) for k in range(8)]
                print('  int',n,'obj',hex(h),[hex(x) if x is not None else None for x in obj])
