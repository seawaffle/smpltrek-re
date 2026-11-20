/* Source-built DSP fixture: no firmware or proprietary content. */
unsigned integer_sum(const unsigned *values, unsigned count)
{
    unsigned sum = 0;
    unsigned i;
    for (i = 0; i < count; i++) sum += values[i] ^ (i * 17u);
    return sum;
}
unsigned integer_mix(unsigned x, unsigned y)
{
    unsigned result = (x ^ (y << 3)) + 0x12345678u;
    if ((int)x < (int)y) result ^= x >> 5;
    else result ^= ~y;
    return result + x * y;
}
