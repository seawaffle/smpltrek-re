import sys,re,subprocess,difflib
def get(elf,a,n):
    t=subprocess.run(['tools/tic6x/bin/tic6x-elf-objdump','-d',f'--start-address={a:#x}',f'--stop-address={a+n:#x}',elf],capture_output=True,text=True).stdout
    out=[]
    for l in t.splitlines():
        m=re.match(r'\s*([0-9a-f]{8}):\s+[0-9a-f]+\s+(.*)$',l)
        if not m or 'fetch packet' in l: continue
        ins=re.sub(r'\s*\|\| nop \d+$','',m.group(2))
        ins=re.sub(r'[0-9a-f]{8} <[^>]*>','T',ins)
        out.append(ins)
    return out
a=get(sys.argv[1],int(sys.argv[2],16),int(sys.argv[5],0)); b=get(sys.argv[3],int(sys.argv[4],16),int(sys.argv[5],0))
d=[x for x in difflib.unified_diff(a,b,lineterm='',n=0) if x[:1] in '+-' and not x.startswith(('+++','---'))]
print(len(a),len(b),'difflines',len(d)); print('\n'.join(d[:30]))
