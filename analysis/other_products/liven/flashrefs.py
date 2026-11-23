import os
import json,re,subprocess,sys
S=os.environ.get('OTHER_OUT', 'work/other/liven'); b=sys.argv[1]
j=json.load(open(f'{S}/{b}.consts.json'))
dis=open(f'{S}/{b}.dis').read().splitlines()
idx={}
for i,l in enumerate(dis):
    m=re.match(r'([0-9a-f]{8}):',l)
    if m: idx[int(m.group(1),16)]=i
for k,v in sorted(j['code'].items(), key=lambda kv:int(kv[0],16)):
  x=int(k,16)
  if 0x10000<=x<0x01000000 and x%0x1000==0:
    for a in v:
      a=int(a) if not isinstance(a,str) else int(a,16)
      i=idx.get(a); tg=[]
      for l in dis[i:i+25]:
        m=re.search(r'(callp|\sb) \.S[12] (c[0-9a-f]{7})',l)
        if m: tg.append(m.group(2))
        if len(tg)>=2: break
      print(hex(x), hex(a), tg)
