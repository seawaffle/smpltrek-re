/* Differential tests for c6sim: every function is C with defined behaviour, so TI cl6x on C674x and gcc on the
   host must return the same value. Each takes four 32-bit words and returns one. */
#include <stdint.h>
typedef int32_t i32; typedef uint32_t u32; typedef int64_t i64; typedef uint64_t u64;
typedef int16_t i16; typedef uint16_t u16; typedef int8_t i8; typedef uint8_t u8;
#define T(n) u32 n(u32 a, u32 b, u32 c, u32 d)

T(t_arith) { return a + 3 * b - (c ^ d) + (a & ~c) + (b | d); }
T(t_shift) { u32 n = b & 31, m = c & 31; return (a << n) ^ (a >> m) ^ (u32)((i32)a >> (d & 31)); }
T(t_cmp)   { return ((i32)a < (i32)b) | (a < b) << 1 | ((i32)c > (i32)d) << 2 | (c >= d) << 3 | (a == c) << 4; }
T(t_div)   { i32 x = (i32)a, y = (i32)(b | 1); if (y == -1) y = 7;
             return (u32)(x / y) ^ ((u32)(x % y) << 7) ^ (a / (c | 1)) ^ (a % (d | 1)); }
/* Quotient alone, remainder alone, signed and unsigned: each reaches a different run-time helper than t_div's
   combined ones (with GCC: __c6xabi_divi, _remi, _divu, _remu). */
T(t_sdiv)  { i32 x = (i32)a, y = (i32)(b | 1), z = (i32)(c | 1); if (y == -1) y = 3; if (z == -1) z = 5;
             return (u32)(x / y) + (u32)((i32)d / z); }
T(t_smod)  { i32 x = (i32)a, y = (i32)(b | 1), z = (i32)(c | 1); if (y == -1) y = 3; if (z == -1) z = 5;
             return (u32)(x % y) ^ ((u32)((i32)d % z) << 3); }
T(t_udiv)  { return a / (b | 1) + c / ((d & 0xFFFF) | 1); }
T(t_umod)  { return (a % (b | 1)) ^ ((c % ((d >> 8) | 1)) << 5); }
/* Half-word multiplies, saturating and packed arithmetic. The r_ functions are the instruction manual's definitions in
   plain C and are what the host returns. On the DSP, where the compiler has an intrinsic for an instruction (c6x.h with
   cl6x, c6x_intrinsics.h with GCC) the X_ name is that intrinsic, so the instruction itself is executed; otherwise it
   is the r_ function. GCC also turns some of the plain C here into these instructions (MPYH and its family, SWAP4). */
