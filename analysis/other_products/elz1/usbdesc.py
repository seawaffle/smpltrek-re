import sys; sys.path.insert(0,sys.argv[0].rsplit('/',1)[0])
from secs import Img
im=Img(sys.argv[1])
for pat in [b'\x12\x01\x00\x02',b'\x12\x01\x10\x01',b'\x12\x01\x00\x01']:
    for a in im.find(pat):
        d=im.read(a,18)
        import struct
        f=struct.unpack('<BBHBBBBHHHBBBB',d)
        print(hex(a),'bcdUSB %x class %d/%d/%d mps %d VID %04x PID %04x bcdDev %x'%(f[2],f[3],f[4],f[5],f[6],f[7],f[8],f[9]))
# config descriptors
for a in im.find(b'\x09\x02'):
    d=im.read(a,9)
    if d and len(d)==9 and d[4] in range(1,8) and d[7]&0x80 and d[8]<=250 and d[2]+d[3]*256<600 and d[2]>=18:
        print('cfg?',hex(a),d.hex())
