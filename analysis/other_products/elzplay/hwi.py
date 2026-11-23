import sys,struct
sys.path.insert(0,'analysis')
import init_data
img,ms,code_lo,code_hi=sys.argv[1],int(sys.argv[2],16),int(sys.argv[3],16),int(sys.argv[4],16)
D=init_data.InitData(img)
w=D.word
ev=[]
for i in range(0,16,4):
    x=w(ms+i); ev+= [ (x>>(8*k))&0xff for k in range(4)]
print('ISTP', hex(w(ms+32)))
for n in range(4,16):
    h=w(ms+44+4*n)
    e=ev[n]; e = e-256 if e>127 else e
    fx=None; words=[]
    if h and h!=0xffffffff:
        words=[w(h+4*k) for k in range(10)]
        fx=[hex(x) for x in words if code_lo<=x<code_hi]
    print(f'int {n:2d} event {e:4d} handle {h:#x} code-ptrs {fx}')
