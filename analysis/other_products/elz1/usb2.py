import sys,struct; sys.path.insert(0,sys.argv[0].rsplit('/',1)[0])
from copytab import table
v=sys.argv[1]; args=[int(x,16) for x in sys.argv[2:6]]
im,r=table(v,*args)
mem={}
for run,n,k,d in r:
    if d: mem[run]=d
def find(pat):
    for b,d in mem.items():
        i=d.find(pat)
        while i>=0:
            yield b+i,d,i; i=d.find(pat,i+1)
for a,d,i in find(b'\x12\x01'):
    x=d[i:i+18]
    if len(x)<18 or x[2:4] not in (b'\x00\x02',b'\x10\x01',b'\x00\x01'): continue
    f=struct.unpack('<BBHBBBBHHHBBBB',x)
    print('DEV',hex(a),'bcdUSB %x cls %d/%d/%d mps %d VID %04x PID %04x bcd %x str %d/%d/%d ncfg %d'%(f[2],f[3],f[4],f[5],f[6],f[7],f[8],f[9],f[10],f[11],f[12],f[13]))
for a,d,i in find(b'\x09\x02'):
    x=d[i:i+9]
    if len(x)<9: continue
    tot=x[2]|x[3]<<8
    if not (18<=tot<400 and 1<=x[4]<=6 and x[7]&0x80): continue
    blob=d[i:i+tot]; print('CFG',hex(a),'total',tot,'ifs',x[4],'attr %x maxpower %dmA'%(x[7],x[8]*2))
    j=0
    while j<len(blob):
        L=blob[j]; t=blob[j+1] if j+1<len(blob) else None
        if L==0: break
        print('   ',blob[j:j+L].hex())
        j+=L
# string descriptors: UTF16
for a,d,i in find(b'\x04\x03\x09\x04'):
    print('LANGID',hex(a))
import binascii
for a in (0xc1318d00,0xc1318d20,0xc1318d40,0xc1318d60,0xc1318d80,0xc1318da0,0xc1318dc0, 0xc1318de0, 0xc1318e00, 0xc1318e20):
    for b,d in mem.items():
        if b<=a<b+len(d): print(hex(a), d[a-b:a-b+32].hex(' '))