#if defined(__TI_COMPILER_VERSION__)
#include <c6x.h>
#define ON_CL6X 1
#elif defined(__TMS320C6X__)
#include <c6x_intrinsics.h>
#define ON_DSP_GCC 1
#endif
static i32 sh(u32 x, int high) { return (i16)(high ? x >> 16 : x); }
static u32 uh(u32 x, int high) { return (u16)(high ? x >> 16 : x); }
static u32 two(i32 high, i32 low) { return ((u32)high & 0xFFFFu) << 16 | ((u32)low & 0xFFFFu); }
static i32 clamp(i64 v, i64 low, i64 high) { return (i32)(v < low ? low : v > high ? high : v); }
static i32 floor_half(i32 v) { return v >= 0 ? v >> 1 : -((-v + 1) >> 1); }
static i32 r_sadd(i32 x, i32 y) { return clamp((i64)x + y, -2147483647 - 1, 2147483647); }
static i32 r_ssub(i32 x, i32 y) { return clamp((i64)x - y, -2147483647 - 1, 2147483647); }
static i32 r_sshl(i32 x, u32 n) { return clamp((i64)x * ((i64)1 << (n & 31)), -2147483647 - 1, 2147483647); }
static i32 r_smpyx(u32 x, int hx, u32 y, int hy) { i64 p = (i64)sh(x, hx) * sh(y, hy) * 2; return p == 0x80000000LL ? 2147483647 : (i32)p; }
static u32 r_add2(u32 x, u32 y) { return two(sh(x, 1) + sh(y, 1), sh(x, 0) + sh(y, 0)); }
static u32 r_sub2(u32 x, u32 y) { return two(sh(x, 1) - sh(y, 1), sh(x, 0) - sh(y, 0)); }
static u32 r_sadd2(u32 x, u32 y) { return two(clamp(sh(x, 1) + sh(y, 1), -32768, 32767), clamp(sh(x, 0) + sh(y, 0), -32768, 32767)); }
static u32 r_ssub2(u32 x, u32 y) { return two(clamp(sh(x, 1) - sh(y, 1), -32768, 32767), clamp(sh(x, 0) - sh(y, 0), -32768, 32767)); }
static u32 r_saddus2(u32 x, u32 y) { return two(clamp((i64)uh(x, 1) + sh(y, 1), 0, 65535), clamp((i64)uh(x, 0) + sh(y, 0), 0, 65535)); }
static u32 r_avg2(u32 x, u32 y) { return two(floor_half(sh(x, 1) + sh(y, 1) + 1), floor_half(sh(x, 0) + sh(y, 0) + 1)); }
static u32 r_abs2(u32 x) { i32 h = sh(x, 1), l = sh(x, 0); return two(h == -32768 ? 32767 : h < 0 ? -h : h, l == -32768 ? 32767 : l < 0 ? -l : l); }
static u32 r_max2(u32 x, u32 y) { return two(sh(x, 1) > sh(y, 1) ? sh(x, 1) : sh(y, 1), sh(x, 0) > sh(y, 0) ? sh(x, 0) : sh(y, 0)); }
static u32 r_min2(u32 x, u32 y) { return two(sh(x, 1) < sh(y, 1) ? sh(x, 1) : sh(y, 1), sh(x, 0) < sh(y, 0) ? sh(x, 0) : sh(y, 0)); }
static u32 r_bytes(u32 x, u32 y, int kind) {
    u32 r = 0;
    for (int i = 0; i < 32; i += 8) {
        u32 p = x >> i & 255, q = y >> i & 255;
        u32 v = kind == 0 ? p + q : kind == 1 ? p - q : kind == 2 ? (p + q > 255 ? 255 : p + q) : (p + q + 1) >> 1;
        r |= (v & 255) << i;
    }
    return r;
}
static u32 r_bitr(u32 x) { u32 r = 0; for (int i = 0; i < 32; i++) r |= (x >> i & 1) << (31 - i); return r; }
static u32 r_swap4(u32 x) { return (x & 0xFF00FF00u) >> 8 | (x & 0x00FF00FFu) << 8; }
static u32 r_shlmb(u32 x, u32 y) { return y << 8 | x >> 24; }
static u32 r_shrmb(u32 x, u32 y) { return y >> 8 | x << 24; }
static u64 r_mpy4(u32 x, u32 y, int signed1) {
    u64 r = 0;
    for (int i = 0; i < 4; i++) {
        i32 p = signed1 ? (i8)(x >> (i * 8)) : (i32)(x >> (i * 8) & 255);
        r |= (u64)((u32)(p * (i32)(y >> (i * 8) & 255)) & 0xFFFFu) << (i * 16);
    }
    return r;
}
static u64 r_smpy2(u32 x, u32 y) { return (u64)(u32)r_smpyx(x, 1, y, 1) << 32 | (u32)r_smpyx(x, 0, y, 0); }
#if defined(ON_CL6X) || defined(ON_DSP_GCC)
#define X_SADD(x, y) ((i32)_sadd((int)(x), (int)(y)))
#define X_SSUB(x, y) ((i32)_ssub((int)(x), (int)(y)))
#define X_SSHL(x, n) ((i32)_sshl((int)(x), (n) & 31))
#define X_SMPY(x, y) ((i32)_smpy((int)(x), (int)(y)))
#define X_SMPYH(x, y) ((i32)_smpyh((int)(x), (int)(y)))
#define X_SMPYHL(x, y) ((i32)_smpyhl((int)(x), (int)(y)))
#define X_SMPYLH(x, y) ((i32)_smpylh((int)(x), (int)(y)))
#define X_ADD2(x, y) ((u32)_add2((int)(x), (int)(y)))
#define X_SUB2(x, y) ((u32)_sub2((int)(x), (int)(y)))
#define X_SADD2(x, y) ((u32)_sadd2((int)(x), (int)(y)))
#define X_SSUB2(x, y) ((u32)_ssub2((int)(x), (int)(y)))
#define X_AVG2(x, y) ((u32)_avg2((int)(x), (int)(y)))
#define X_ABS2(x) ((u32)_abs2((int)(x)))
#define X_ADD4(x, y) ((u32)_add4((int)(x), (int)(y)))
#define X_SUB4(x, y) ((u32)_sub4((int)(x), (int)(y)))
#define X_SADDU4(x, y) ((u32)_saddu4((x), (y)))
#define X_AVGU4(x, y) ((u32)_avgu4((x), (y)))
#define X_SMPY2(x, y) ((u64)_smpy2ll((int)(x), (int)(y)))
#else
#define X_SADD(x, y) r_sadd((i32)(x), (i32)(y))
#define X_SSUB(x, y) r_ssub((i32)(x), (i32)(y))
#define X_SSHL(x, n) r_sshl((i32)(x), (n))
#define X_SMPY(x, y) r_smpyx((x), 0, (y), 0)
#define X_SMPYH(x, y) r_smpyx((x), 1, (y), 1)
#define X_SMPYHL(x, y) r_smpyx((x), 1, (y), 0)
#define X_SMPYLH(x, y) r_smpyx((x), 0, (y), 1)
#define X_ADD2(x, y) r_add2((x), (y))
#define X_SUB2(x, y) r_sub2((x), (y))
#define X_SADD2(x, y) r_sadd2((x), (y))
#define X_SSUB2(x, y) r_ssub2((x), (y))
#define X_AVG2(x, y) r_avg2((x), (y))
#define X_ABS2(x) r_abs2((x))
#define X_ADD4(x, y) r_bytes((x), (y), 0)
#define X_SUB4(x, y) r_bytes((x), (y), 1)
#define X_SADDU4(x, y) r_bytes((x), (y), 2)
#define X_AVGU4(x, y) r_bytes((x), (y), 3)
#define X_SMPY2(x, y) r_smpy2((x), (y))
#endif
#if defined(ON_DSP_GCC)
/* GCC 13.3 emits SMPY (low half x low half) for these three intrinsics, whatever halves they name: its own fault, seen in
   the disassembly, so they are not used with it. */
