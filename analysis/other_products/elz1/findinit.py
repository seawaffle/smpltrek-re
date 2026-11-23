import re,sys
def consts(lines):
    pend={};out=[]
    for l in lines:
        m=re.match(r'\s*([0-9a-f]+):\s+\S+\s+(?:\|\|\s*)?(?:\[!?[ab]\d+\]\s*)?(mvkl?|mvkh)\s+\.\S+\s+(-?\d+),([ab]\d+)',l)
        if not m: continue
        a,op,v,r=m.groups(); v=int(v)
        if op!='mvkh': pend[r]=v
        elif r in pend: out.append((a,r,((v>>16)<<16)|(pend.pop(r)&0xffff)))
    return out
if __name__=='__main__':
  v=sys.argv[1]
  L=open(f'dis-{v}.txt').read().split('\n')
  for i,l in enumerate(L):
      if 'cmpltu .L1 a3,a4,a0' in l and i>12:
          c=consts(L[i-14:i+1])
          regs={r:val for a,r,val in c}
          if all(k in regs for k in ('a3','a4','b4','b5')) and regs['a3']<regs['a4']<regs['b4']<regs['b5']:
              print(v,l.split(':')[0].strip(),' '.join(hex(regs[k]) for k in ('a3','a4','b4','b5')))
