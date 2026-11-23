import sys,struct
sys.path.insert(0,'tools'); sys.path.insert(0,'analysis')
raw=open(sys.argv[1],'rb').read()
shoff,=struct.unpack_from('<I',raw,0x20); shentsize,shnum=struct.unpack_from('<HH',raw,0x2e)
secs=[]
for k in range(shnum):
    nm,typ,fl,addr,off,size=struct.unpack_from('<6I',raw,shoff+k*shentsize)
    if typ==1: secs.append((addr,raw[off:off+size]))
for base,d in secs:
    i=0
    while True:
        i=d.find(b'\x12\x01',i)
        if i<0: break
        if i+18<=len(d) and d[i+2:i+4] in (b'\x00\x02',b'\x10\x01',b'\x00\x01') and d[i+7] in (8,16,32,64):
            v,p=struct.unpack_from('<HH',d,i+8)
            print(f'device desc @{base+i:#x}: bcdUSB {d[i+3]:x}.{d[i+2]:02x} class {d[i+4]} sub {d[i+5]} proto {d[i+6]} mps {d[i+7]} VID {v:#06x} PID {p:#06x} bcdDev {d[i+13]:x}.{d[i+12]:02x} iMfr {d[i+14]} iProd {d[i+15]} iSer {d[i+16]} nCfg {d[i+17]}')
        i+=1
    # string descriptors: UTF-16LE with bLength/bDescriptorType 3
    i=0
    while True:
        i=d.find(b'\x03',i)
        if i<0: break
        L=d[i-1] if i>0 else 0
        if L>=6 and L%2==0 and i-1+L<=len(d):
            raw=d[i+1:i-1+L]
            if all(raw[k+1]==0 and 32<=raw[k]<127 for k in range(0,len(raw),2)):
                print(f'string desc @{base+i-1:#x}: {raw.decode("utf-16le")!r}')
        i+=1