#undef X_SMPYH
#undef X_SMPYHL
#undef X_SMPYLH
#define X_SMPYH(x, y) r_smpyx((x), 1, (y), 1)
#define X_SMPYHL(x, y) r_smpyx((x), 1, (y), 0)
#define X_SMPYLH(x, y) r_smpyx((x), 0, (y), 1)
#endif
#if defined(ON_CL6X)                                     /* intrinsics only cl6x has */
#define X_MAX2(x, y) ((u32)_max2((int)(x), (int)(y)))
#define X_MIN2(x, y) ((u32)_min2((int)(x), (int)(y)))
#define X_SADDUS2(x, y) ((u32)_saddus2((x), (int)(y)))
#define X_BITR(x) ((u32)_bitr((x)))
#define X_SWAP4(x) ((u32)_swap4((x)))
#define X_SHLMB(x, y) ((u32)_shlmb((x), (y)))
#define X_SHRMB(x, y) ((u32)_shrmb((x), (y)))
#define X_MPYU4(x, y) ((u64)_mpyu4ll((x), (y)))
#define X_MPYSU4(x, y) ((u64)_mpysu4ll((int)(x), (y)))
#define X_HH(x, y) ((u32)_mpyh((int)(x), (int)(y)))
#define X_HHU(x, y) ((u32)_mpyhu((x), (y)))
#define X_HUS(x, y) ((u32)_mpyhus((x), (int)(y)))
#define X_HSU(x, y) ((u32)_mpyhsu((int)(x), (y)))
#define X_HL(x, y) ((u32)_mpyhl((int)(x), (int)(y)))
#define X_HLU(x, y) ((u32)_mpyhlu((x), (y)))
#define X_HULS(x, y) ((u32)_mpyhuls((x), (int)(y)))
#define X_HSLU(x, y) ((u32)_mpyhslu((int)(x), (y)))
#define X_LUHS(x, y) ((u32)_mpyluhs((x), (int)(y)))
#define X_LSHU(x, y) ((u32)_mpylshu((int)(x), (y)))
#else                                                    /* plain C; GCC for the DSP recognises several of these */
#define X_MAX2(x, y) r_max2((x), (y))
#define X_MIN2(x, y) r_min2((x), (y))
#define X_SADDUS2(x, y) r_saddus2((x), (y))
#define X_BITR(x) r_bitr((x))
#define X_SWAP4(x) r_swap4((x))
#define X_SHLMB(x, y) r_shlmb((x), (y))
#define X_SHRMB(x, y) r_shrmb((x), (y))
#define X_MPYU4(x, y) r_mpy4((x), (y), 0)
#define X_MPYSU4(x, y) r_mpy4((x), (y), 1)
#define X_HH(x, y) ((u32)(((i32)(x) >> 16) * ((i32)(y) >> 16)))
#define X_HHU(x, y) (((u32)(x) >> 16) * ((u32)(y) >> 16))
#define X_HUS(x, y) ((u32)((i32)((u32)(x) >> 16) * ((i32)(y) >> 16)))
#define X_HSU(x, y) ((u32)(((i32)(x) >> 16) * (i32)((u32)(y) >> 16)))
#define X_HL(x, y) ((u32)(((i32)(x) >> 16) * (i16)(y)))
#define X_HLU(x, y) (((u32)(x) >> 16) * (u16)(y))
#define X_HULS(x, y) ((u32)((i32)((u32)(x) >> 16) * (i16)(y)))
#define X_HSLU(x, y) ((u32)(((i32)(x) >> 16) * (i32)(u16)(y)))
#define X_LUHS(x, y) ((u32)((i32)(u16)(x) * ((i32)(y) >> 16)))
#define X_LSHU(x, y) ((u32)((i16)(x) * (i32)((u32)(y) >> 16)))
#endif
T(t_half)  { u32 r = X_HH(a, b); r = r * 31 + X_HHU(a, b); r = r * 31 + X_HUS(a, c); r = r * 31 + X_HSU(c, b); r = r * 31 + X_HL(a, d);
             r = r * 31 + X_HLU(b, c); r = r * 31 + X_HULS(c, d); r = r * 31 + X_HSLU(d, a); r = r * 31 + X_LUHS(b, d); return r * 31 + X_LSHU(d, c); }
T(t_satq)  { u32 r = (u32)X_SADD(a, b); r = r * 31 + (u32)X_SSUB(c, d); r = r * 31 + (u32)X_SMPY(a, d); r = r * 31 + (u32)X_SMPYH(b, c);
             r = r * 31 + (u32)X_SMPYHL(a, c); r = r * 31 + (u32)X_SMPYLH(b, d); r = r * 31 + (u32)X_SSHL(c, d);
             return r * 31 + (u32)X_SADD(X_SADD(a, a), X_SSUB(b, c)); }
T(t_pack2) { u32 r = X_ADD2(a, b); r = r * 31 + X_SUB2(c, d); r = r * 31 + X_SADD2(a, c); r = r * 31 + X_SSUB2(b, d); r = r * 31 + X_AVG2(a, d);
             r = r * 31 + X_ABS2(b); r = r * 31 + X_MAX2(c, a); r = r * 31 + X_MIN2(d, b); return r * 31 + X_SADDUS2(a, b); }
T(t_pack4) { u32 r = X_ADD4(a, b); r = r * 31 + X_SUB4(c, d); r = r * 31 + X_SADDU4(a, c); r = r * 31 + X_AVGU4(b, d); r = r * 31 + X_SWAP4(a);
             r = r * 31 + X_BITR(b); r = r * 31 + X_SHLMB(c, d); return r * 31 + X_SHRMB(d, a); }
T(t_mul4)  { u64 p = X_MPYU4(a, b), q = X_MPYSU4(c, d), s = X_SMPY2(a, c);
             return (u32)p ^ (u32)(p >> 32) * 3 ^ (u32)q * 5 ^ (u32)(q >> 32) * 7 ^ (u32)s * 11 ^ (u32)(s >> 32) * 13; }
T(t_bswap) { u32 x = (a << 24) | ((a << 8) & 0x00FF0000u) | ((a >> 8) & 0x0000FF00u) | (a >> 24); u32 n = b & 31;
             return x ^ ((c << n) | (c >> ((32 - n) & 31))) ^ d; }
T(t_mul)   { return a * b + (u32)((i32)(i16)c * (i32)(i16)d) + (u32)(u16)a * (u16)d; }
T(t_mul64) { i64 p = (i64)(i32)a * (i32)b; u64 q = (u64)c * d; return (u32)(p >> 32) ^ (u32)p ^ (u32)(q >> 29) ^ (u32)q; }
T(t_add64) { u64 x = ((u64)a << 32) | b, y = ((u64)c << 32) | d; u64 s = x + y, t = x - y;
             return (u32)(s >> 32) ^ (u32)s ^ (u32)(t >> 17) ^ (u32)(x > y); }
T(t_shift64) { u64 x = ((u64)a << 32) | b; i64 y = (i64)x; unsigned n = c & 63;
               return (u32)(x << n) ^ (u32)((x >> n) >> 3) ^ (u32)(y >> n) ^ (u32)((u64)(y >> n) >> 32); }
