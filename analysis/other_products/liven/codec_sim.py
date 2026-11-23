"""Simulate the Liven codec start-up function (caller of codec_reset) and record codec_write(reg b4, val a6)."""
import os
import sys,re
sys.path.insert(0,'analysis')
import c6sim, codec_map
S=os.environ.get('OTHER_OUT', 'work/other/liven')
b, start = sys.argv[1], int(sys.argv[2],16)
car={l.split()[1]:int(l.split()[0],16) for l in open(f'{S}/{b}.carried.txt')}
b14=int(re.search(r"'b14': '(0x[0-9a-f]+)'",[l for l in open(S+'/b14.txt') if l.startswith(b+' ')][0]).group(1),16)
p=c6sim.Program(f'firmware/other/{b}.syx')
writes=[]; calls=[]
def cw(m):
    writes.append((m.g('b4'), m.g('a6')&0xff, hex(m.g('a4')))); m.R['a4']=1; return m.R['b3']
hooks={car['codec_write']:cw}
for extra in sys.argv[3:]:
    hooks[int(extra,16)]=c6sim.returns(0)
m=c6sim.Machine(p,{'b14':b14,'a4':0x01C22000},hooks=hooks)
m.apply_init_data(f'firmware/other/{b}.syx')
try:
    m.run(start, max_cycles=3000000)
except c6sim.SimError as e:
    print('SimError',e)
print(b, 'writes', len(writes))
print(' '.join(f'{r}=0x{v:02X}' for r,v,_ in writes))
print('bases', set(x[2] for x in writes))
print('calls', [(hex(s),hex(t)) for s,t,a4,b4 in m.calls][:60])
if True:
    for pg,reg,val,name,mean in codec_map.decode([(r,v) for r,v,_ in writes]):
        print(f'   p{pg} r{reg:3d}=0x{val:02X} {name}: {mean}')
