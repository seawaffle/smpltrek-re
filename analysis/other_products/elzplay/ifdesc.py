import sys,struct
raw=open(sys.argv[1],'rb').read()
shoff,=struct.unpack_from('<I',raw,0x20); shentsize,shnum=struct.unpack_from('<HH',raw,0x2e)
CLS={1:'Audio',3:'HID',8:'MSC',2:'CDC',0xff:'vendor'}
for k in range(shnum):
    nm,typ,fl,addr,off,size=struct.unpack_from('<6I',raw,shoff+k*shentsize)
    if typ!=1 or fl&4: continue
    d=raw[off:off+size]
    for i in range(len(d)-9):
        if d[i]==9 and d[i+1]==4 and d[i+5] in CLS and d[i+4]<=4 and d[i+2]<8 and d[i+3]<4:
            print(f'IF @{addr+i:#x} if{d[i+2]} alt{d[i+3]} nEP{d[i+4]} class {CLS[d[i+5]]} sub {d[i+6]} proto {d[i+7]}')
        if d[i]==9 and d[i+1]==2 and d[i+4]<=8 and d[i+5]>=1 and d[i+5]<=4:
            print(f'CFG @{addr+i:#x} total {struct.unpack_from("<H",d,i+2)[0]} nIF {d[i+4]} val {d[i+5]} attr {d[i+7]:#x} power {d[i+8]*2}mA')
        if d[i] in (7,9) and d[i+1]==5 and (d[i+2]&0x70)==0 and d[i+2]&0xf and d[i+3]<4:
            mps=struct.unpack_from('<H',d,i+4)[0]
            if mps in (8,16,32,64,196,192,288,294,384,512,576,1023): print(f'  EP @{addr+i:#x} addr {d[i+2]:#04x} attr {d[i+3]:#x} mps {mps} interval {d[i+6]}')
        if d[i]==0x0c and d[i+1]==0x24 and d[i+2]==2:
            print(f'  AC input terminal @{addr+i:#x} id {d[i+3]} type {struct.unpack_from("<H",d,i+4)[0]:#06x} nch {d[i+7]}')
        if d[i]==0x0b and d[i+1]==0x24 and d[i+2]==2 and d[i+3]==1:
            print(f'  AS format I @{addr+i:#x} ch {d[i+4]} subframe {d[i+5]} bits {d[i+6]} nfreq {d[i+7]} freq {d[i+8]|d[i+9]<<8|d[i+10]<<16}')