T(t_div64) { u64 x = ((u64)a << 32) | b, y = ((u64)(c & 0xFFFF) << 16) | d | 1; i64 s = (i64)x, t = (i64)(y | 3);
             return (u32)(x / y) ^ (u32)(x % y) ^ (u32)(s / t) ^ (u32)((s % t) >> 3); }
T(t_bits)  { u32 x = (a >> (b & 15)) & 0x3FF; i32 y = ((i32)(c << 9)) >> 20; return x | ((u32)y << 10) ^ (d | 0x00F0F000) ^ (a & ~0x0FF00000u); }
T(t_clz)   { u32 n = 0, x = a; if (!x) return 32 + b; while (!(x & 0x80000000u)) { x <<= 1; n++; } return n ^ (c & 7); }
T(t_bytes) { u8 buf[16]; for (int i = 0; i < 16; i++) buf[i] = (u8)(a >> (i & 3) * 8) ^ (u8)(b * i);
             i32 s = 0; for (int i = 0; i < 16; i++) s += (i8)buf[i] * (i + (i32)(c & 7)); return (u32)s ^ buf[d & 15]; }
T(t_halves) { i16 h[12]; for (int i = 0; i < 12; i++) h[i] = (i16)(a * (i + 1) + (b >> i));
              u32 s = 0; for (int i = 0; i < 12; i++) s += (u32)(h[i] * (i32)(i16)(c >> (i & 15))); return s ^ (u16)h[d % 12]; }
T(t_loop)  { u32 s = a; for (u32 i = 0; i < (b & 255); i++) s = s * 1664525u + 1013904223u + i; return s ^ c; }
T(t_dot)   { i32 x[64], y[64]; u32 s = 0; for (int i = 0; i < 64; i++) { x[i] = (i32)(a * i) >> 3; y[i] = (i32)(b ^ (u32)i * c) >> 5; }
             for (int i = 0; i < 64; i++) s += (u32)x[i] * (u32)y[i]; return s + d; }
T(t_switch) { switch ((a ^ d) % 11) { case 0: return b; case 1: return c + 1; case 2: return b ^ c; case 3: return a * 3;
              case 4: return d >> 2; case 5: return ~a; case 6: return b + c + d; case 7: return 77; case 8: return a & d;
              case 9: return c - b; default: return 123456; } }
static u32 fib(u32 n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }
T(t_recurse) { return fib(a % 18) ^ b; }
typedef u32 (*fn)(u32, u32);
static u32 op0(u32 x, u32 y) { return x + y; } static u32 op1(u32 x, u32 y) { return x ^ (y << 3); }
static u32 op2(u32 x, u32 y) { return x * y + 1; }
static const fn ops[3] = {op0, op1, op2};
T(t_fnptr) { u32 s = d; for (u32 i = 0; i < 9; i++) s = ops[(a + i) % 3](s, b + i * c); return s; }
struct S { u8 k; i16 h; i32 w; u8 tail[5]; };
T(t_struct) { struct S s[4]; for (int i = 0; i < 4; i++) { s[i].k = (u8)(a + i); s[i].h = (i16)(b - i); s[i].w = (i32)(c * i);
              for (int j = 0; j < 5; j++) s[i].tail[j] = (u8)(d >> j); }
              struct S t = s[a & 3]; s[(a + 1) & 3] = t; u32 r = 0;
              for (int i = 0; i < 4; i++) r = r * 31 + s[i].k + (u32)s[i].h + (u32)s[i].w + s[i].tail[i]; return r; }
T(t_float) { float x = (float)(i32)a / 1048576.0f, y = (float)(i32)(b | 1) / 977.0f / 1024.0f;
             float z = x * y + x - y; i32 r = (i32)(z * 13.0f); return (u32)r ^ (u32)(x < y) ^ (u32)(i32)(x * 0.5f); }
T(t_double) { double x = (double)(i32)a / 1024.0, y = (double)(i32)(b | 1) / 977.0;
              double z = x * y + x - y; i64 r = (i64)(z * 1000.0); return (u32)r ^ (u32)(r >> 32) ^ (u32)(x < y); }
T(t_fdiv)  { float x = (float)(i32)a, y = (float)((b >> 16) | 1) + 65536.0f; return (u32)(i32)(x / y * 4096.0f); }
T(t_ddiv)  { double x = (double)(i32)a, y = (double)((b >> 16) | 1) + 65536.0; return (u32)(i64)(x / y * 65536.0); }
T(t_conv)  { float f = (float)(u32)a; double g = (double)(i32)b; u32 r = (u32)(f / 4.0f) ^ (u32)(i32)(g / 3.0);
             return r ^ (u32)(float)(i16)c ^ (u32)(u8)(float)(d & 255); }
T(t_sat)   { i64 s = (i64)(i32)a + (i32)b; i32 r = s > 2147483647 ? 2147483647 : s < -2147483647 - 1 ? -2147483647 - 1 : (i32)s;
             i32 t = (i32)(i16)c * 3; if (t > 32767) t = 32767; if (t < -32768) t = -32768; return (u32)r ^ (u32)t ^ d; }
T(t_abs)   { i32 x = (i32)a; i32 y = x < 0 ? -(x | 1) : x; i32 m = (i32)b > (i32)c ? (i32)b : (i32)c; return (u32)y + (u32)m + (d > a ? d : a); }
T(t_memcpy) { u8 src[40], dst[40]; for (int i = 0; i < 40; i++) { src[i] = (u8)(a + i * b); dst[i] = (u8)c; }
              u32 off = d % 9, n = (a >> 3) % 30; for (u32 i = 0; i < n; i++) dst[off + i] = src[(b & 7) + i];
              u32 r = 0; for (int i = 0; i < 40; i++) r = r * 33 + dst[i]; return r; }
