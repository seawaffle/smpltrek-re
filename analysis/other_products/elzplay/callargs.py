import sys,re,subprocess
# usage: callargs.py image target [regs]
img,tgt=sys.argv[1],sys.argv[2]
regs=(sys.argv[3] if len(sys.argv)>3 else 'a4,b4,a6,b6').split(',')
out=subprocess.run(['python3','-B','analysis/packets.py',img,'--calls',tgt,'--before','4','--after','5'],capture_output=True,text=True).stdout
sites=out.split('\n== ')
MV=re.compile(r'(?:\[[!ab0-9]+\] )?mvk[lh]? \.\w+ (-?\d+),([ab]\d+)')
OR0=re.compile(r'(?:or|mv) \.\w+X? (?:0,)?([ab]\d+),([ab]\d+)')
for s in sites[1:]:
    lines=s.split('\n'); site=lines[0].strip()
    val={}
    seen_call=False; post=[]
    for ln in lines[1:]:
        body=ln[12:] if len(ln)>12 else ln
        iscall=ln.startswith(' >>')
        parts=[p.strip() for p in body.split('||')]
        for p in parts:
            m=MV.search(p)
            if m:
                v=int(m.group(1)); r=m.group(2)
                if 'mvkh' in p: val[r]=((v>>16)<<16)|(val.get(r,0)&0xffff)
                else: val[r]=v
        if iscall:
            seen_call=True
            # for 'b' (not callp) include following packets until addkpc
            if ' callp ' in ln: break
        elif seen_call and 'addkpc' in ln: break
    print(site, ' '.join(f'{r}={val[r]:#x}' if abs(val[r])>255 else f'{r}={val[r]}' for r in regs if r in val))
