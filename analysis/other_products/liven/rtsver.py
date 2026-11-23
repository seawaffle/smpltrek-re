import json,sys,glob
S=sys.argv[1]
for b in sorted(set(p.split('/')[-1].split('.rts-')[0] for p in glob.glob(S+'/*.rts-*.json'))):
    row={}
    sets={}
    for v in ['8.3.2','8.3.9','8.3.10','8.3.13','8.5.0.LTS']:
        j=json.load(open(f'{S}/{b}.rts-{v}.json'))
        u=[f for f in j['functions'] if len(f['matches'])==1]
        row[v]=(len(u),sum(f['size'] for f in u))
        sets[v]={f['name'] for f in u}
    print(b, ' '.join(f'{v}:{n}/{sz}' for v,(n,sz) in row.items()))
    print('   only 8.3.13:',sorted(sets['8.3.13']-sets['8.3.10'])[:12])
    print('   only 8.3.10:',sorted(sets['8.3.10']-sets['8.3.13'])[:12])
    print('   only 8.3.9 vs 8.3.2:',sorted(sets['8.3.9']-sets['8.3.2'])[:8], 'only 8.3.2:',sorted(sets['8.3.2']-sets['8.3.9'])[:8])