T(t_matrix) { u32 m[6][6], v[6], o[6]; for (int i = 0; i < 6; i++) { v[i] = (a >> i) - d; for (int j = 0; j < 6; j++) m[i][j] = b * (u32)i - c * (u32)j; }
              for (int i = 0; i < 6; i++) { u32 s = 0; for (int j = 0; j < 6; j++) s += m[i][j] * v[j]; o[i] = s; }
              return (o[0] ^ o[1] * 3 ^ o[2] * 5 ^ o[3] * 7 ^ o[4] * 11 ^ o[5] * 13); }
T(t_crc)   { u32 crc = 0xFFFFFFFFu; u32 w[4] = {a, b, c, d};
             for (int i = 0; i < 16; i++) { crc ^= (w[i >> 2] >> ((i & 3) * 8)) & 0xFF; for (int k = 0; k < 8; k++) crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1))); }
             return ~crc; }
T(t_while) { u32 n = 0, x = a | 1; while (x != 1 && n < 500) { x = (x & 1) ? 3 * x + 1 : x >> 1; n++; } return n ^ (b & 0xFF); }
/* Do-while loops that cl6x turns into SPLOOPW (kept out of line so the loop form survives). The exit test acts on
   the value the condition register had 4 cycles before the stage boundary (SPRUFE8B 7.10.2): w_dot's loop has
   ii 3 and work after the condition is set, so an exit on the current value drops its last products. */
static i16 wx[64], wy[64]; static char wsrc[80], wdst[80];
static void w_fill(u32 a, u32 b) { for (int i = 0; i < 64; i++) { wx[i] = (i16)(((a >> (i & 15)) & 2047) + i - 900); wy[i] = (i16)(((b >> (i & 7)) & 1023) - 3 * i); } }
__attribute__((noinline)) static int w_dot(const i16 *restrict x, const i16 *restrict y, int n, int m) { int sum = 0; do { sum += *x++ * *y++; n -= m; } while (n >= 0); return sum; }
__attribute__((noinline)) static char *w_copy(char *restrict to, const char *restrict from) { char t; do { t = *from++; *to++ = t; } while (t); return to; }
__attribute__((noinline)) static u32 w_len(const char *s) { const char *p = s; while (*p) p++; return (u32)(p - s); }
__attribute__((noinline)) static int w_find(const i16 *restrict p, int v) { int i = 0; while (p[i] != v) i++; return i; }
T(t_wdot)  { w_fill(a, b); return (u32)w_dot(wx, wy, (int)(c % 50), (int)(d % 5) + 1); }
T(t_wcopy) { u32 n = a % 60, h = 0; for (u32 i = 0; i < 79; i++) { wsrc[i] = (char)(1 + ((b >> (i & 15)) + i) % 100); wdst[i] = 0x55; } wsrc[n] = 0;
             char *e = w_copy(wdst, wsrc); for (u32 i = 0; i < 80; i++) h = h * 31 + (u8)wdst[i]; return h ^ (u32)(e - wdst); }
T(t_wlen)  { u32 n = a % 70; for (u32 i = 0; i < 79; i++) wsrc[i] = (char)(1 + (i + b) % 90); wsrc[n] = 0; wsrc[79] = 0; return w_len(wsrc) ^ c; }
T(t_wfind) { w_fill(a, b); wx[c % 64] = 12345; wx[63] = 12345; return (u32)w_find(wx, 12345) ^ d; }
/* Loops in more shapes (2026-11-16), kept out of line so each keeps its own loop form: counted loops whose trip
   count starts at 0 or 1, 8/16/32-bit elements, 64-bit and saturating accumulators, nested loops with a short inner
   loop, loops that end on data, and single-precision loops (exact on both sides: same operations in the same order,
   no contraction). At -O2 and above cl6x turns most into SPLOOP or SPLOOPD and uses packed 16-bit instructions
   (DOTP2, MPY2, DPACK2, MPYLH, MPYLHU). It emitted no loop-buffer reload for any of them. */
#define NI __attribute__((noinline)) static
static i16 lx[96], ly[96], lo[96]; static i32 lw[96], lv[96]; static u8 lb[128], lc[128]; static float lf[64], lg[64], lh[64];
static void l_fill(u32 a, u32 b) { for (int i = 0; i < 96; i++) { lx[i] = (i16)(((a >> (i & 15)) & 1023) + 7 * i - 600); ly[i] = (i16)(((b >> (i & 7)) & 511) - 5 * i);
    lw[i] = (i32)((a ^ (b << (i & 7))) + (u32)i * 2654435761u) >> 9; lv[i] = (i32)(b * (u32)(i + 3)) >> 11; lo[i] = 0; }
  for (int i = 0; i < 128; i++) { lb[i] = (u8)(1 + ((a >> (i & 13)) + 3 * i) % 251); lc[i] = lb[i]; }
  for (int i = 0; i < 64; i++) { lf[i] = (float)((i32)((a >> (i & 9)) & 255) - 100) * 0.25f; lg[i] = (float)((i32)((b >> (i & 5)) & 127) - 60) * 0.5f; lh[i] = 0; } }
