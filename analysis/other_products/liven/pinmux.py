import os
import sys,re,json
sys.path.insert(0,'analysis')
import c6sim
S=os.environ.get('OTHER_OUT', 'work/other/liven')
b=sys.argv[1]
b14=int(re.search(r"'b14': '(0x[0-9a-f]+)'",[l for l in open(S+'/b14.txt') if l.startswith(b+' ')][0]).group(1),16)
hw=json.load(open(f'{S}/{b}.hw.json'))
fns=sorted({int(c['function'],16) for k in ('SYSCFG0','SYSCFG1','SPI1','UART0') for c in hw['constants'].get(k,[])})
p=c6sim.Program(f'firmware/other/{b}.syx')
for f in fns:
    m=c6sim.Machine(p,{'b14':b14})
    log=[]
    orig=m.mem.write
    def w(a,d,log=log,orig=orig):
        if 0x01c00000<=a<0x02000000: log.append((a,int.from_bytes(d,'little')))
        return orig(a,d)
    m.mem.write=w
    # stub every call: return 0
    try:
        m.hooks={}
        m.run(f,max_cycles=200000)
        st='ok'
    except c6sim.SimError as e: st='err:'+str(e)[:60]
    print(hex(f), st, ' '.join(f'{a:#010x}={v:#010x}' for a,v in log[:20]))
