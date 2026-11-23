import sys,struct,re; sys.path.insert(0,sys.argv[0].rsplit('/',1)[0])
from copytab import table
from findinit import consts
inits={l.split()[0]:[int(x,16) for x in l.split()[2:]] for l in open('inits.txt')}
for v in ['2.0','2.1','3.0','4.0','5.0','6.0','7.0']:
    im,r=table(v,*inits[v])
    mem={run:d for run,n,k,d in r if d}
    code=[(b,b+len(d)) for b,d in im.secs if b<=im.entry<b+len(d)][0]
    print('=====',v,'entry',hex(im.entry),'text %x-%x'%code,'(%.2f MiB)'%((code[1]-code[0])/1048576))
    for run,n,k,d in r: print('   region',hex(run),hex(n),k)
    L=open(f'dis-{v}.txt').read().split('\n')
    C=consts(L)
    from collections import Counter
    cnt=Counter(val for a,rg,val in C)
    print('   const 48000:',cnt[48000],'44100:',cnt[44100],'48000.0f:',cnt[0x473b8000],'1/48000f:',cnt[0x37aec33e],'0x01E13000(LCDC):',cnt[0x01e13000],'153600:',cnt[153600],'186000000:',cnt[186000000],'15000000:',cnt[15000000],'0x220045:',cnt[0x220045],'24000000:',cnt[24000000])
    # LCD init: mvk 0x5555 count and mvk 21845
    # dir/ext table
    def findmem(pat):
        out=[]
        for b,d in mem.items():
            i=d.find(pat)
            while i>=0: out.append(b+i); i=d.find(pat,i+1)
        return out
    s=im.find(b'MEMORY\0*.e1m\0')
    if s:
        p=findmem(struct.pack('<I',s[0]))
        if p:
            b=[bb for bb in mem if bb<=p[0]<bb+len(mem[bb])][0]
            ws=struct.unpack_from('<8I',mem[b],p[0]-b)
            print('   dir table',hex(p[0]),[im.read(w,12).split(b'\0')[0].decode() for w in ws])
    # PaRAM templates: search const for SRC/DST 0x01d02000 with ACNT 4
    for b,d in im.secs:
        for i in range(0,len(d)-32,4):
            o,s1,ab,dst=struct.unpack_from('<4I',d,i)
            if (s1==0x01d02000 or dst==0x01d02000) and (ab&0xffff)==4 and o&0xffff0000 in (0x00100000,0):
                print('   PaRAM',hex(b+i),'OPT %08x SRC %08x ACNT %d BCNT %d DST %08x'%(o,s1,ab&0xffff,ab>>16,dst))
    # USB
    for b,d in mem.items():
        for m in re.finditer(rb'\x12\x01\x00\x02',d):
            x=d[m.start():m.start()+18]; f=struct.unpack('<BBHBBBBHHHBBBB',x)
            print('   USBdev',hex(b+m.start()),'VID %04x PID %04x str %d/%d/%d'%(f[7],f[8],f[10],f[11],f[12]))
        for m in re.finditer(rb'\x09\x02(.)\x00(.)\x01',d,re.S):
            print('   USBcfg',hex(b+m.start()),d[m.start():m.start()+9].hex())
    # Task objects stride 76
    for b,d in mem.items():
        for off in range(0,len(d)-76,4):
            w=struct.unpack_from('<19I',d,off)
            pri=struct.unpack('<i',struct.pack('<I',w[2]))[0]
            if code[0]<=w[10]<code[1] and -1<=pri<=31 and w[5]<=4 and 256<=w[7]<=0x40000 and w[7]%8==0 and 0xc0000000<=w[8]<0xc4000000:
                print('   Task',hex(b+off),'pri',pri,'stack',w[7],'fxn',hex(w[10]))