static u32 hash16(const i16 *p, int n) { u32 h = 0; for (int i = 0; i < n; i++) h = h * 31 + (u16)p[i]; return h; }
static u32 hash32(const i32 *p, int n) { u32 h = 0; for (int i = 0; i < n; i++) h = h * 33 + (u32)p[i]; return h; }
static u32 fbits(float f) { union { float f; u32 u; } v; v.f = f; return v.u; }
/* nested loops with a short inner loop: candidates for buffer reload */
NI void l_fir(const i16 *restrict x, const i16 *restrict h, i16 *restrict y, int n, int taps) { for (int j = 0; j < n; j++) { i32 s = 0; for (int i = 0; i < taps; i++) s += x[i + j] * h[i]; y[j] = (i16)(s >> 8); } }
NI void l_fir8(const i16 *restrict x, const i16 *restrict h, i16 *restrict y, int n) { for (int j = 0; j < n; j++) { i32 s = 0; for (int i = 0; i < 8; i++) s += x[i + j] * h[i]; y[j] = (i16)(s >> 6); } }
NI void l_rows(const i32 *restrict s, i32 *restrict t, int rows, int cols) { for (int r = 0; r < rows; r++) for (int c = 0; c < cols; c++) t[r * cols + c] = s[r * cols + c] + r; }
NI u32 l_matsum(const i32 *restrict m, int rows) { u32 acc = 0; for (int r = 0; r < rows; r++) { u32 s = 0; for (int c = 0; c < 6; c++) s += (u32)m[r * 6 + c]; acc = acc * 3 + s; } return acc; }
T(t_fir)   { l_fill(a, b); int n = (int)(c % 40) + 1, taps = (int)(d % 24) + 1; l_fir(lx, ly, lo, n, taps); return hash16(lo, 96); }
T(t_fir8)  { l_fill(a, b); int n = (int)(c % 80) + 1; l_fir8(lx, ly, lo, n); return hash16(lo, 96) ^ d; }
T(t_rows)  { l_fill(a, b); int rows = (int)(c % 9) + 1, cols = (int)(d % 10) + 1; l_rows(lw, lv, rows, cols); return hash32(lv, 96); }
T(t_matsum){ l_fill(a, b); return l_matsum(lw, (int)(c % 16)) ^ d; }
/* counted loops with trip counts from 0, element sizes, 64-bit and saturating accumulators */
NI u32 l_sum8(const u8 *restrict p, int n) { u32 s = 0; for (int i = 0; i < n; i++) s += p[i]; return s; }
NI i64 l_dot64(const i32 *restrict x, const i32 *restrict y, int n) { i64 s = 0; for (int i = 0; i < n; i++) s += (i64)x[i] * y[i]; return s; }
NI i32 l_max(const i32 *restrict x, int n) { i32 m = x[0]; for (int i = 1; i < n; i++) if (x[i] > m) m = x[i]; return m; }
NI int l_argmax(const i16 *restrict x, int n) { int k = 0; for (int i = 1; i < n; i++) if (x[i] > x[k]) k = i; return k; }
NI void l_sat(const i16 *restrict x, const i16 *restrict y, i16 *restrict o, int n) { for (int i = 0; i < n; i++) { i32 v = x[i] * 3 + y[i] * 5; o[i] = (i16)(v > 32767 ? 32767 : v < -32768 ? -32768 : v); } }
NI void l_scale(const i16 *restrict x, i16 *restrict o, int n, int g) { for (int i = 0; i < n; i++) o[i] = (i16)((x[i] * g) >> 7); }
NI u32 l_prefix(i32 *restrict x, int n) { for (int i = 1; i < n; i++) x[i] += x[i - 1]; return (u32)x[n ? n - 1 : 0]; }
NI void l_rev(u8 *restrict p, int n) { for (int i = 0, j = n - 1; i < j; i++, j--) { u8 t = p[i]; p[i] = p[j]; p[j] = t; } }
T(t_sum8)  { l_fill(a, b); return l_sum8(lb + (d & 3), (int)(c % 100)); }
T(t_dot64) { l_fill(a, b); i64 s = l_dot64(lw, lv, (int)(c % 90)); return (u32)s ^ (u32)(s >> 32) ^ d; }
T(t_max)   { l_fill(a, b); return (u32)l_max(lw + (d % 8), (int)(c % 80) + 1); }
T(t_argmax){ l_fill(a, b); return (u32)l_argmax(lx, (int)(c % 96) + 1) ^ d; }
T(t_lsat)  { l_fill(a, b); for (int i = 0; i < 96; i++) lx[i] = (i16)(lx[i] * 13); l_sat(lx, ly, lo, (int)(c % 97)); return hash16(lo, 96) ^ d; }
T(t_scale) { l_fill(a, b); l_scale(lx, lo, (int)(c % 97), (int)(d % 300) - 150); return hash16(lo, 96); }
T(t_prefix){ l_fill(a, b); for (int i = 0; i < 96; i++) lw[i] >>= 8; u32 r = l_prefix(lw, (int)(c % 97)); return r ^ hash32(lw, 96) ^ d; }
T(t_rev)   { l_fill(a, b); l_rev(lb, (int)(c % 129)); u32 h = d; for (int i = 0; i < 128; i++) h = h * 131 + lb[i]; return h; }
/* loops that end on data */
NI int l_chr(const u8 *restrict p, int n, u8 v) { int i = 0; while (i < n && p[i] != v) i++; return i; }
NI int l_cmp(const u8 *restrict p, const u8 *restrict q) { while (*p && *p == *q) { p++; q++; } return (int)*p - (int)*q; }
NI u32 l_gcd(u32 x, u32 y) { while (y) { u32 t = x % y; x = y; y = t; } return x; }
NI u32 l_pop(u32 x) { u32 n = 0; while (x) { x &= x - 1; n++; } return n; }
NI int l_skip(const i16 *restrict p, int lim) { int i = 0; do { i++; } while (p[i] < lim && i < 90); return i; }
NI u32 l_acc_until(const i32 *restrict p, u32 lim) { u32 s = 0; int i = 0; do { s += (u32)p[i] & 0xFFFF; i++; } while (s < lim && i < 96); return s ^ (u32)i; }
NI int l_copy_until(u8 *restrict to, const u8 *restrict from, u8 stop) { int n = 0; u8 t; do { t = from[n]; to[n] = (u8)(t ^ 0x5A); n++; } while (t != stop && n < 120); return n; }
T(t_chr)   { l_fill(a, b); lb[c % 128] = 0xFE; return (u32)l_chr(lb, (int)(d % 129), 0xFE); }
T(t_lcmp)  { l_fill(a, b); lb[c % 120] = 0; lc[c % 120] = 0; lc[d % 128] ^= (u8)(b & 4); return (u32)l_cmp(lb, lc); }
T(t_gcd)   { return l_gcd(a | 1, b) + l_gcd(c, d | 1); }
T(t_pop)   { return l_pop(a) + l_pop(b) * 33 + l_pop(c & d) * 1089; }
T(t_skip)  { l_fill(a, b); return (u32)l_skip(lx, (int)(c % 2000) - 600) ^ d; }
T(t_accu)  { l_fill(a, b); return l_acc_until(lw, c % 3000000) + d; }
T(t_cpyu)  { l_fill(a, b); u8 out[128]; for (int i = 0; i < 128; i++) out[i] = 0x11; int n = l_copy_until(out, lb, lb[c % 100]); u32 h = (u32)n ^ d; for (int i = 0; i < 128; i++) h = h * 17 + out[i]; return h; }
/* floating point loops (single precision, exact in both builds: no contraction, same operation order) */
NI float l_fdot(const float *restrict x, const float *restrict y, int n) { float s = 0; for (int i = 0; i < n; i++) s += x[i] * y[i]; return s; }
NI void l_saxpy(float *restrict o, const float *restrict x, const float *restrict y, float k, int n) { for (int i = 0; i < n; i++) o[i] = k * x[i] + y[i]; }
NI float l_iir(const float *restrict x, int n, float k) { float s = 0; for (int i = 0; i < n; i++) s = s * k + x[i]; return s; }
NI float l_fmax(const float *restrict x, int n) { float m = x[0]; for (int i = 1; i < n; i++) if (x[i] > m) m = x[i]; return m; }
NI void l_f2i(const float *restrict x, i16 *restrict o, int n) { for (int i = 0; i < n; i++) { float v = x[i] * 64.0f; o[i] = (i16)(v > 32767.0f ? 32767 : v < -32768.0f ? -32768 : (i32)v); } }
/* Audio kernels of the kind a synthesiser or effect is made of: state in a struct, a block of samples in and out.
   Single precision throughout, no division, the same operations in the same order on both sides, and values kept
   far from the denormal range, so the host's result is exact for the DSP too. */
