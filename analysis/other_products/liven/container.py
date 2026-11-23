import sys,struct,hashlib
sys.path.insert(0,'tools')
import sonicware_integrity as si
for p in sys.argv[1:]:
    raw=open(p,'rb').read()
    msgs=raw.count(b'\xf7')
    d=si.unwrap_sysex(raw)
    print('##',p.split('/')[-1],'syx',len(raw),'msgs',msgs,'devbyte',raw[6],'cmtd',len(d),'family',si.word(d,16),'hdr words',[hex(si.word(d,o)) for o in range(0,24,4)])
    for im in si.parse(d)[1:]:
        b=d[im.offset:im.offset+im.size]
        print('  ',im.tag,'ver',im.version,'off',hex(im.offset),'size',im.size, 'hdr',[hex(si.word(b,o)) for o in range(0,36,4)])
        if im.tag=='pmtd':
            n=si.word(b,28)
            for k in range(n):
                t,a,sz=struct.unpack_from('<4sII',b,32+12*k)
                print('      part',t,hex(a),sz)
