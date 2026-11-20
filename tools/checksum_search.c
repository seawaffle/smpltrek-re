// Broad checksum search: for each image (from manifest), compute many candidate
// algorithms over several byte ranges/paddings and report any (algo,range,pad,final)
// combination that matches the stored check on >= MINHIT images of the same tag.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
typedef struct { char path[512]; char tag[8]; long off, size, hdr; uint32_t chk; } Img;
static uint32_t rev32(uint32_t x){x=((x>>1)&0x55555555)|((x&0x55555555)<<1);x=((x>>2)&0x33333333)|((x&0x33333333)<<2);x=((x>>4)&0x0f0f0f0f)|((x&0x0f0f0f0f)<<4);return (x>>24)|((x>>8)&0xff00)|((x<<8)&0xff0000)|(x<<24);}
static uint32_t bswap(uint32_t x){return (x>>24)|((x>>8)&0xff00)|((x<<8)&0xff0000)|(x<<24);}
static const uint32_t POLYS[]={0x04C11DB7,0x1EDC6F41,0x814141AB,0xA833982B,0x741B8CD7,0x32583499,0x000000AF,0x8001801B,0xF4ACFB13,0x04C11DB6,0x80000011};
#define NPOLY (sizeof(POLYS)/sizeof(POLYS[0]))
static uint32_t tab[NPOLY][2][256];
static void mktabs(void){
  for(unsigned p=0;p<NPOLY;p++){
    uint32_t poly=POLYS[p], rpoly=rev32(poly);
    for(int i=0;i<256;i++){
      uint32_t c=(uint32_t)i<<24; for(int k=0;k<8;k++) c=(c&0x80000000)?(c<<1)^poly:(c<<1); tab[p][0][i]=c;
      uint32_t r=i; for(int k=0;k<8;k++) r=(r&1)?(r>>1)^rpoly:(r>>1); tab[p][1][i]=r;
    }
  }
}
// algorithms: index layout
enum { A_W31, A_W33, A_W65599, A_WFNV, A_WXORROT, A_SUM8, A_SUM16LE, A_SUM16BE, A_SUM32LE, A_SUM32BE, A_XOR32LE, A_XOR8, A_ONES32LE, A_FLETCH32, A_ADLER32, A_BSD32, A_SUM32LE_HI, A_DJB2, A_SDBM, A_FNV1A, A_FNV1, A_NCRC };
static const char* ANAME[]={"wh*31+w","wh*33+w","wh*65599+w","wfnv","wrotl1^w","sum8","sum16le","sum16be","sum32le","sum32be","xor32le","xor8","ones32le","fletcher32","adler32","bsd32","sum32le_withcarryhi","djb2","sdbm","fnv1a","fnv1"};
#define NALG (A_NCRC + NPOLY*2*2)   // crc: poly x refl x init(0/FF)
static void algname(int a,char*out){ if(a<A_NCRC){strcpy(out,ANAME[a]);return;} int c=a-A_NCRC; int p=c/4, refl=(c/2)%2, init=c%2; sprintf(out,"crc32 poly=%08x %s init=%s",POLYS[p],refl?"refl":"norm",init?"FFFFFFFF":"0");}
static void compute_all(const uint8_t*b,long n,uint32_t*out){
  uint64_t s8=0,s16le=0,s16be=0,s32le=0,s32be=0; uint32_t x32=0,x8=0; uint64_t ones=0;
  uint32_t f1=0,f2=0; uint32_t ad_a=1,ad_b=0; uint32_t bsd=0, djb=5381, sdbm=0, fnva=0x811C9DC5, fnv=0x811C9DC5;
  uint32_t crc[NPOLY][2][2];
  for(unsigned p=0;p<NPOLY;p++) for(int r=0;r<2;r++){crc[p][r][0]=0;crc[p][r][1]=0xFFFFFFFF;}
  long n4=n&~3L;
  for(long i=0;i<n;i++){ uint8_t c=b[i]; s8+=c; x8^=c; bsd=((bsd>>1)|(bsd<<31))+c; djb=djb*33+c; sdbm=c+(sdbm<<6)+(sdbm<<16)-sdbm; fnva=(fnva^c)*16777619u; fnv=(fnv*16777619u)^c;
    for(unsigned p=0;p<NPOLY;p++){ for(int k=0;k<2;k++){ crc[p][0][k]=(crc[p][0][k]<<8)^tab[p][0][((crc[p][0][k]>>24)^c)&0xff]; crc[p][1][k]=(crc[p][1][k]>>8)^tab[p][1][(crc[p][1][k]^c)&0xff]; } }
  }
  for(long i=0;i+1<n;i+=2){ uint32_t le=b[i]|(b[i+1]<<8), be=(b[i]<<8)|b[i+1]; s16le+=le; s16be+=be; f1=(f1+le)%65535; f2=(f2+f1)%65535; }
  if(n&1){ s16le+=b[n-1]; s16be+=b[n-1]<<8; f1=(f1+b[n-1])%65535; f2=(f2+f1)%65535; }
  for(long i=0;i<n4;i+=4){ uint32_t le=b[i]|(b[i+1]<<8)|(b[i+2]<<16)|((uint32_t)b[i+3]<<24); uint32_t be=bswap(le); s32le+=le; s32be+=be; x32^=le; ones+=le; }
  { uint32_t le=0; for(long i=n4;i<n;i++) le|=(uint32_t)b[i]<<(8*(i-n4)); if(n4<n){ s32le+=le; s32be+=bswap(le); x32^=le; ones+=le; } }
  while(ones>>32) ones=(ones&0xffffffff)+(ones>>32);
  { uint32_t h31=0,h33=0,h65=0,hf=0x811C9DC5,hr=0; for(long i=0;i<n4;i+=4){ uint32_t le=b[i]|(b[i+1]<<8)|(b[i+2]<<16)|((uint32_t)b[i+3]<<24); h31=h31*31+le; h33=h33*33+le; h65=h65*65599u+le; hf=(hf^le)*16777619u; hr=((hr<<1)|(hr>>31))^le; }
    out[A_W31]=h31; out[A_W33]=h33; out[A_W65599]=h65; out[A_WFNV]=hf; out[A_WXORROT]=hr; }
  // adler (slow mod per byte ok for sizes here)
  for(long i=0;i<n;i++){ ad_a=(ad_a+b[i])%65521; ad_b=(ad_b+ad_a)%65521; }
  out[A_SUM8]=(uint32_t)s8; out[A_SUM16LE]=(uint32_t)s16le; out[A_SUM16BE]=(uint32_t)s16be; out[A_SUM32LE]=(uint32_t)s32le; out[A_SUM32BE]=(uint32_t)s32be;
  out[A_XOR32LE]=x32; out[A_XOR8]=x8; out[A_ONES32LE]=(uint32_t)ones; out[A_FLETCH32]=(f2<<16)|f1; out[A_ADLER32]=(ad_b<<16)|ad_a; out[A_BSD32]=bsd; out[A_SUM32LE_HI]=(uint32_t)(s32le>>32)+(uint32_t)s32le;
  out[A_DJB2]=djb; out[A_SDBM]=sdbm; out[A_FNV1A]=fnva; out[A_FNV1]=fnv;
  int a=A_NCRC; for(unsigned p=0;p<NPOLY;p++) for(int r=0;r<2;r++) for(int k=0;k<2;k++) out[a++]=crc[p][r][k];
}
static const char* RNAME[]={"data_after_hdr","from_off12(flags..)","from_off16(ver..)","whole_chk0","whole_chkFF","whole_asis","hdr_only_chk0","data_plus_hdr_chk0_excl_size"};
#define NRANGE 7
static const long PADS[]={0,4,512,4096,65536}; static const int PADFILL[]={0x00,0xFF};
#define NPAD 5
#define NFIN 6
static const char* FNAME[]={"v","~v","-v","bswap v","bswap ~v","rev32 v"};
static uint32_t fin(uint32_t v,int f){switch(f){case 0:return v;case 1:return ~v;case 2:return -v;case 3:return bswap(v);case 4:return bswap(~v);default:return rev32(v);}}
int main(int argc,char**argv){
  if(argc<2){fprintf(stderr,"usage: brute manifest [tagfilter] [maxsize]\n");return 1;}
  const char* tagf=argc>2?argv[2]:NULL; long maxsize=argc>3?atol(argv[3]):0; int xf=argc>4?atoi(argv[4]):0;
  mktabs();
  FILE*m=fopen(argv[1],"r"); Img imgs[64]; int ni=0;
  while(ni<64 && fscanf(m,"%511s %7s %ld %ld %ld %u",imgs[ni].path,imgs[ni].tag,&imgs[ni].off,&imgs[ni].size,&imgs[ni].hdr,&imgs[ni].chk)==6){ if((tagf&&strcmp(tagf,imgs[ni].tag))||(maxsize&&imgs[ni].size>maxsize)) continue; ni++; }
  fclose(m);
  // results[img][range][pad*2+fill][alg]
  static uint32_t res[64][NRANGE][NPAD*2][NALG];
  for(int i=0;i<ni;i++){
    FILE*f=fopen(imgs[i].path,"rb"); long cap=imgs[i].size+65536+8; uint8_t*img=malloc(cap); fseek(f,imgs[i].off,SEEK_SET); fread(img,1,imgs[i].size,f); fclose(f);
    fprintf(stderr,"[%d/%d] %s %s %ld bytes xf=%d\n",i+1,ni,imgs[i].path,imgs[i].tag,imgs[i].size,xf);
    if(xf==1){ for(long k=0;k+3<imgs[i].size;k+=4){ uint8_t t=img[k];img[k]=img[k+3];img[k+3]=t; t=img[k+1];img[k+1]=img[k+2];img[k+2]=t; } }
    if(xf==2){ for(long k=0;k+1<imgs[i].size;k+=2){ uint8_t t=img[k];img[k]=img[k+1];img[k+1]=t; } }
    uint8_t*buf=malloc(cap);
    for(int r=0;r<NRANGE;r++){
      long start,len; memcpy(buf,img,imgs[i].size);
      switch(r){
        case 0: start=imgs[i].hdr; len=imgs[i].size-start; break;
        case 1: start=12; len=imgs[i].size-12; break;
        case 2: start=16; len=imgs[i].size-16; break;
        case 3: memset(buf+8,0,4); start=0; len=imgs[i].size; break;
        case 4: memset(buf+8,0xFF,4); start=0; len=imgs[i].size; break;
        case 5: start=0; len=imgs[i].size; break;
        default: memset(buf+8,0,4); start=0; len=imgs[i].hdr; break;
      }
      for(int p=0;p<NPAD;p++) for(int fl=0;fl<2;fl++){
        long L=len; if(PADS[p]){ long rem=L%PADS[p]; if(rem){ memset(buf+start+L,PADFILL[fl],PADS[p]-rem); L+=PADS[p]-rem; } }
        if(p==0&&fl==1){ memcpy(res[i][r][1],res[i][r][0],sizeof(res[i][r][0])); continue; }
        compute_all(buf+start,L,res[i][r][p*2+fl]);
      }
    }
    free(buf); free(img);
  }
  int minhit=ni>=3?3:ni; char nm[128];
  for(int r=0;r<NRANGE;r++) for(int p=0;p<NPAD*2;p++) for(int a=0;a<NALG;a++) for(int f=0;f<NFIN;f++){
    int hits=0; for(int i=0;i<ni;i++) if(fin(res[i][r][p][a],f)==imgs[i].chk) hits++;
    if(hits>=minhit || hits>=2){ algname(a,nm); printf("HITS=%d/%d  alg=[%s] range=%s pad=%ld fill=%02x final=%s\n",hits,ni,nm,RNAME[r],PADS[p/2],PADFILL[p%2],FNAME[f]); }
  }
  // also report constancy: same raw value across all images for whole_asis (would indicate check makes total constant)
  for(int a=0;a<NALG;a++){ int same=1; for(int i=1;i<ni;i++) if(res[i][5][0][a]!=res[0][5][0][a]) same=0; if(same&&ni>1){algname(a,nm); printf("CONSTANT over whole_asis: alg=[%s] value=%08x\n",nm,res[0][5][0][a]);} }
  printf("done: %d images\n",ni); return 0;
}