typedef struct { float b0, b1, b2, a1, a2, z1, z2; } k_biquad;
typedef struct { float g, k, a1, a2, a3, ic1, ic2; } k_svf;
typedef struct { u32 phase, step; } k_osc;
typedef struct { float *buf; u32 mask, write; } k_delay;
static float kt[64 + 1], kd[64], ko[64], kp[64];
static u32 khash(const float *p, int n) { u32 h = 0; for (int i = 0; i < n; i++) h = h * 37 + fbits(p[i]); return h; }
NI void k_biquad_run(k_biquad *restrict s, const float *restrict in, float *restrict out, int n) {   /* transposed direct form II */
    float z1 = s->z1, z2 = s->z2;
    for (int i = 0; i < n; i++) { float x = in[i], y = s->b0 * x + z1; z1 = s->b1 * x - s->a1 * y + z2; z2 = s->b2 * x - s->a2 * y; out[i] = y; }
    s->z1 = z1; s->z2 = z2;
}
NI void k_svf_run(k_svf *restrict s, const float *restrict in, float *restrict low, float *restrict band, int n) {   /* trapezoidal state variable */
    for (int i = 0; i < n; i++) {
        float v3 = in[i] - s->ic2, v1 = s->a1 * s->ic1 + s->a2 * v3, v2 = s->ic2 + s->a2 * s->ic1 + s->a3 * v3;
        s->ic1 = 2.0f * v1 - s->ic1; s->ic2 = 2.0f * v2 - s->ic2; low[i] = v2; band[i] = v1;
    }
}
NI float k_onepole_run(float y, float a, const float *restrict in, float *restrict out, int n) { for (int i = 0; i < n; i++) out[i] = y += a * (in[i] - y); return y; }
NI void k_fir_run(const float *restrict taps, int length, const float *restrict in, float *restrict out, int n) {
    for (int j = 0; j < n; j++) { float acc = 0; for (int i = 0; i < length; i++) acc += taps[i] * in[j + i]; out[j] = acc; }
}
NI void k_table_run(k_osc *restrict o, const float *restrict table, int bits, float *restrict out, int n, float level) {   /* linear interpolation */
    u32 phase = o->phase, step = o->step;
    for (int i = 0; i < n; i++) {
        u32 index = phase >> (32 - bits);
        float frac = (float)((phase << bits) >> 8) * (1.0f / 16777216.0f), x0 = table[index], x1 = table[index + 1];
        out[i] += level * (x0 + frac * (x1 - x0)); phase += step;
    }
    o->phase = phase;
}
NI void k_saw_run(k_osc *restrict o, float *restrict out, int n, float level) {   /* phase to a bipolar ramp, then a cubic shaper */
    u32 phase = o->phase;
    for (int i = 0; i < n; i++) { float x = (float)(i32)phase * (1.0f / 2147483648.0f); out[i] += level * (1.5f * x - 0.5f * x * x * x); phase += o->step; }
    o->phase = phase;
}
static inline void k_delay_write(k_delay *d, float x) { d->buf[d->write = (d->write + 1) & d->mask] = x; }
static inline float k_delay_tap(const k_delay *d, float delay) {
    u32 whole = (u32)delay; float frac = delay - (float)whole;
    float x0 = d->buf[(d->write - whole) & d->mask], x1 = d->buf[(d->write - whole - 1) & d->mask];
    return x0 + frac * (x1 - x0);
}
NI void k_chorus_run(k_delay *restrict d, const float *restrict in, const float *restrict depth, float *restrict out, int n, float feedback) {
    for (int i = 0; i < n; i++) { float wet = k_delay_tap(d, depth[i]); k_delay_write(d, in[i] + feedback * wet); out[i] = in[i] + wet; }
}
NI void k_clip_run(float *restrict buf, int n, float drive) {   /* clamp to +-1.5, then x - 4/27 x^3 */
    for (int i = 0; i < n; i++) { float x = drive * buf[i]; x = x > 1.5f ? 1.5f : x < -1.5f ? -1.5f : x; buf[i] = x - 0.148148148f * x * x * x; }
}
NI void k_pan_run(const float *restrict in, float *restrict left, float *restrict right, int n, float gl, float gr, float dl, float dr) {
    for (int i = 0; i < n; i++) { left[i] += gl * in[i]; right[i] += gr * in[i]; gl += dl; gr += dr; }
}
NI void k_noise_run(u32 *restrict state, float *restrict out, int n, float level) {
    u32 s = *state;
    for (int i = 0; i < n; i++) { s = s * 1664525u + 1013904223u; out[i] += level * ((float)(i32)s * (1.0f / 2147483648.0f)); }
    *state = s;
}
NI void k_to_pcm(const float *restrict in, i16 *restrict out, int n) {   /* scale, round half away from zero, clamp */
    for (int i = 0; i < n; i++) { float v = in[i] * 32768.0f; v += v >= 0 ? 0.5f : -0.5f; out[i] = (i16)(v > 32767.0f ? 32767 : v < -32768.0f ? -32768 : (i32)v); }
}
static void k_fill(u32 a, u32 b) {
    for (int i = 0; i < 64; i++) { kd[i] = (float)((i32)((a >> (i & 11)) & 2047) - 1024) * (1.0f / 1024.0f); ko[i] = 0; kp[i] = 0;
                                   kt[i] = (float)((i32)(((b >> (i & 7)) * (u32)(i + 5)) & 4095) - 2048) * (1.0f / 2048.0f); }
    kt[64] = kt[0];
}
static float coef(u32 v, u32 span, float scale) { return (float)((i32)(v % span) - (i32)(span / 2)) * scale; }
T(t_kbiquad) { k_fill(a, b); k_biquad s = { 0.25f, 0.5f, 0.25f, coef(c, 96, 1.0f / 64.0f), coef(d, 48, 1.0f / 64.0f), 0, 0 };
               k_biquad_run(&s, kd, ko, 24 + (int)(a % 9)); k_biquad_run(&s, kd + 20, ko + 32, (int)(b % 30)); return khash(ko, 64) ^ fbits(s.z1) ^ fbits(s.z2); }
