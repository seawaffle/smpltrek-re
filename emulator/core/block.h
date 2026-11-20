// Interface between the core and compiled guest blocks (off in the core unless a caller enables it).
// A block is host code for a straight run of guest packets. It leaves the machine either
// just before a cycle's tick (returns true: the core then runs the ordinary tick) or at a
// packet boundary (returns false).
#pragma once
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstring>

struct alignas(64) C6Due {
    static constexpr unsigned SLOTS = 16, ROOM = 15; // 128 bytes per slot
    uint32_t count = 0;
    struct Entry { uint32_t first, second; } writes[ROOM];
};
struct C6Page {
    uint8_t data[4096];
    uint64_t versions[4096 / 32];
    bool decoded[4096 / 32];
};
struct C6Direct { uint32_t page = UINT32_MAX, physical = 0; C6Page *host = nullptr; };
struct C6BlockContext {
    void *machine;
    uint32_t *regs;
    uint64_t *cycles, *packets, *interrupt_blocked_until;
    uint32_t *pc, *idle, *fault_address, *pending_count;
    C6Due *due;
    uint32_t iterations, boundaries; // Loop blocks: iterations allowed, loop boundaries passed.
    uint32_t history; // SPLOOPW blocks: the loop condition at the start of each of the last 32 cycles.
    uint64_t *held;      // Data of the loads by byte lane, [0] path T1 (side A registers), [1] T2: the reserved-low read option.
    const bool *tsc_running; const uint64_t *tsc_start; // The time stamp counter counts cycles from tsc_start.
    const C6Direct *direct_read, *direct_write;
    void (*delay_slow)(void *machine, uint64_t due, uint32_t reg, uint32_t value);
    void (*branch)(void *machine, uint64_t due, uint32_t target, uint32_t restore);
};
typedef bool (*C6BlockFunction)(C6BlockContext *);

// A load of `size` bytes replaces the byte lanes it reads in the held data.
[[gnu::always_inline]] static inline void c6b_hold(uint64_t &held, uint32_t address, uint64_t value, uint32_t size) {
    if (size == 8) { held = value; return; }
    unsigned shift = (address & (8 - size)) * 8;
    uint64_t mask = (size == 4 ? 0xffffffffull : size == 2 ? 0xffffull : 0xffull) << shift;
    held = (held & ~mask) | (value << shift & mask);
}
#ifdef C6_BLOCK_CODE
static_assert(std::endian::native == std::endian::little, "compiled blocks assume a little-endian host");
static inline int64_t c6b_signed(uint32_t value) { return int32_t(value); }
static inline float c6b_single(uint32_t value) {
    if (!(value & 0x7f800000)) value &= 0x80000000;
    return std::bit_cast<float>(value);
}
static inline uint32_t c6b_bits(float value) {
    if (std::isnan(value)) return 0x7fffffff;
    uint32_t result = std::bit_cast<uint32_t>(value);
    return !(result & 0x7f800000) ? result & 0x80000000 : result;
}
static inline uint32_t c6b_fix(uint32_t bits, bool nearest) {
    double x = c6b_single(bits);
    if (std::isnan(x) || x >= 2147483648.0) return 0x7fffffff;
    if (x < -2147483648.0) return 0x80000000;
    return uint32_t(int64_t(nearest ? std::nearbyint(x) : std::trunc(x)));
}
// LMBD: how many bits from the top precede the first one equal to `bit`; 32 if none.
static inline uint32_t c6b_lmbd(uint32_t bit, uint32_t value) {
    return uint32_t(std::countl_zero(bit & 1 ? value : ~value));
}
// The time stamp counter at `cycle`.
[[gnu::always_inline]] static inline uint64_t c6b_tsc(const C6BlockContext *c, uint64_t cycle) {
    return *c->tsc_running && cycle >= *c->tsc_start ? cycle - *c->tsc_start : 0;
}
// Results issued before the block was entered.
[[gnu::always_inline]] static inline void c6b_deliver(C6BlockContext *c, uint64_t cycle) {
    C6Due &slot = c->due[cycle % C6Due::SLOTS];
    for (uint32_t i = 0; i < slot.count; i++) c->regs[slot.writes[i].first] = slot.writes[i].second;
    *c->pending_count -= slot.count; slot.count = 0;
}
[[gnu::always_inline]] static inline void c6b_push(C6BlockContext *c, uint64_t due, uint32_t reg, uint32_t value) {
    C6Due &slot = c->due[due % C6Due::SLOTS];
    if (slot.count == C6Due::ROOM) { c->delay_slow(c->machine, due, reg, value); return; }
    slot.writes[slot.count++] = {reg, value};
    ++*c->pending_count;
}
// Only plain RAM is accessed here. Anything else sets `slow`; the block then leaves before
// the packet and the interpreter performs the access.
// `held` is the block's copy of the held load data; the block stores it once the packet is not refused.
[[gnu::always_inline]] static inline uint64_t c6b_load(C6BlockContext *c, uint32_t address, uint32_t size, bool &slow, uint64_t &held) {
    const C6Direct &entry = c->direct_read[(address >> 12) & 4095];
    uint64_t result = 0;
    if (entry.page == address >> 12 && (address & 4095) + size <= 4096) {
        std::memcpy(&result, entry.host->data + (address & 4095), size);
        c6b_hold(held, address, result, size);
    } else slow = true;
    return result;
}
// A store into bytes that have been decoded as code is also left to the interpreter: it
// must be the last thing host code made from those bytes sees, in this block or another.
[[gnu::always_inline]] static inline bool c6b_writable(C6BlockContext *c, uint32_t address, uint32_t size) {
    const C6Direct &entry = c->direct_write[(address >> 12) & 4095];
    uint32_t offset = address & 4095;
    return entry.page == address >> 12 && offset + size <= 4096 &&
           !(entry.host->decoded[offset / 32] | entry.host->decoded[(offset + size - 1) / 32]);
}
[[gnu::always_inline]] static inline void c6b_store(C6BlockContext *c, uint32_t address, uint64_t value, uint32_t size) {
    C6Page *host = c->direct_write[(address >> 12) & 4095].host;
    uint32_t offset = address & 4095;
    std::memcpy(host->data + offset, &value, size);
    ++host->versions[offset / 32];
    if ((offset + size - 1) / 32 != offset / 32) ++host->versions[offset / 32 + 1];
}
#endif
