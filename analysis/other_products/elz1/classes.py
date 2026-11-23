import os
import json,sys,subprocess
R='work/other/rtti/'  # rtti_recover.py JSON per legacy release
def demangle(m):
    return subprocess.run(['c++filt','-t','_Z'+('N' if False else '')+m],capture_output=True,text=True).stdout.strip()
vers=['2.0','2.1','3.0','4.0','5.0','6.0','7.0']
sets={}
names={}
for v in vers:
    d=json.load(open(R+f'ELZ_1_v{v}.rtti.json'))
    s=set()
    for c in d['classes']:
        n=c.get('name') or c['mangled']
        s.add(n)
    sets[v]=s
import pickle
json.dump({v:sorted(s) for v,s in sets.items()},open(os.environ.get('OTHER_OUT', 'work/other/elz1') + '/classes.json','w'),indent=0)
prev=None
for v in vers:
    if prev:
        print(f'== {prev} -> {v}: +{len(sets[v]-sets[prev])} -{len(sets[prev]-sets[v])}')
        print('  +',sorted(sets[v]-sets[prev]))
        print('  -',sorted(sets[prev]-sets[v]))
    prev=v
