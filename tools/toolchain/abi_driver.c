/* Caller side of the C6000 EABI interoperability test. See abi_funcs.c.
 *
 * abi_driver(out) calls every function in abi_funcs.c with fixed inputs and stores each result as
 * one or two 32-bit words in `out`, returning the number of words written. The simulator runs it
 * with A4 = a scratch buffer; the harness compares the words across the four compiler pairings and
 * against values computed in Python. Nothing here depends on which compiler built abi_funcs.c.
 */

typedef unsigned int u32;
typedef unsigned long long u64;
struct s8 { int a; int b; };
struct s24 { int v[6]; };

int add5(int, int, int, int, int);
int add12(int, int, int, int, int, int, int, int, int, int, int, int);
u64 add64(u64, u64);
u64 mix64(int, u64, int, u64);
double dmul(double, double);
float fmadd(float, float, float);
double mixfd(float, double, int, float);
int f2i(float);
float i2f(int);
u32 d2u(double);
long long d2ll(double);
struct s8 s8_make(int);
int s8_sum(struct s8, int);
struct s24 s24_make(int);
int s24_sum(struct s24, int);
int vsum(int, ...);
u64 vsum64(int, ...);
int call_through(int (*)(int, int), int, int);
int sub2(int, int);
u32 udiv(u32, u32);
int sdiv(int, int);
u32 umod(u32, u32);
u64 udiv64(u64, u64);
long long smod64(long long, long long);
int dot(const short *, const short *, int);
void fill(unsigned char *, int, unsigned char);
int pressure(const int *);

static void put64(u32 *out, int *n, u64 v) { out[(*n)++] = (u32)v; out[(*n)++] = (u32)(v >> 32); }
static void putd(u32 *out, int *n, double v) { union { double d; u64 u; } x; x.d = v; put64(out, n, x.u); }
static void putf(u32 *out, int *n, float v) { union { float f; u32 u; } x; x.f = v; out[(*n)++] = x.u; }

int abi_driver(u32 *out)
{
    int n = 0, i;
    struct s8 a8;
    struct s24 a24;
    static const short va[8] = { 1, -2, 3, -4, 5, -6, 7, -8 };
    static const short vb[8] = { 8, 7, 6, 5, 4, 3, 2, 1 };
    static const int pr[16] = { 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16 };
    unsigned char buf[16];

    out[n++] = (u32)add5(1, 2, 3, 4, 5);
    out[n++] = (u32)add12(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12);
    put64(out, &n, add64(0x0000000180000000ull, 0x0000000280000001ull));
    put64(out, &n, mix64(5, 0x100000000ull, -2, 0x200000000ull));
    putd(out, &n, dmul(2.5, 4.0));
    putf(out, &n, fmadd(1.5f, 2.0f, 0.25f));
    putd(out, &n, mixfd(0.5f, 1.25, 3, 0.75f));
    out[n++] = (u32)f2i(-7.9f);
    putf(out, &n, i2f(10));
    out[n++] = d2u(3000000000.0);
    put64(out, &n, (u64)d2ll(-5000000000.0));

    a8 = s8_make(7);
    out[n++] = (u32)a8.a;
    out[n++] = (u32)a8.b;
    out[n++] = (u32)s8_sum(a8, 100);
    a24 = s24_make(10);
    for (i = 0; i < 6; i++) out[n++] = (u32)a24.v[i];
    out[n++] = (u32)s24_sum(a24, 1000);

    out[n++] = (u32)vsum(0);
    out[n++] = (u32)vsum(3, 10, 20, 30);
    out[n++] = (u32)vsum(12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12);
    put64(out, &n, vsum64(3, 0x100000001ull, 0x200000002ull, 0x300000003ull));

    out[n++] = (u32)call_through(sub2, 50, 8);
    out[n++] = udiv(1000000007u, 13u);
    out[n++] = (u32)sdiv(-1000000007, 13);
    out[n++] = umod(1000000007u, 13u);
    put64(out, &n, udiv64(0x123456789ABCDEF0ull, 0x1000000FFull));
    put64(out, &n, (u64)smod64(-0x123456789ABCDEFll, 1000003ll));

    out[n++] = (u32)dot(va, vb, 8);
    fill(buf, 16, 0xF0);
    for (i = 0; i < 16; i += 4)
        out[n++] = (u32)buf[i] | ((u32)buf[i + 1] << 8) | ((u32)buf[i + 2] << 16) | ((u32)buf[i + 3] << 24);
    out[n++] = (u32)pressure(pr);
    return n;
}
