import subprocess,re,sys,glob,os
OBJ='tools/tic6x/bin/tic6x-elf-objdump'
ent={}
for log in sorted(glob.glob(sys.argv[1]+'/*.elf.log')):
    b=os.path.basename(log).split('.elf')[0]
    e=int(re.search(r'entry (0x[0-9a-f]+)',open(log).read()).group(1),16)
    out=subprocess.run([OBJ,'-d',f'--start-address={e}',f'--stop-address={e+0x80}',sys.argv[1]+f'/{b}.elf'],capture_output=True,text=True).stdout
    lo={}
    res={}
    for l in out.splitlines():
        m=re.search(r'\tmvk(l?)\s+\S+\s+(-?\d+),(b1[45])',l)
        if m: lo[m.group(3)]=int(m.group(2))&0xffff
        m=re.search(r'\tmvkh\s+\S+\s+(-?\d+),(b1[45])',l)
        if m and m.group(2) in lo:
            res[m.group(2)]=((int(m.group(1))&0xffffffff)>>16<<16)|lo[m.group(2)]
    print(b,hex(e),{k:hex(v) for k,v in res.items()})
