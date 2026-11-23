import sys,struct,re,json; sys.path.insert(0,sys.argv[0].rsplit('/',1)[0])
from secs import Img
def p(lo,hi): return ((hi>>16)<<16)|(lo&0xffff)
def rle(buf,pos,is24=True):
    out=bytearray(); delim=buf[pos]; pos+=1
    while True:
        ch=buf[pos]; pos+=1
        if ch!=delim: out.append(ch); continue
        rl=buf[pos]; pos+=1
        if rl==0:
            rl=buf[pos]; pos+=1
            rl=(rl<<8)|buf[pos]; pos+=1
            if rl==0: break
            if is24 and rl<=0xff:
                for _ in range(2): rl=(rl<<8)|buf[pos]; pos+=1
            ch=buf[pos]; pos+=1
        elif rl<4: ch=delim
        else: ch=buf[pos]; pos+=1
        out+=bytes([ch])*rl
    return bytes(out)
def find_autoinit(dis):
    # find c_int00's auto_init: pattern 4 mvk/mvkh pairs; we take from argv
    pass
def table(v,H,HE,B,L):
    im=Img(v)
    sec=lambda a: next((b,d) for b,d in im.secs if b<=a<b+len(d))
    regions=[]
    for i in range((L-B)//8):
        ld,run=struct.unpack('<II',im.read(B+8*i,8))
        b,d=sec(ld); off=ld-b; h=d[off]
        if h==1:
            data=rle(d,off+1)
            regions.append((run,len(data),'rle24',data))
        elif h==0:
            cnt=struct.unpack('<I',d[(off+4)&~3 if (off+4)%4 else off+4:][:4])[0]
            regions.append((run,cnt,'zero',None))
        else:
            regions.append((run,0,'h%d'%h,None))
    return im,regions
if __name__=='__main__':
    v=sys.argv[1]; H,HE,B,L=[int(x,16) for x in sys.argv[2:6]]
    im,r=table(v,H,HE,B,L)
    for run,n,k,_ in r: print(hex(run),hex(run+n),hex(n),k)
