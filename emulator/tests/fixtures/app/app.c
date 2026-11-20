/* A small synthesiser as a custom firmware would be built: a timer interrupt renders one block of samples at a
   time through an oscillator, a filter, a delay and a clipper, while the main program does unrelated work and
   then sleeps in IDLE until the last block is done. Built by GCC for the DSP (with crt0.s) and for the host,
   where the blocks are simply rendered in a loop: the result must be the same whenever the interrupts fall.
   Single precision, no float division, values far from the denormal range. See tests/test_app.py. */
#include <stdint.h>
typedef int32_t i32; typedef uint32_t u32; typedef int16_t i16; typedef uint16_t u16; typedef uint8_t u8;
#define BLOCK 32
#define BLOCKS 24
#define TABLE 64
static float table[TABLE + 1], line[128], out[BLOCK * BLOCKS];
static i16 pcm[BLOCK * BLOCKS];
static struct { u32 phase, step, lfo, write, noise; float ic1, ic2, g, k; } voice;
static volatile u32 done;

static u32 fbits(float f) { union { float f; u32 u; } v; v.f = f; return v.u; }

void app_block(void) {
    if (done >= BLOCKS) return;
    float *o = out + done * BLOCK;
    float g = voice.g, a1 = 0.5f, a2 = g * a1, a3 = g * a2;
    for (int i = 0; i < BLOCK; i++) {
        u32 index = voice.phase >> 26;
        float frac = (float)((voice.phase << 6) >> 8) * (1.0f / 16777216.0f);
        float x = table[index] + frac * (table[index + 1] - table[index]);
        voice.noise = voice.noise * 1664525u + 1013904223u;
        x += 0.0625f * ((float)(i32)voice.noise * (1.0f / 2147483648.0f));
        float v3 = x - voice.ic2, v1 = a1 * voice.ic1 + a2 * v3, v2 = voice.ic2 + a2 * voice.ic1 + a3 * v3;   /* state variable low-pass */
        voice.ic1 = 2.0f * v1 - voice.ic1; voice.ic2 = 2.0f * v2 - voice.ic2;
        u32 tap = 20 + (voice.lfo >> 27) + (done * 7 + (u32)i) % 5;                                          /* a wobbling delay */
        float wet = line[(voice.write - tap) & 127];
        line[voice.write = (voice.write + 1) & 127] = v2 + 0.375f * wet;
        float y = 1.25f * (v2 + 0.5f * wet);
        y = y > 1.5f ? 1.5f : y < -1.5f ? -1.5f : y;
        y = y - 0.148148148f * y * y * y;
        o[i] = y;
        float scaled = y * 20000.0f; scaled += scaled >= 0 ? 0.5f : -0.5f;
        pcm[done * BLOCK + i] = (i16)(i32)scaled;
        voice.phase += voice.step; voice.lfo += 0x00a3d70au;
    }
    voice.step += voice.step / 64;                                                                           /* a slow glide, by integer division */
    done++;
}

/* Unrelated work for the main program, of the kind interrupts land in: local arrays, integer division, float. */
__attribute__((noinline)) static u32 background(u32 seed, u32 rounds) {
    u32 acc = seed;
    for (u32 r = 0; r < rounds; r++) {
        i16 h[12]; float f[8];
        for (int i = 0; i < 12; i++) h[i] = (i16)(acc * (u32)(i + 1) + (seed >> i));
        for (int i = 0; i < 8; i++) f[i] = (float)h[i] * 0.03125f + (float)(i32)(r % 7);
        float s = 0; for (int i = 0; i < 8; i++) s = s * 0.5f + f[i];
        u32 t = 0; for (int i = 0; i < 12; i++) t += (u32)(h[i] * (i32)(i16)(acc >> (i & 15)));
        acc = acc * 1664525u + (t ^ fbits(s)) + (u32)((i32)(acc >> 3) / (i32)((r & 31) + 3)) + (u16)h[(acc >> 8) % 12];
    }
    return acc;
}

#if defined(__TMS320C6X__)
#define TIMER ((volatile u32 *)0x01c20000)
static void start(u32 period) { TIMER[0x18 / 4] = period; TIMER[0x24 / 4] = 5; TIMER[0x20 / 4] = 0x80; }
static void stop(void) { TIMER[0x20 / 4] = 0; }
static void finish(void) { while (done < BLOCKS) __asm__ volatile ("idle"); }
#else
static void start(u32 period) { (void)period; }
static void stop(void) { }
static void finish(void) { while (done < BLOCKS) app_block(); }
#endif

u32 app_main(u32 period, u32 seed, u32 rounds, u32 unused) {
    (void)unused;
    for (int i = 0; i <= TABLE; i++) {                      /* one cycle of a parabolic sine approximation */
        float t = (float)(i & (TABLE - 1)) * (1.0f / 32.0f) - 1.0f, a = t < 0 ? -t : t;
        table[i] = 4.0f * t * (1.0f - a);
    }
    for (int i = 0; i < 128; i++) line[i] = 0;
    for (int i = 0; i < BLOCK * BLOCKS; i++) { out[i] = 0; pcm[i] = 0; }
    voice.phase = seed; voice.step = 0x02000000u + (seed & 0x00ffffffu); voice.lfo = seed << 3; voice.write = 0; voice.noise = seed ^ 0x5bd1e995u;
    voice.ic1 = voice.ic2 = 0; voice.g = 0.125f + (float)(seed >> 28) * 0.03125f; voice.k = 0.5f;
    done = 0;
    start(period);
    u32 acc = background(seed, rounds);
    finish();
    stop();
    u32 hash = 0;
    for (int i = 0; i < BLOCK * BLOCKS; i++) hash = hash * 31 + fbits(out[i]) + (u16)pcm[i];
    return hash * 31 + acc;
}

#if !defined(__TMS320C6X__)
#include <stdio.h>
int main(void) { unsigned seed, rounds; while (scanf("%u %u", &seed, &rounds) == 2) printf("%u\n", app_main(0, seed, rounds, 0)); return 0; }
#endif
