/* Callee side of the C6000 EABI interoperability test.
 *
 * Every function here is compiled once with TI cl6x and once with GCC tic6x-elf, and called from
 * abi_driver.c compiled by either compiler. Each case covers one convention that matters at the
 * skeleton-firmware API boundary (SPRAB89, C6000 EABI): register arguments past the first few,
 * stack arguments, 64-bit and floating-point register pairs, small and large structs by value,
 * struct return, variadic calls, callbacks, division helpers, and loops (code quality).
 * No libc: the file is freestanding.
 */

typedef unsigned int u32;
typedef unsigned long long u64;

struct s8 { int a; int b; };                       /* 8 bytes: fits a register pair */
struct s24 { int v[6]; };                          /* 24 bytes: passed and returned by reference */

int add5(int a, int b, int c, int d, int e) { return a + 2 * b + 3 * c + 4 * d + 5 * e; }

/* twelve arguments: ten in registers, two on the stack */
int add12(int a, int b, int c, int d, int e, int f, int g, int h, int i, int j, int k, int l)
{
    return a + b * 2 + c * 3 + d * 4 + e * 5 + f * 6 + g * 7 + h * 8 + i * 9 + j * 10 + k * 11 + l * 12;
}

u64 add64(u64 a, u64 b) { return a + b; }
u64 mix64(int a, u64 b, int c, u64 d) { return b + d + (u64)a * 3 + (u64)c * 7; }

double dmul(double a, double b) { return a * b + 1.5; }
float fmadd(float a, float b, float c) { return a * b + c; }
double mixfd(float a, double b, int c, float d) { return a + b + c + d; }
int f2i(float a) { return (int)a; }
float i2f(int a) { return (float)a / 4.0f; }
u32 d2u(double a) { return (u32)a; }
long long d2ll(double a) { return (long long)a; }

struct s8 s8_make(int x) { struct s8 r; r.a = x; r.b = x * 3; return r; }
int s8_sum(struct s8 s, int k) { return s.a + s.b + k; }
struct s24 s24_make(int x) { struct s24 r; int i; for (i = 0; i < 6; i++) r.v[i] = x + i; return r; }
int s24_sum(struct s24 s, int k) { return s.v[0] + s.v[1] + s.v[2] + s.v[3] + s.v[4] + s.v[5] + k; }

#include <stdarg.h>
int vsum(int n, ...)
{
    va_list ap; int i, t = 0;
    va_start(ap, n);
    for (i = 0; i < n; i++) t += va_arg(ap, int);
    va_end(ap);
    return t;
}
u64 vsum64(int n, ...)
{
    va_list ap; int i; u64 t = 0;
    va_start(ap, n);
    for (i = 0; i < n; i++) t += va_arg(ap, u64);
    va_end(ap);
    return t;
}

int call_through(int (*f)(int, int), int x, int y) { return f(x, y) + 1; }
int sub2(int x, int y) { return x - y; }

u32 udiv(u32 a, u32 b) { return a / b; }
int sdiv(int a, int b) { return a / b; }
u32 umod(u32 a, u32 b) { return a % b; }
u64 udiv64(u64 a, u64 b) { return a / b; }
long long smod64(long long a, long long b) { return a % b; }

int dot(const short *a, const short *b, int n)
{
    int i, t = 0;
    for (i = 0; i < n; i++) t += a[i] * b[i];
    return t;
}

void fill(unsigned char *p, int n, unsigned char v)
{
    int i;
    for (i = 0; i < n; i++) p[i] = (unsigned char)(v + i);
}

/* register pressure: forces callee-saved registers to be used and restored */
int pressure(const int *p)
{
    int a = p[0], b = p[1], c = p[2], d = p[3], e = p[4], f = p[5], g = p[6], h = p[7];
    int i = p[8], j = p[9], k = p[10], l = p[11], m = p[12], n = p[13], o = p[14], q = p[15];
    int r = sub2(a * b, c * d);
    r += sub2(e * f, g * h);
    r += sub2(i * j, k * l);
    r += sub2(m * n, o * q);
    return r + a + b + c + d + e + f + g + h + i + j + k + l + m + n + o + q;
}
