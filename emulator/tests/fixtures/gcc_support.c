/* What the C library would supply: the compiler may call these for block copies, and libgcc's unwinder refers to abort. */
typedef __SIZE_TYPE__ size_t;
void abort(void) { for (;;) ; }
void *memcpy(void *to, const void *from, size_t n) { char *t = to; const char *f = from; while (n--) *t++ = *f++; return to; }
void *memmove(void *to, const void *from, size_t n) {
    char *t = to; const char *f = from;
    if (t < f) while (n--) *t++ = *f++; else while (n--) t[n] = f[n];
    return to;
}
void *memset(void *to, int value, size_t n) { char *t = to; while (n--) *t++ = (char)value; return to; }
