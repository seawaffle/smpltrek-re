import sys,struct
sys.path.insert(0,'analysis')
import mmtd2elf,zipfile
def load(v):
    z=zipfile.ZipFile(f'firmware/other/ELZ_1 v{v}.zip')
    n=[x for x in z.namelist() if x.endswith('ELZ_1.bin') and 'MACOSX' not in x][0]
    return mmtd2elf.mmtd_sections(z.read(n))
class Img:
    def __init__(s,v):
        s.ver,s.entry,s.secs=load(v)
    def read(s,a,n):
        for b,d in s.secs:
            if b<=a<b+len(d): return d[a-b:a-b+n]
    def find(s,pat):
        out=[]
        for b,d in s.secs:
            i=d.find(pat)
            while i>=0:
                out.append(b+i); i=d.find(pat,i+1)
        return out
