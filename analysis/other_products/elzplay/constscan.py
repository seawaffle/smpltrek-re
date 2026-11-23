import re,sys,collections
dis=sys.argv[1]; want={int(x,0) for x in sys.argv[2:]}
pend={}; out=collections.defaultdict(list)
for line in open(dis):
    m=re.match(r'\s*([0-9a-f]{8}):',line)
    if not m: continue
    for ins in line.split('||'):
        a=re.search(r'mvk[l]? \.\w+ (-?\d+),([ab]\d+)',ins)
        if a and 'mvkh' not in ins: pend[a.group(2)]=int(a.group(1))&0xffff
        h=re.search(r'mvkh \.\w+ (\d+),([ab]\d+)',ins)
        if h and h.group(2) in pend:
            v=((int(h.group(1))>>16)<<16)|pend[h.group(2)]
            if v in want: out[v].append(m.group(1))
for v,s in out.items(): print(hex(v), len(s), s[:8])