T(t_ksvf)    { k_fill(a, b); float g = 0.0625f + (float)(c % 16) * 0.03125f, k = 0.25f + (float)(d % 16) * 0.0625f;
               k_svf s = { g, k, 0.5f, g * 0.5f, g * g * 0.5f, 0, 0 }; k_svf_run(&s, kd, ko, kp, (int)(a % 65)); return khash(ko, 64) ^ khash(kp, 64) * 3 ^ fbits(s.ic1); }
T(t_kpole)   { k_fill(a, b); float y = k_onepole_run(coef(c, 64, 1.0f / 32.0f), 0.015625f + (float)(d % 60) * 0.015625f, kd, ko, (int)(b % 65)); return khash(ko, 64) ^ fbits(y); }
T(t_kfir)    { k_fill(a, b); int length = (int)(c % 24) + 1; k_fir_run(kt, length, kd, ko, 64 - length - (int)(d % 8)); return khash(ko, 64); }
T(t_ktable)  { k_fill(a, b); k_osc o = { c, d | 0x00200001u }; k_table_run(&o, kt, 6, ko, 64, 0.75f); o.step >>= 3; k_table_run(&o, kt, 6, ko, (int)(a % 65), -0.5f);
               return khash(ko, 64) ^ o.phase; }
T(t_ksaw)    { k_fill(a, b); k_osc o = { a, c | 0x01000001u }; k_saw_run(&o, ko, 64, 0.5f); o.step = d >> 4; k_saw_run(&o, ko, (int)(b % 65), 0.25f); return khash(ko, 64) ^ o.phase; }
T(t_kchorus) { k_fill(a, b); float line[32]; for (int i = 0; i < 32; i++) line[i] = 0; k_delay d0 = { line, 31, c & 31 };
               for (int i = 0; i < 64; i++) kp[i] = 1.0f + (float)((d >> (i & 15)) & 255) * (1.0f / 16.0f);
               k_chorus_run(&d0, kd, kp, ko, 64, coef(b, 16, 1.0f / 16.0f)); return khash(ko, 64) ^ khash(line, 32) ^ d0.write; }
T(t_kclip)   { k_fill(a, b); k_clip_run(kd, (int)(c % 65), 0.5f + (float)(d % 40) * 0.125f); return khash(kd, 64); }
T(t_kpan)    { k_fill(a, b); k_pan_run(kd, ko, kp, (int)(c % 65), 0.75f, 0.25f, coef(d, 32, 1.0f / 512.0f), coef(d >> 8, 32, 1.0f / 512.0f)); return khash(ko, 64) ^ khash(kp, 64) * 5; }
T(t_knoise)  { k_fill(a, b); u32 state = c; k_noise_run(&state, kd, (int)(d % 65), 0.125f); i16 pcm[64]; k_to_pcm(kd, pcm, 64); return khash(kd, 64) ^ hash16(pcm, 64) ^ state; }
T(t_fdot)  { l_fill(a, b); return fbits(l_fdot(lf, lg, (int)(c % 65))) ^ d; }
T(t_saxpy) { l_fill(a, b); l_saxpy(lh, lf, lg, (float)((i32)(d % 17) - 8) * 0.125f, (int)(c % 65)); u32 h = 0; for (int i = 0; i < 64; i++) h = h * 29 + fbits(lh[i]); return h; }
T(t_iir)   { l_fill(a, b); return fbits(l_iir(lf, (int)(c % 65), (float)((i32)(d % 9) - 4) * 0.125f)); }
T(t_fmax)  { l_fill(a, b); return fbits(l_fmax(lf + (d % 4), (int)(c % 60) + 1)); }
T(t_f2i)   { l_fill(a, b); l_f2i(lf, lo, (int)(c % 65)); return hash16(lo, 96) ^ d; }
