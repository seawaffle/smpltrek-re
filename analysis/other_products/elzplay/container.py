import sys,struct,zipfile
for p in sys.argv[1:]:
    z=zipfile.ZipFile(p)
    for n in z.namelist():
        if n.startswith('__MACOSX') or n.endswith('/'): continue
        d=z.read(n)
        print('==',p.split('/')[-1],n,len(d),d[:4])
        if d[:4]!=b'cmtd':
            # contents file: show first header words
            print('  head',d[:64].hex()); 
            # scan chunk tags top-level
            continue
        w=lambda o:struct.unpack_from('<I',d,o)[0]
        print('  cmtd words', [hex(w(o)) for o in range(0,24,4)])
        cnt=w(20)
        for i in range(cnt):
            kind,ma,mi,b,off,sz=struct.unpack_from('<6I',d,24+24*i)
            tag=d[off:off+4]
            print(f'  img kind {kind} {tag} v{ma}.{mi}.{b} off {off:#x} size {sz:#x} hdr',[hex(w(off+o)) for o in range(0,36,4)])
            if tag==b'pmtd':
                np=w(off+28)
                for k in range(np):
                    e=d[off+32+12*k:off+44+12*k]
                    print('    part',e[:4],[hex(x) for x in struct.unpack_from('<2I',e,4)])
