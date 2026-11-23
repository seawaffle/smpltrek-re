import os
import json,sys,subprocess,re
S=os.environ.get('OTHER_OUT', 'work/other/liven')
for b in sys.argv[1:]:
    j=json.load(open(f'{S}/../other/{b}.rtti.json'))
    for c in j['classes']:
        n=c['name']
        if '__func' in n and 'receiveSystemExclusiveMessage' in n:
            op=int(c['vtables'][0]['entries'][6],16)
            out=subprocess.run(['python3','-B','analysis/packets.py',f'firmware/other/{b}.syx',hex(op),'--count','2'],capture_output=True,text=True).stdout
            m=re.search(r'\bb \.S\d (c[0-9a-f]+)',out)
            tgt=m.group(1) if m else '?'
            out2=subprocess.run(['python3','-B','analysis/packets.py',f'firmware/other/{b}.syx','0x'+tgt,'--count','14'],capture_output=True,text=True).stdout
            ks=re.findall(r'(mvk \.\w+ (?:96|9[0-9]|1[0-9][0-9]),\w+|cmpeq \.\w+ \d+,\w+,\w+)',out2)
            print(b, n[n.find('<')+1:n.find('::{')], 'op',hex(op),'->',tgt, ks[:14])
