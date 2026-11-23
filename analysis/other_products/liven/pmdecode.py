import re,sys,os
H=os.path.join(os.environ.get('STARTERWARE',os.path.expanduser('~/ti/C6748_StarterWare_1_20_04_01')),'include/hw/hw_syscfg0_C6748.h')
tok={}
for l in open(H):
    m=re.match(r'#define SYSCFG_PINMUX(\d+)_PINMUX\d+_(\d+)_(\d+)_(\w+) \((0x[0-9A-Fa-f]+)u\)',l)
    if m and m.group(4) not in ('SHIFT','DEFAULT') and not m.group(4).startswith('RESERVED'):
        tok[(int(m.group(1)),int(m.group(3)),int(m.group(5),16))]=m.group(4)
def decode(reg,val):
    out=[]
    for sh in range(0,32,4):
        f=(val>>sh)&0xf
        if f: out.append(tok.get((reg,sh,f),f'?{f}@{sh}'))
    return out
lines=sys.stdin.read().split()
seen={}
for t in lines:
    m=re.match(r'0x01c14(1[2-6][0-9a-f])=(0x[0-9a-f]+)',t)
    if m:
        reg=(int(m.group(1),16)-0x120)//4; v=int(m.group(2),16)
        seen.setdefault(reg,set()).update(decode(reg,v))
for r in sorted(seen): print(f'PINMUX{r}:',', '.join(sorted(seen[r])))
