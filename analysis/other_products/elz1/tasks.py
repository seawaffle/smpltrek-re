import sys,struct; sys.path.insert(0,sys.argv[0].rsplit('/',1)[0])
from copytab import table
v=sys.argv[1]; args=[int(x,16) for x in sys.argv[2:6]]
im,r=table(v,*args)
code=[(b,b+len(d)) for b,d in im.secs if b<=im.entry<b+len(d)][0]
for run,n,k,d in r:
    if not d: continue
    for off in range(0,len(d)-92,4):
        w=struct.unpack_from('<23I',d,off)
        pri=struct.unpack('<i',struct.pack('<I',w[2]))[0]
        fxn=w[10]; ss=w[7]; st=w[8]
        if code[0]<=fxn<code[1] and -1<=pri<=31 and w[5]<=4 and 256<=ss<=0x40000 and ss%8==0 and 0xc0000000<=st<0xc4000000:
            print(hex(run+off),'pri',pri,'mode',w[5],'stack',hex(st),'size',ss,'fxn',hex(fxn),'arg0',hex(w[11]),'arg1',hex(w[12]))
