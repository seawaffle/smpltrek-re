import sys,struct,zipfile,zlib,collections
def load(p):
    z=zipfile.ZipFile(p)
    n=[x for x in z.namelist() if x.endswith('ELZ_1.bin') and 'MACOSX' not in x][0]
    return z.read(n)
for p in sys.argv[1:]:
    d=load(p)
    print('==',p,len(d),'hdr',[hex(x) for x in struct.unpack_from('<5I',d,0)])
    n=struct.unpack_from('<I',d,0x10)[0]
    for i in range(n):
        k,a,b,c,off,sz=struct.unpack_from('<6I',d,0x14+24*i)
        img=d[off:off+sz]
        print(' desc',i,'kind',k,'ver %d.%d.%d'%(a,b,c),'off',hex(off),'size',hex(sz),img[:4], [hex(x) for x in struct.unpack_from('<8I',img,4)])
        if img[:4]==b'pmtd':
            # dump header words
            w=struct.unpack_from('<16I',img,0)
            print('   pmtd words',[hex(x) for x in w])
    for i in range(n):
        k,a,b,c,off,sz=struct.unpack_from('<6I',d,0x14+24*i)
        img=d[off:off+sz]
        if img[:4]==b'pmtd':
            cnt=struct.unpack_from('<I',img,28)[0]
            for j in range(cnt):
                t,o,s=struct.unpack_from('<4sII',img,32+12*j)
                body=img[o:o+s]
                print('   part',t,hex(o),hex(s),'head',body[:16].hex())
