"""Run a Liven image's Hwi start-up (the function writing INTMUX 0x01800104) in c6sim and decode INTMUX/IER/ISTP."""
import os
import sys,re,json
sys.path.insert(0,'analysis')
import c6sim
S=os.environ.get('OTHER_OUT', 'work/other/liven')
b,start=sys.argv[1],int(sys.argv[2],16)
b14=int(re.search(r"'b14': '(0x[0-9a-f]+)'",[l for l in open(S+'/b14.txt') if l.startswith(b+' ')][0]).group(1),16)
p=c6sim.Program(f'firmware/other/{b}.syx')
m=c6sim.Machine(p,{'b14':b14})
m.apply_init_data(f'firmware/other/{b}.syx')
log=[]
orig=m.mem.write
def w(a,d):
    if 0x01800000<=a<0x01900000: log.append((a,int.from_bytes(d,'little')))
    return orig(a,d)
m.mem.write=w
try: m.run(start,max_cycles=2000000)
except c6sim.SimError as e: print('SimError',e)
for a,v in log: print(hex(a),hex(v))
print('ier',hex(m.g('ier')),'istp',hex(m.R.get('istp',0)), {k:hex(v) for k,v in m.R.items() if k.startswith('_')})
mux={}
for a,v in log:
    if a in (0x01800104,0x01800108,0x0180010c):
        base=4+4*((a-0x01800104)//4)
        for i in range(4): mux[base+i]=(v>>(8*i))&0x7f
print('INTSEL', mux)
