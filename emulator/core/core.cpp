#include "core.h"
#include "board.h"
#include "block.h"
#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <deque>
#include <limits>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace {
constexpr uint32_t PAGE = 4096;
constexpr uint32_t AMR = 73, TSCL = 74, TSCH = 75;
static_assert(sizeof(c6_operand) == 24 && sizeof(c6_instruction) == 120 && sizeof(c6_state) == 424);
struct Page {
    std::array<uint8_t, PAGE> data{};
    std::array<uint64_t, PAGE / 32> versions{};
    std::array<bool, PAGE / 32> decoded{}; // A decoded packet has depended on this span.
};
using PageGroup = std::array<std::unique_ptr<Page>, 1024>;
struct Region { uint64_t begin, end; uint32_t flags; };
struct Alias { uint64_t begin, end; uint32_t target; };
struct Write { uint64_t due; uint32_t reg, value; };
// Delayed register results, indexed by due cycle. Every result is due within 11 cycles.
using Due = C6Due;
struct Branch { uint64_t due; uint32_t target, restore = 0; };
struct IrqWrite { uint64_t due; uint32_t set, clear; };
struct Store { uint32_t address; uint64_t value; uint32_t size, pc; };
// A guest page that is entirely ordinary RAM with one permission set and one translation.
struct Direct { uint32_t page = UINT32_MAX, physical = 0; Page *host = nullptr; };
// Compiled blocks read these through the plain layouts of block.h.
static_assert(sizeof(Page) == sizeof(C6Page) && offsetof(Page, versions) == offsetof(C6Page, versions) &&
              sizeof(Direct) == sizeof(C6Direct) && offsetof(Direct, host) == offsetof(C6Direct, host));
// Host code for a straight run of packets; see block.h and Machine::block_plan.
struct Block {
    uint32_t steady = 0; bool loop = false; // Loop blocks: see Machine::loop_plan.
    C6BlockFunction function = nullptr;
    uint32_t ticks = 0; // Cycles it may advance without the ordinary tick.
    std::vector<std::pair<const uint64_t *, uint64_t>> dependencies;
    std::vector<uint32_t> later_packets; // Issue addresses after the first, for breakpoints.
    uint64_t breakpoint_epoch = 0;
    bool breakpoint_free = false;
};
struct BlockSlot { uint32_t pc = 0; Block *block = nullptr; };
struct DoubleJob {
    uint64_t issue;
    c6_instruction instruction;
    std::array<uint32_t, 3> low{}, high{}, scalar{};
    std::array<uint64_t, 3> due{};
};
// The common instruction forms in a compact, directly executable shape. Sources point at
// CPU registers or pooled constants. Forms it cannot express use the general path.
struct Micro {
    enum Kind : uint8_t { SKIP, MOV, MVKH, ADD, SUB, AND, OR, XOR, ANDN, NOT, NEG, SHL, SHR, SHRU,
        CMPEQ, CMPGT, CMPLT, CMPGTU, CMPLTU, EXT, EXTU, ADDSCALED, MPY16, MPY32,
        ADDSP, SUBSP, MPYSP, INTSP, INTSPU, SPTRUNC, SPINT, CMPEQSP, CMPGTSP, CMPLTSP,
        LOAD, STORE, BRANCH, BDEC, BPOS, NOP, ADDKPC, MOVLATE, ABSSP, MPY32WIDE, LMBD, ROTL, TSC,
        DINT, RINT, CSRW, IERW };
    Kind kind = SKIP;
    uint8_t dst = 0, high = 0, size = 0, sign = 0, mode = 0, aligned = 0, restore = 0, left = 0, right = 0;
    bool link = false, sets_extra = false;
    int32_t scale = 0;
    uint32_t extra = 0;
    int64_t displacement = 0;
    const uint32_t *a = nullptr, *b = nullptr, *base = nullptr, *index = nullptr;
};
// A decoded instruction with its plain scalar sources resolved once. A source points at a
// CPU register or a pooled constant; null selects the general operand path (pairs, memory
// operands and control registers with read side effects).
struct Op {
    static constexpr uint32_t LOOP = 1, UNSUPPORTED = 2, LOAD = 4, BRANCH = 8;
    c6_instruction ins{};
    std::array<const uint32_t *, 4> source{};
    const uint32_t *predicate = nullptr;
    uint32_t flags = 0;
    bool fast = false;
    Micro micro;
};
struct Packet {
    uint32_t next, protected_load;
    std::vector<Op> ops;
    std::vector<const Op *> refs;
    bool fast = false; // Every instruction has a Micro form.
    // Pages live until machine destruction, so these counters stay valid across
    // RAM growth/reset.
    std::array<std::pair<const uint64_t *, uint64_t>, 3> dependencies{};
    uint32_t dependency_count = 0;
    bool loop_control = false, reload_control = false;
    mutable bool executable = false; // Mappings only grow, so a passed fetch check stays passed.
    uint32_t nop_cycles = 0;
};
struct FetchSlot { uint32_t address = 0; Packet *packet = nullptr; };
struct LoopRow {
    uint32_t offset, mask;
    std::vector<Op> instructions;
    uint32_t phase = 0, stage = 0; // offset modulo and divided by the loop's ii
};
struct Loop {
    uint32_t kind = 0, ii = 1, length = 0, boundary = 0, delay = 0, after = 0, ilc = 0, pc = 0;
    int32_t predicate = -1;
    bool invert = false, loading_only = false, stopping = false;
    // Nested reload (SPRUFE8B 7.9.6). `nested`: a conditional SPLOOP(D). `reload`: its condition was
    // true 4 cycles before the last kernel stage boundary. `sampled`: that cycle was inside the loop.
    // `reloaded`: this invocation came from the buffer, so masked instructions never issue.
    // `reloading`: it still overlaps program fetch. `kernel_reload`: the body ends in SPKERNELR, so a
    // reload starts with the post-loop code instead of at an SPMASKR. `from_reload`: started by a
    // reload, not by the SPLOOP packet. A reload with RILC = 0 is `loading_only` and `reloaded`: it
    // issues nothing until its last stage boundary (7.9.6.2).
    bool nested = false, reload = false, sampled = false, reloaded = false, reloading = false;
    bool kernel_reload = false, from_reload = false;
    // Draining for an interrupt (7.13.1): no new iterations, then the interrupt is taken with
    // IRP = the SPLOOP packet and ITSR.SPLX set.
    bool interrupted = false;
    uint32_t history = 0; // The loop instruction's predicate at the start of each of the last 32 loop cycles.
    uint64_t start = 0, started = 1, post = 0, end = 0;
    int64_t term = -1;
    std::vector<LoopRow> rows;
};
struct GuestProfile {
    bool enabled = false, rows_valid = false;
    uint32_t period = 0, countdown = 0, random = 0x6748;
    uint64_t begin_cycle = 0, begin_packet = 0, begin_irq = 0;
    uint64_t end_cycle = 0, end_packet = 0, end_irq = 0;
    uint64_t issue_cycles = 0, wait_cycles = 0, loop_cycles = 0, irq_cycles = 0, drain_cycles = 0;
    uint64_t loop_packets = 0, wait_advances = 0, coalesced = 0, samples = 0, dropped = 0;
    std::unordered_map<uint64_t, uint64_t> pcs;
    std::vector<std::pair<uint64_t, uint64_t>> rows;
    void packet(uint32_t pc, bool software_loop) {
        if (software_loop) loop_packets++;
        if (--countdown) return;
        samples++; rows_valid = false;
        uint64_t key = uint64_t(software_loop) << 32 | pc;
        auto found = pcs.find(key);
        if (found != pcs.end()) found->second++;
        else if (pcs.size() < 65536) pcs.emplace(key, 1);
        else dropped++;
        random = random * 1664525u + 1013904223u;
        countdown = period == 1 ? 1 : (period + 1) / 2 + random % period;
    }
    void snapshot() {
        rows.assign(pcs.begin(), pcs.end());
        std::sort(rows.begin(), rows.end(), [](const auto &a, const auto &b) {
            return a.second != b.second ? a.second > b.second : a.first < b.first;
        });
        rows_valid = true;
    }
};
// Exact fast-forward of guest state that provably repeats. A snapshot is taken when a
// branch lands. If the same CPU state recurs at that PC with no net RAM change by the CPU
// and no MMIO, TSCL read, interrupt or device write to RAM the CPU touched, the CPU repeats
// that period until a device event changes its inputs. Whole periods are then added to
// the cycle/packet counts, never across a device event. The proof survives events that
// leave the CPU's registers and touched RAM alone.
//
// When every store of the period rewrote what was already there, RAM is the same at every
// cycle of it, so a device event inside the next period finds the RAM it would have found.
// That event is then run early, at its own cycle number, while the CPU waits at the anchor.
// If it raised no new interrupt flag and wrote nothing the CPU touches, the period is
// skipped as well. Otherwise its flags (and its writes to touched RAM, undone first) are
// held back until the CPU reaches the event's cycle by ordinary execution.
struct Recurrence {
    static constexpr uint64_t MAX_CYCLES = 65536;
    static constexpr size_t MAX_WORDS = 4096, SLOTS = 16384;
    bool enabled = true, active = false, recording = false, proven = false;
    bool constant = false;    // The proven period never changes RAM, even briefly.
    bool varying = false;     // Some store of the recorded period changed RAM, if only briefly.
    bool looking = false;     // A device event is running ahead of the CPU.
    mutable bool impure = false;
    uint32_t cleared = 0;        // Interrupt flags cleared since the snapshot.
    uint32_t steady_cleared = 0; // The same, over the proven period.
    uint32_t anchor = 0, favorite = 0, favorite_failures = 0, fault_address = 0, mismatches = 0;
    uint64_t cycle = 0, packets = 0, period = 0, issued = 0, blocked = 0, interrupts = 0, run_end = 0;
    uint64_t cooldown = 0, backoff = 64;
    bool tsc_running = false;
    std::array<uint32_t, 96> regs{};
    std::vector<std::pair<uint32_t, uint64_t>> stores;
    std::vector<uint32_t> loads;
    struct Slot { uint32_t address, stamp; uint64_t value; };
    std::vector<Slot> slots = std::vector<Slot>(SLOTS);
    uint32_t stamp = 0;
    uint64_t skips = 0, skipped_cycles = 0, skipped_packets = 0, attempts = 0, abandoned = 0, proofs = 0;
    uint64_t looks = 0, held = 0;
    // A device write made while looking ahead, and the bytes it replaced.
    struct Ahead { Page *page; uint32_t offset, size; std::array<uint8_t, 32> before, after; };
    std::vector<Ahead> ahead;
    // Words are 8-byte aligned physical addresses. Returns the slot holding the word, or
    // the empty slot where it belongs.
    Slot &slot(uint32_t word) {
        for (size_t index = (word >> 3) * 0x9e3779b1u >> 18;; index = (index + 1) % SLOTS)
            if (slots[index].stamp != stamp || slots[index].address == word) return slots[index];
    }
    bool touched(uint32_t word) { return slot(word).stamp == stamp; }
    void stop() { recording = proven = false; }
};
std::string hex(uint32_t value) {
    char text[16]; std::snprintf(text, sizeof text, "0x%08x", value); return text;
}
int64_t signed32(uint32_t value) { return value < 0x80000000u ? value : int64_t(value) - 0x100000000ll; }
uint32_t saturated(int64_t value) {
    return uint32_t(std::clamp(value, int64_t(-2147483648ll), int64_t(2147483647ll)));
}
float single(uint32_t value) {
    if (!(value & 0x7f800000)) value &= 0x80000000;
    return std::bit_cast<float>(value);
}
uint32_t single_bits(float value) {
    if (std::isnan(value)) return 0x7fffffff;
    uint32_t result = std::bit_cast<uint32_t>(value);
    return !(result & 0x7f800000) ? result & 0x80000000 : result;
}
double floating64(uint64_t bits) {
    if (!(bits & 0x7ff0000000000000ull)) bits &= 0x8000000000000000ull;
    return std::bit_cast<double>(bits);
}
uint64_t double_bits(double value) {
    if (std::isnan(value)) return 0x7fffffffffffffffull;
    uint64_t bits = std::bit_cast<uint64_t>(value);
    return !(bits & 0x7ff0000000000000ull) ? bits & 0x8000000000000000ull : bits;
}
// RCPSP/RCPDP/RSQRSP/RSQRDP of a normal number. Only the top eight mantissa bits of the input are used, as a table
// would (bench M3, RCP2: all eight tables); the result is the exact value for that input rounded to nearest at
// eight mantissa bits, lower bits zero (M2, step R1; no result is ever a tie). `width` is 32 or 64; a result too
// small is a signed zero.
uint64_t estimate(uint64_t bits, unsigned width, bool root) {
    const unsigned fraction = width == 32 ? 23 : 52, field = width - 1 - fraction;
    const int bias = (1 << (field - 1)) - 1;
    const uint64_t sign = bits >> (width - 1) << (width - 1), one = uint64_t(1) << fraction;
    uint64_t mantissa = ((bits & (one - 1)) | one) >> (fraction - 8) << (fraction - 8);
    int exponent = int(bits >> fraction & ((1u << field) - 1)) - bias, out;
    unsigned __int128 top;
    if (!root) {
        if (mantissa == one) { top = 256; out = -exponent; }
        else { top = (((unsigned __int128)1 << (fraction + 10)) + mantissa) / (2 * (unsigned __int128)mantissa); out = -exponent - 1; }
    } else {
        int odd = exponent & 1;                                  // value = scaled / 2^fraction * 4^((exponent - odd) / 2)
        unsigned __int128 scaled = (unsigned __int128)mantissa << odd, limit = (unsigned __int128)1 << (fraction + 20);
        out = -((exponent - odd) / 2);
        if (scaled == one) top = 256;
        else {                                                   // 2 / sqrt(scaled / 2^fraction), in (1, 2), times 256
            auto reaches = [&](unsigned __int128 t) { return (2 * t - 1) * (2 * t - 1) * scaled <= limit; };
            top = (unsigned __int128)(512.0 / std::sqrt(double(scaled) / double(one)));
            while (reaches(top + 1)) top++;
            while (!reaches(top)) top--;
            out--;
        }
    }
    if (top == 512) { top = 256; out++; }
    if (out + bias <= 0) return sign;
    return sign | uint64_t(out + bias) << fraction | uint64_t(top - 256) << (fraction - 8);
}
uint32_t double_delay(uint32_t op) {
    switch (op) {
    case C6_MPYSP2DP: case C6_INTDP: case C6_INTDPU: return 4;
    case C6_MPYSPDP: case C6_ADDDP: case C6_SUBDP: return 6;
    case C6_MPYDP: return 9;
    case C6_DPTRUNC: case C6_DPINT: case C6_DPSP: return 3;
    default: return 1;
    }
}

class Machine {
public:
    Machine() {
        indirect_read.fill(UINT32_MAX); indirect_write.fill(UINT32_MAX);
        board.dma_copy = [this](uint32_t src, uint32_t dst, uint32_t size) {
            // MMIO arrays retain bus widths; RAM goes through normal permission and
            // instruction-cache invalidation paths. DMA accesses have a distinct trace PC.
            for (uint32_t offset = 0; offset < size;) {
                uint32_t count = std::min(4u, size - offset);
                uint64_t value = board.contains(src + offset, count)
                    ? board.read(src + offset, count, cycles, 0xfffffff0) : load(src + offset, count);
                uint8_t bytes[4];
                for (unsigned i = 0; i < count; i++) bytes[i] = uint8_t(value >> (i * 8));
                if (board.contains(dst + offset, count)) board.write(dst + offset, uint32_t(value), count, cycles, 0xfffffff0);
                else write(dst + offset, bytes, count, true, 0xfffffff0);
                offset += count;
            }
        };
    }
    std::array<uint32_t, 96> regs{};
    std::vector<Region> regions;
    mutable Region checked_region{0, 0, 0};
    std::vector<Alias> aliases;
    Board board;
    // Two direct indices cover the 32-bit address space. Allocate 8 KiB pointer
    // groups and 4 KiB RAM pages only when used; page/version addresses stay stable.
    std::array<std::unique_ptr<PageGroup>, 1024> pages{};
    // Mappings and aliases only grow and never overlap, and pages are never freed, so an
    // entry stays correct once made. Device, partial and unmapped pages are never entered.
    std::array<Direct, 4096> direct_read{}, direct_write{};
    std::array<uint32_t, 4096> indirect_read, indirect_write; // Pages last found unsuitable.
    std::vector<uint8_t> device_pages = std::vector<uint8_t>(1u << 20); // 0 unknown, 1 none, 2 device
    std::deque<uint32_t> constants; // Stable addresses for immediate operands.
    std::unordered_map<uint32_t, const uint32_t *> constant_index;
    const uint32_t *constant(uint32_t value) {
        auto [found, added] = constant_index.try_emplace(value, nullptr);
        if (added) found->second = &constants.emplace_back(value);
        return found->second;
    }
    std::unordered_map<uint32_t, Packet> cache;
    // Stable unordered_map nodes own packets; this small tagged front cache only
    // avoids repeated hash lookups. Fetch versions are still checked on every hit.
    std::array<FetchSlot, 4096> fetch_slots{};
    std::array<Due, Due::SLOTS> due{};
    std::vector<Write> pending; // Results beyond a slot's room or the ring's reach.
    uint32_t pending_count = 0;
    std::vector<DoubleJob> late;
    std::vector<Branch> branches;
    std::vector<IrqWrite> irq_writes;
    // Packet scratch storage persists across issue, avoiding allocator work in the hot loop.
    std::vector<Write> issue_immediate, issue_delayed;
    std::vector<Store> issue_stores;
    std::vector<Branch> issue_branches;
    std::vector<const Op *> buffered_ops;
    std::unordered_set<uint32_t> breakpoints;
    std::array<uint64_t, 1024> breakpoint_bits{}; // Superset filter for the set above.
    Loop loop, loop_candidate;
    GuestProfile guest_profile;
    Recurrence recur;
    std::unordered_map<uint32_t, Block> blocks;
    std::array<BlockSlot, 65536> block_slots{};
    static uint32_t block_slot(uint32_t pc) { return (pc * 0x9e3779b1u) >> 16; }
    std::unordered_map<uint32_t, uint64_t> block_heat;
    C6BlockContext block_context{};
    std::string block_reason; // Why the last plan stopped where it did (diagnostic).
    Block *loop_native = nullptr; // Host code for the active loop, chosen when it begins.
    bool blocks_enabled = false, block_heat_enabled = false, block_seek = true;
    bool micro_enabled = true; // Off: every instruction takes the general path (for comparing the two).
    uint64_t block_entries = 0, block_cycles = 0, block_refusals = 0, block_loop_cycles = 0, breakpoint_epoch = 1;
    // Effects of a device event that ran ahead of the CPU, applied when it reaches that cycle.
    uint64_t held_cycle = 0;
    uint32_t held_interrupts = 0;
    bool loop_active = false;
    std::vector<Loop> draining;
    bool reload_pending = false, reload_landed = false; // A reloading invocation is in `draining`.
    // A return from interrupt restored TSR.SPLX: the SPLOOP packet at this address pipes the loop
    // back up (7.13.2) instead of starting it.
    bool loop_resume = false;
    uint32_t loop_resume_pc = 0;
    uint64_t cycles = 0, packets = 0;
    uint32_t pc = 0, idle = 0, status = C6_BUDGET, fault_address = 0, return_address = 0;
    uint32_t decode_address = 0;
    uint64_t interrupt_blocked_until = 0, interrupt_due = 0, interrupt_count = 0;
    // CSR.SAT is set one cycle after a saturating instruction's result is written (SPRUFE8B: SADD, SSUB,
    // SSHL, SAT, SMPY...). The cycle from which an instruction sees it; 0 when none is owed.
    // IDLE has been issued: the multicycle NOP it starts lasts until an interrupt is entered or a branch
    // already in flight lands (SPRUFE8B IDLE).
    bool idling = false;
    uint64_t sat_due = 0;
    uint32_t sat_units = 0; // The SSR bits (L1, L2, S1, S2, M1, M2) that go with it.
    uint64_t loop_interrupt_count = 0; // Interrupts entered with ITSR.SPLX set.
    uint32_t interrupt_target = 0;
    bool stop_on_return = false;
    bool tsc_running = false;
    uint64_t tsc_start = 0;
    std::string error;

    void check(uint32_t address, uint64_t size, uint32_t flags) const {
        if (!size || uint64_t(address) + size > 0x100000000ull)
            throw std::runtime_error("invalid memory range at " + hex(address));
        uint64_t cursor = address, end = cursor + size;
        if (checked_region.begin <= cursor && end <= checked_region.end &&
            (checked_region.flags & flags) == flags) return;
        while (cursor < end) {
            auto region = std::find_if(regions.begin(), regions.end(), [cursor](const Region &r) {
                return r.begin <= cursor && cursor < r.end;
            });
            if (region == regions.end() || (region->flags & flags) != flags)
                throw std::runtime_error("unmapped or disallowed memory access at " + hex(uint32_t(cursor)));
            checked_region = *region;
            cursor = std::min(end, region->end);
        }
    }
    void map(uint32_t address, uint64_t size, uint32_t flags) {
        if ((board.reserved_low_writes || board.reserved_low_reads) && address < Board::RESERVED_END)
            throw std::runtime_error("reserved-low policy does not map RAM below L2 ROM");
        if (!size || uint64_t(address) + size > 0x100000000ull || !flags || flags > 7)
            throw std::runtime_error("invalid mapping at " + hex(address));
        if (board.enabled && uint64_t(address) < 0x60000000u && uint64_t(address) + size > 0x40000000u)
            throw std::runtime_error("the board does not map RAM in the EMIFA range");
        for (const auto &region : regions)
            if (uint64_t(address) < region.end && uint64_t(address) + size > region.begin)
                throw std::runtime_error("overlapping mapping at " + hex(address));
        regions.push_back({address, uint64_t(address) + size, flags});
    }
    uint32_t physical(uint32_t address) const {
        for (const auto &alias : aliases) if (alias.begin <= address && address < alias.end)
            return alias.target + uint32_t(address - alias.begin);
        return address;
    }
    void alias(uint32_t address, uint32_t target, uint64_t size) {
        if ((address | target | size) & 31) throw std::runtime_error("aliases must align to fetch packets");
        check(target, size, 0);
        for (const auto &other : aliases) if (target < other.end && uint64_t(target) + size > other.begin)
            throw std::runtime_error("nested aliases are not supported");
        auto region = std::find_if(regions.begin(), regions.end(), [target, size](const auto &r) {
            return r.begin <= target && uint64_t(target) + size <= r.end;
        });
        if (region == regions.end()) throw std::runtime_error("alias must target one mapped region");
        uint32_t flags = region->flags;
        map(address, size, flags);
        aliases.push_back({address, uint64_t(address) + size, target});
    }
    const Page *find_page(uint32_t address) const {
        const auto &group = pages[address >> 22];
        return group ? (*group)[(address / PAGE) & 1023].get() : nullptr;
    }
    Page &ensure_page(uint32_t address) {
        auto &group = pages[address >> 22];
        if (!group) group = std::make_unique<PageGroup>();
        auto &page = (*group)[(address / PAGE) & 1023];
        if (!page) page = std::make_unique<Page>();
        return *page;
    }
    uint8_t byte(uint32_t address) const {
        address = physical(address);
        const auto *page = find_page(address);
        return page ? page->data[address % PAGE] : 0;
    }
    Page *direct(uint32_t address, uint32_t flags) {
        auto &denied = (flags == C6_READ ? indirect_read : indirect_write)[(address / PAGE) % indirect_read.size()];
        if (denied == address / PAGE) return nullptr;
        auto *host = direct_page(address, flags);
        if (!host) denied = address / PAGE;
        return host;
    }
    Page *direct_page(uint32_t address, uint32_t flags) {
        uint64_t begin = address & ~(PAGE - 1), end = begin + PAGE;
        auto &device = device_pages[begin / PAGE];
        if (!device) device = board.device_page(uint32_t(begin)) ? 2 : 1;
        if (device == 2) return nullptr;
        bool allowed = false;
        for (const auto &region : regions)
            if (region.begin <= begin && end <= region.end && (region.flags & flags) == flags) allowed = true;
        if (!allowed) return nullptr;
        uint32_t target = uint32_t(begin);
        for (const auto &alias : aliases) if (begin < alias.end && end > alias.begin) {
            target = alias.target + uint32_t(begin - alias.begin);
            // A direct page is one host page at the same offsets as the guest's.
            if (alias.begin > begin || alias.end < end || target % PAGE) return nullptr;
        }
        return &ensure_page(target);
    }
    // An aligned-form access ignores the low address bits (measured on the unit in cached DDR,
    // M1 bench I4: LDDW, LDW and STW, no exception). Not measured at a device or in reserved low
    // memory: that still stops, and so does a misaligned load from the empty EMIFA chip select under the
    // low-read option. A store there is dropped as any other (the bench's own store was at 0x4630314e).
    uint32_t round_down(uint32_t address, uint32_t size, const char *what) {
        uint32_t aligned = address & ~(size - 1u);
        if (((board.reserved_low_writes || board.reserved_low_reads) && aligned < Board::RESERVED_END) || board.contains(aligned, std::min(size, 4u)) ||
            (board.reserved_low_reads && what[0] == 'l' && emifa(aligned)))
            throw std::runtime_error(std::string("unaligned ") + what + " outside RAM at " + hex(address));
        return aligned;
    }
    // Opt-in model of a CPU read of reserved low memory or of the empty EMIFA chip select 0. On the unit such a
    // read returns data the CPU loaded earlier, with no exception or event flag (bench M1 I1/I4, M2 L1-L8): the
    // data of its loads is held as eight byte lanes, each load replaces the lanes it reads (address bits 2:0 and
    // the size), and the read returns the lanes its own address picks. Loads from a device count; stores, low
    // reads and EMIFA reads do not. Each data path holds its own data (bench M3 S1-S12): a load into a side A
    // register (T1) replaces held[0], one into a side B register (T2) held[1], and a read returns the data of the
    // path of its own destination register. The side of the address register plays no part (S5-S8), and a load
    // in an interrupt handler counts like any other (S12). Side A's data is 0 after reset, as the unit's first
    // two reads showed (M2 L9); side B's first value was not measured and is taken to be 0 as well.
    uint64_t held[2] = {0, 0};
    bool held_read(uint32_t address) const { return board.reserved_low_reads && (address < Board::RESERVED_END || emifa(address)); }
    uint64_t cpu_load(uint32_t address, uint32_t size, bool side_b) {
        if (held_read(address)) {
            recur.impure = true;
            unsigned shift = (address & 7) * 8;
            const uint64_t data = held[side_b];
            uint64_t value = shift ? data >> shift | data << (64 - shift) : data;
            if (size < 8) value &= (1ull << (size * 8)) - 1;
            board.reserved_read_count++;
            if (board.reserved_reads.size() < 4096) board.reserved_reads.push_back({cycles, value, fault_address, address, size});
            return value;
        }
        uint64_t raw = load(address, size);
        c6b_hold(held[side_b], address, raw, size);
        return raw;
    }
    uint64_t load(uint32_t address, uint32_t size) {
        auto &entry = direct_read[(address / PAGE) % direct_read.size()];
        if (entry.page == address / PAGE && address % PAGE + size <= PAGE) {
            uint64_t result = 0;
            const uint8_t *data = entry.host->data.data() + address % PAGE;
            if (recur.recording) {
                uint32_t at = entry.physical + address % PAGE;
                if (recur.loads.size() + 2 > Recurrence::MAX_WORDS) recur.impure = true;
                else for (uint32_t word = at & ~7u; word < at + size; word += 8) recur.loads.push_back(word);
            }
            if constexpr (std::endian::native == std::endian::little) std::memcpy(&result, data, size);
            else for (uint32_t i = 0; i < size; i++) result |= uint64_t(data[i]) << (i * 8);
            return result;
        }
        if (board.contains(address, size)) {
            recur.impure = true;
            return board.read(address, size, cycles, fault_address);
        }
        check(address, size, C6_READ);
        uint64_t result = 0;
        // Aliases align to 32 bytes. Within one such span, translation and the
        // sparse-page lookup can be shared by all bytes of the guest load.
        if (address % 32 + size <= 32) {
            uint32_t at = physical(address);
            if (entry.page != address / PAGE) if (auto *host = direct(address, C6_READ)) entry = {address / PAGE, at & ~(PAGE - 1), host};
            const auto *page = find_page(at);
            if (recur.recording) {
                if (recur.loads.size() + 2 > Recurrence::MAX_WORDS) recur.impure = true;
                else for (uint32_t word = at & ~7u; word < at + size; word += 8) recur.loads.push_back(word);
            }
            if (!page) return 0;
            const uint8_t *data = page->data.data() + at % PAGE;
            if constexpr (std::endian::native == std::endian::little) std::memcpy(&result, data, size);
            else for (uint32_t i = 0; i < size; i++) result |= uint64_t(data[i]) << (i * 8);
            return result;
        }
        recur.impure = true; // Unaligned across a fetch-packet span: rare, not tracked.
        for (uint32_t i = 0; i < size; i++) result |= uint64_t(byte(address + i)) << (i * 8);
        return result;
    }
    // EMIFA chip select 0 has nothing on it. On the unit CPU stores there complete without a stall,
    // an exception or an event flag (M1 bench I6, three words at 0x4630314c); the whole chip-select
    // range is assumed to behave the same. They are dropped and counted. Reads still stop.
    uint64_t emifa_stores = 0;
    uint32_t emifa_address = 0, emifa_pc = 0;
    bool emifa(uint32_t address) const { return board.enabled && address - 0x40000000u < 0x20000000u; }
    void enable_board(bool profile) {
        for (const auto &region : regions)
            if (region.begin < 0x60000000u && region.end > 0x40000000u)
                throw std::runtime_error("the board does not map RAM in the EMIFA range");
        board.enable(profile);
        emifa_stores = 0; emifa_address = emifa_pc = 0;
    }
    void write(uint32_t address, const uint8_t *data, uint32_t size, bool guest, uint32_t writer_pc = UINT32_MAX) {
        if (writer_pc == UINT32_MAX) writer_pc = fault_address;
        if (guest && writer_pc != 0xfffffff0 && emifa(address)) {
            recur.impure = true; emifa_stores++; emifa_address = address; emifa_pc = writer_pc; return;
        }
        if (address < Board::RESERVED_END && board.reserved_write(address, data, size, cycles, writer_pc, guest)) {
            recur.impure = true; return;
        }
        if (board.contains(address, size)) {
            recur.impure = true;
            uint32_t value = 0;
            for (uint32_t i = 0; i < size; i++) value |= uint32_t(data[i]) << (i * 8);
            board.write(address, value, size, cycles, writer_pc, guest); return;
        }
        check(address, size, guest ? C6_WRITE : 0);
        for (uint32_t i = 0; i < size;) {
            uint32_t count = std::min(size - i, 32 - (address + i) % 32);
            uint32_t at = physical(address + i);
            auto &page = ensure_page(at);
            if (recur.recording) {
                if (recur.stores.size() + 4 > Recurrence::MAX_WORDS) recur.impure = true;
                else for (uint32_t word = at & ~7u; word < at + count; word += 8) {
                    uint64_t old; std::memcpy(&old, page.data.data() + word % PAGE, 8);
                    recur.stores.push_back({word, old});
                }
                if (std::memcmp(page.data.data() + at % PAGE, data + i, count)) recur.varying = true;
            } else if (!recur.looking && !recur.proven) {
            } else if (!std::memcmp(page.data.data() + at % PAGE, data + i, count)) {
                // Rewrites what is there (a receive DMA's sink byte, say): nothing can tell.
            } else if (recur.looking || !guest || writer_pc == 0xfffffff0) {
                // A device or host write; the CPU's own stores were proven to change nothing.
                if (page.decoded[(at % PAGE) / 32]) recur.proven = false;
                else for (uint32_t word = at & ~7u; recur.proven && word < at + count; word += 8)
                    if (recur.touched(word)) recur.proven = false;
                // Every write of an event run ahead is kept, also those after the proof fell:
                // if the event must be held back, all of them are undone together.
                if (recur.looking) {
                    Recurrence::Ahead entry{&page, at % PAGE, count, {}, {}};
                    std::memcpy(entry.before.data(), page.data.data() + at % PAGE, count);
                    std::memcpy(entry.after.data(), data + i, count);
                    recur.ahead.push_back(entry);
                }
            }
            std::memcpy(page.data.data() + at % PAGE, data + i, count);
            // Aliases align to fetch packets, so this span has one translation and
            // one version counter, even at RAM-page or partial-alias boundaries.
            ++page.versions[(at % PAGE) / 32];
            i += count;
        }
    }
    // A CPU store to a page already known to be ordinary writable RAM.
    bool store_direct(uint32_t address, uint64_t value, uint32_t size) {
        auto &entry = direct_write[(address / PAGE) % direct_write.size()];
        uint32_t offset = address % PAGE;
        if (entry.page != address / PAGE || offset + size > PAGE) return false;
        if (recur.recording) {
            uint32_t at = entry.physical + offset;
            if (recur.stores.size() + 2 > Recurrence::MAX_WORDS) recur.impure = true;
            else for (uint32_t word = at & ~7u; word < at + size; word += 8) {
                uint64_t old; std::memcpy(&old, entry.host->data.data() + word % PAGE, 8);
                recur.stores.push_back({word, old});
            }
            uint64_t before = 0;
            if constexpr (std::endian::native == std::endian::little) std::memcpy(&before, entry.host->data.data() + offset, size);
            else recur.varying = true;
            if (before != (size == 8 ? value : value & ((uint64_t(1) << (size * 8)) - 1))) recur.varying = true;
        }
        if constexpr (std::endian::native == std::endian::little) std::memcpy(entry.host->data.data() + offset, &value, size);
        else for (uint32_t i = 0; i < size; i++) entry.host->data[offset + i] = uint8_t(value >> (i * 8));
        ++entry.host->versions[offset / 32];
        if ((offset + size - 1) / 32 != offset / 32) ++entry.host->versions[offset / 32 + 1];
        return true;
    }
    bool writable_direct(uint32_t address, uint32_t size) {
        auto &entry = direct_write[(address / PAGE) % direct_write.size()];
        if (entry.page == address / PAGE) return address % PAGE + size <= PAGE;
        if (address % PAGE + size > PAGE) return false;
        auto *host = direct(address, C6_WRITE);
        if (host) entry = {address / PAGE, physical(address) & ~(PAGE - 1), host};
        return host != nullptr;
    }
    uint64_t *version(uint32_t fetch) {
        fetch = physical(fetch);
        auto &page = ensure_page(fetch);
        page.decoded[(fetch % PAGE) / 32] = true;
        return &page.versions[(fetch % PAGE) / 32];
    }
    uint32_t reg(int32_t index) const {
        if (index < 0 || index >= int32_t(regs.size())) throw std::runtime_error("invalid register");
        if (index == int32_t(TSCL)) recur.impure = true;
        if (index == int32_t(TSCL)) return uint32_t(tsc_running && cycles >= tsc_start ? cycles - tsc_start : 0);
        if (index == 67 || index == 68) return 0; // ISR/ICR are write-only.
        if (index == 89) return fault_address & ~31u; // PCE1 is the issuing fetch-packet address.
        if (index == 71) {
            uint32_t enabled = regs[65] & regs[66] & 0xfff0;
            return (regs[71] & ~1023u) | (enabled ? std::countr_zero(enabled) << 5 : 0);
        }
        return regs[index];
    }
    void delay(const Write &write) {
        auto &slot = due[write.due % Due::SLOTS];
        if (write.due - cycles >= Due::SLOTS || write.due <= cycles || slot.count == Due::ROOM || !pending.empty())
            pending.push_back(write);
        else slot.writes[slot.count++] = {write.reg, write.value};
        pending_count++;
    }
    uint64_t next_result() const {
        uint64_t stop = UINT64_MAX;
        for (const auto &write : pending) stop = std::min(stop, write.due);
        for (uint64_t at = cycles + 1; at < cycles + Due::SLOTS && at < stop; at++)
            if (due[at % Due::SLOTS].count) return at;
        return stop;
    }
    static void valid_register(int32_t index) {
        if (index < 0 || index >= 96) throw std::runtime_error("invalid register");
    }
    uint32_t value(const c6_operand &op) const {
        if (op.kind == C6_IMMEDIATE) return uint32_t(op.value);
        if (op.kind == C6_REGISTER) return reg(op.reg);
        throw std::runtime_error("unsupported scalar operand");
    }
    uint64_t pair(const c6_operand &op) const {
        if (op.kind != C6_PAIR) return value(op);
        return uint64_t(reg(op.aux)) | (uint64_t(reg(op.reg)) << 32);
    }
    int64_t long_value(const c6_operand &op) const {
        if (op.kind != C6_PAIR) return signed32(value(op));
        uint64_t bits = pair(op) & 0xffffffffffull;
        return bits & (uint64_t(1) << 39) ? int64_t(bits) - (int64_t(1) << 40) : int64_t(bits);
    }
    void result(std::vector<Write> &out, const c6_operand &dst, uint64_t value, uint64_t due) const {
        if (dst.kind == C6_PAIR) {
            valid_register(dst.reg); valid_register(dst.aux);
            out.push_back({due, uint32_t(dst.aux), uint32_t(value)});
            out.push_back({due, uint32_t(dst.reg), uint32_t(value >> 32)});
        } else {
            if (dst.kind != C6_REGISTER) throw std::runtime_error("destination is not a register");
            valid_register(dst.reg);
            out.push_back({due, uint32_t(dst.reg), uint32_t(value)});
        }
    }
    uint32_t address(const c6_operand &op, uint32_t size, std::vector<Write> &writes) const {
        if (op.kind != C6_MEMORY) throw std::runtime_error("expected a memory operand");
        uint32_t base = reg(op.reg);
        int64_t offset = op.aux < 0 ? op.value : signed32(reg(op.aux));
        if (op.flags & C6_SCALED) offset *= size;
        if (op.flags & C6_MINUS) offset = -offset;
        uint32_t updated = base + uint32_t(offset);
        if (op.flags & (C6_PRE | C6_POST)) writes.push_back({cycles, uint32_t(op.reg), updated});
        return op.flags & C6_POST ? base : updated;
    }
    void reset(uint32_t entry, uint32_t sentinel, bool stop) {
        release_held(); // A reset breaks the timeline the held effects were waiting on.
        regs.fill(0); pending.clear(); branches.clear(); late.clear();
        for (auto &slot : due) slot.count = 0;
        pending_count = 0;
        regs[64] = 0x100; regs[65] = 1; // Little-endian CPU reset state (SPRUFE8B 5.3.4.1).
        regs[87] = 0x0700001d;
        irq_writes.clear(); interrupt_blocked_until = interrupt_due = interrupt_count = loop_interrupt_count = 0;
        sat_due = 0; sat_units = 0; idling = false;
        loop = Loop{}; loop_active = false; draining.clear(); reload_pending = reload_landed = false;
        loop_resume = false;
        guest_profile = GuestProfile{};
        tsc_running = false; tsc_start = 0;
        pc = entry; cycles = packets = 0; idle = 0; status = C6_BUDGET; error.clear(); fault_address = 0; held[0] = held[1] = 0;
        return_address = sentinel; stop_on_return = stop;
        if (stop) regs[35] = sentinel; // B3, as a caller returning from a function.
    }
    bool valid(const Packet &packet) const {
        for (uint32_t i = 0; i < packet.dependency_count; i++)
            if (*packet.dependencies[i].first != packet.dependencies[i].second) return false;
        return true;
    }
    const Packet *fetch(uint32_t address) {
        auto &slot = fetch_slots[(address >> 1) & (fetch_slots.size() - 1)];
        if (slot.packet && slot.address == address) return slot.packet;
        auto found = cache.find(address);
        if (found == cache.end()) return nullptr;
        slot = {address, &found->second};
        return slot.packet;
    }
    static bool starts_loop(uint32_t opcode) {
        return opcode == C6_SPLOOP || opcode == C6_SPLOOPD || opcode == C6_SPLOOPW;
    }
    bool prepare_loop(const Packet &packet, Loop &candidate) {
        auto found = std::find_if(packet.ops.begin(), packet.ops.end(), [](const auto &op) {
            return starts_loop(op.ins.opcode);
        });
        if (found == packet.ops.end()) return true;
        const auto *first = &found->ins;
        candidate.kind = first->opcode; candidate.ii = value(first->operands[0]); candidate.pc = first->address;
        candidate.predicate = first->predicate; candidate.invert = first->invert;
        candidate.nested = candidate.predicate >= 0 && candidate.kind != C6_SPLOOPW;
        if (!candidate.ii || candidate.ii > 14) throw std::runtime_error("SPLOOP ii must be 1..14");
        if (candidate.kind == C6_SPLOOPW && candidate.predicate < 0)
            throw std::runtime_error("SPLOOPW needs a predicate");
        uint32_t cursor = packet.next, offset = 0;
        for (uint32_t count = 0; count < 1024; count++) {
            const auto *decoded = fetch(cursor);
            if (!decoded || !valid(*decoded)) {
                decode_address = cursor; status = C6_DECODE; return false;
            }
            const auto &body = *decoded;
            LoopRow row{offset, 0, {}};
            bool kernel = false;
            uint32_t length = 1;
            for (const auto &op : body.ops) {
                const auto &ins = op.ins;
                if (ins.opcode == C6_SPMASK) row.mask |= value(ins.operands[0]);
                else if (ins.opcode == C6_SPMASKR || starts_loop(ins.opcode))
                    throw std::runtime_error("nested SPLOOP control at " + hex(ins.address) + " (opcode " + std::to_string(ins.opcode) + ") is not implemented");
                else if (ins.opcode == C6_SPKERNELR) {
                    // Post-loop code and the reload both start with the first epilog cycle (7.5.2.2).
                    if (!candidate.nested) throw std::runtime_error("SPKERNELR at " + hex(ins.address) + " without a conditional SPLOOP(D)");
                    kernel = true; candidate.kernel_reload = true;
                } else if (ins.opcode == C6_SPKERNEL) {
                    kernel = true;
                    if (ins.reserved & 0x10000) {
                        uint32_t field = ins.reserved >> 8 & 63;
                        uint32_t cbits = candidate.ii <= 1 ? 0 : candidate.ii <= 2 ? 1 : candidate.ii <= 4 ? 2 : candidate.ii <= 8 ? 3 : 4;
                        uint32_t fcyc = field & ((1u << cbits) - 1), fstg = 0;
                        for (uint32_t j = 0; j < 6 - cbits; j++) fstg |= ((field >> (5 - j)) & 1) << j;
                        candidate.delay = fstg * candidate.ii + fcyc;
                    } else candidate.delay = value(ins.operands[0]) * candidate.ii + value(ins.operands[1]);
                } else if (ins.opcode == C6_NOP) length = std::max(length, ins.count ? value(ins.operands[0]) : 1u);
                else {
                    row.instructions.push_back(op);
                    if (body.protected_load && ins.opcode >= C6_LDW && ins.opcode <= C6_LDNDW) length = std::max(length, 5u);
                }
            }
            row.phase = row.offset % candidate.ii; row.stage = row.offset / candidate.ii;
            candidate.rows.push_back(std::move(row));
            offset += length; cursor = body.next;
            if (kernel) {
                candidate.length = offset; candidate.boundary = ((offset + candidate.ii - 1) / candidate.ii) * candidate.ii;
                candidate.after = cursor; return true;
            }
        }
        throw std::runtime_error("SPLOOP body has no SPKERNEL within 1024 packets");
    }
    void begin_loop(Loop candidate, bool resumed) {
        if (resumed) {
            // 7.13.2: masked instructions were set-up code and do not run again, and an SPLOOPD
            // tests and counts like an SPLOOP.
            candidate.reloaded = true;
            if (candidate.kind == C6_SPLOOPD) candidate.kind = C6_SPLOOP;
        }
        candidate.start = cycles + 1; candidate.ilc = regs[76];
        if (candidate.kind == C6_SPLOOP) {
            candidate.loading_only = candidate.ilc == 0;
            if (candidate.ilc) candidate.ilc--;
        }
        if (candidate.kind != C6_SPLOOPW) regs[76] = candidate.ilc;
        loop = std::move(candidate); loop_active = true; loop_native = nullptr;
    }
    static void buffered(const Loop &buffer, uint64_t time, std::vector<const Op *> &out, uint32_t mask = 0) {
        uint64_t stage; uint32_t phase;
        if (time <= UINT32_MAX) { stage = uint32_t(time) / buffer.ii; phase = uint32_t(time) % buffer.ii; }
        else { stage = time / buffer.ii; phase = uint32_t(time % buffer.ii); }
        for (const auto &row : buffer.rows) {
            // The same phase at or after the row's offset: a whole number of iterations later.
            if (row.phase != phase || time < row.offset) continue;
            uint64_t iteration = stage - row.stage;
            if (iteration >= buffer.started) continue;
            for (const auto &op : row.instructions) {
                uint32_t unit = op.ins.reserved & 255;
                if (unit & mask) continue;
                bool masked = unit & row.mask;
                if (buffer.loading_only ? masked && !buffer.reloaded : !((iteration || buffer.reloaded) && masked)) out.push_back(&op);
            }
        }
    }
    bool advance_loop() {
        uint64_t time = cycles - loop.start;
        if (loop.predicate >= 0 && (loop.term < 0 || loop.loading_only || loop.interrupted))
            loop.history = loop.history << 1 | loop_condition(loop);
        if (loop.interrupted && loop.kind == C6_SPLOOPW && time > uint64_t(loop.term) && time % loop.ii == 0 &&
            !(loop.history >> 4 & 1)) {
            // 7.10.3: the condition ended the loop while it drained for the interrupt. The buffer
            // goes idle and the interrupt is taken at the packet after the loop body.
            pc = loop.after; loop_active = false; loop.interrupted = false;
            return enter_interrupt();
        }
        if (time && time % loop.ii == 0 && loop.term < 0) {
            if (loop.kind == C6_SPLOOPW) {
                // 7.10.2: the condition as it stood 4 cycles before this boundary (read 3 cycles
                // ahead of it), so never in the first 3 cycles. cl6x output depends on the delay.
                if (time > 3 && (loop.stopping || !(loop.history >> 4 & 1))) {
                    if (time >= loop.boundary) loop.term = int64_t(time);
                    else loop.stopping = true;
                }
            } else if (loop.loading_only) loop.term = 0;
            else if (loop.kind == C6_SPLOOPD && time <= 3) { }
            else if (!loop.ilc) loop.term = int64_t(time);
            else loop.ilc--;
            if (loop.term < 0) loop.started++;
            else if (loop.nested) { loop.sampled = time >= 4; loop.reload = loop.sampled && (loop.history >> 4 & 1); }
        }
        if (loop.loading_only && loop.term < 0) loop.term = 0;
        if (loop.term >= 0) {
            if (loop.interrupted) // Every started iteration finishes; program fetch stays off.
                loop.post = loop.end = std::max((loop.started - 1) * loop.ii + loop.length, uint64_t(loop.term));
            else if (loop.kind == C6_SPLOOPW) loop.post = loop.end = uint64_t(loop.term);
            else {
                loop.end = std::max((loop.started - 1) * loop.ii + loop.length, uint64_t(loop.boundary));
                loop.post = std::min(loop.end, std::max(uint64_t(loop.term), uint64_t(loop.boundary)) + loop.delay);
            }
            if (time >= loop.post) {
                loop_active = false;
                if (loop.kind != C6_SPLOOPW) regs[76] = loop.ilc;
                if (loop.interrupted) {
                    loop.interrupted = false;
                    pc = loop.pc; loop_resume = true; loop_resume_pc = pc;
                    if (!enter_interrupt()) throw std::runtime_error("the interrupt was withdrawn while the loop buffer drained for it");
                    return true;
                }
                pc = loop.after;
                if (loop.nested && loop.loading_only && loop.reloaded) {
                    // A skipped invocation: the reload condition is evaluated again (7.9.6.2).
                    loop.sampled = time >= 4; loop.reload = loop.sampled && (loop.history >> 4 & 1);
                }
                if (loop.post < loop.end && !loop.loading_only) draining.push_back(loop);
                if (loop.kernel_reload) begin_reload(cycles);
                // The buffer may be idle from this cycle: a pending interrupt is taken before the
                // first post-loop packet.
                return enter_interrupt();
            }
        }
        buffered_ops.clear();
        buffered(loop, time, buffered_ops);
        if (!buffered_ops.empty()) issue(buffered_ops.data(), buffered_ops.size(), pc, 0);
        return true;
    }
    bool loop_condition(const Loop &buffer) const { return (reg(uint32_t(buffer.predicate)) != 0) != buffer.invert; }
    // The reload point of a nested loop: an SPMASKR in the post-loop code (the new invocation
    // starts on the next cycle) or, with SPKERNELR, the first epilog cycle (it starts in this one).
    // If the reload condition held, the buffer starts the invocation at cycle `start`, alongside
    // the program and the previous invocation's epilog. RILC is read now: with RILC = 0 the
    // invocation is skipped, issuing nothing until its last stage boundary.
    void begin_reload(uint64_t start) {
        if (loop_active || !loop.nested) throw std::runtime_error("SPMASKR without a conditional SPLOOP(D)");
        if (!loop.sampled)
            throw std::runtime_error("reload condition of a zero-iteration or very short nested SPLOOP is not implemented");
        if (reload_pending) throw std::runtime_error("SPMASKR while the loop buffer is already reloading");
        if (!loop.reload) return;
        Loop next = loop;
        next.kind = C6_SPLOOP; next.start = start; next.started = 1; next.term = -1; next.post = 0;
        next.end = UINT64_MAX; next.loading_only = !regs[77]; next.ilc = regs[77] ? regs[77] - 1 : 0;
        // reload_step keeps the history from the cycle after this one.
        next.history = start == cycles ? loop_condition(loop) : 0;
        next.reload = next.sampled = false; next.reloaded = next.reloading = next.from_reload = true;
        loop.reload = false; regs[76] = 0;
        draining.push_back(std::move(next)); reload_pending = true; reload_landed = false;
    }
    // Each cycle while a reloading invocation overlaps the program. Program fetch stops, and the
    // invocation becomes the active loop, after the last delay slot of a taken branch or once the
    // whole body is enabled again (7.9.6.3).
    void reload_step() {
        auto found = std::find_if(draining.begin(), draining.end(), [](const auto &buffer) { return buffer.reloading; });
        if (found == draining.end()) throw std::runtime_error("reloading loop buffer was lost");
        if (cycles < found->start) return;
        uint64_t time = cycles - found->start;
        if (reload_landed || time >= found->length) {
            found->after = pc; found->reloading = false; found->end = 0;
            loop = std::move(*found); draining.erase(found);
            loop_active = true; loop_native = nullptr; reload_pending = reload_landed = false;
            return;
        }
        found->history = found->history << 1 | loop_condition(*found);
        if (time && time % found->ii == 0 && !found->loading_only) {
            if (!found->ilc) throw std::runtime_error("early exit of a reloading SPLOOP is not implemented");
            found->ilc--; found->started++;
        }
    }
    void epilog(uint32_t mask, std::vector<const Op *> &instructions) {
        for (const auto &buffer : draining) if (cycles >= buffer.start && cycles - buffer.start < buffer.end)
            buffered(buffer, cycles - buffer.start, instructions, mask);
        std::erase_if(draining, [this](const auto &buffer) { return cycles - buffer.start >= buffer.end; });
    }
    void finish_double(const DoubleJob &job, std::vector<Write> &writes) const {
        const auto &ins = job.instruction;
        auto source = [&](unsigned index) { return floating64(uint64_t(job.low[index]) | (uint64_t(job.high[index]) << 32)); };
        double x = source(0), y = source(1), answer = 0;
        uint64_t bits = 0;
        bool explicit_bits = false;
        switch (ins.opcode) {
        case C6_MPYSP2DP: answer = double(single(job.scalar[0])) * double(single(job.scalar[1])); break;
        case C6_MPYSPDP: answer = double(single(job.scalar[0])) * y; break;
        case C6_MPYDP: answer = x * y; break;
        case C6_ADDDP: answer = x + y; break;
        case C6_SUBDP: answer = x - y; break;
        case C6_INTDP: answer = double(signed32(job.scalar[0])); break;
        case C6_INTDPU: answer = double(job.scalar[0]); break;
        case C6_ABSDP: answer = std::abs(x); break;
        case C6_RCPDP:
            if (std::isnan(x)) answer = std::numeric_limits<double>::quiet_NaN();
            else if (x == 0) answer = std::copysign(std::numeric_limits<double>::infinity(), x);
            else if (std::isinf(x)) answer = std::copysign(0.0, x);
            else { bits = estimate(double_bits(x), 64, false); explicit_bits = true; }
            break;
        case C6_RSQRDP:
            if (std::isnan(x) || x < 0) answer = std::numeric_limits<double>::quiet_NaN();
            else if (x == 0) answer = std::copysign(std::numeric_limits<double>::infinity(), x);
            else if (std::isinf(x)) answer = 0.0;
            else { bits = estimate(double_bits(x), 64, true); explicit_bits = true; }
            break;
        case C6_CMPEQDP: bits = x == y; explicit_bits = true; break;
        case C6_CMPGTDP: bits = x > y; explicit_bits = true; break;
        case C6_CMPLTDP: bits = x < y; explicit_bits = true; break;
        case C6_DPSP: bits = single_bits(float(x)); explicit_bits = true; break;
        case C6_DPTRUNC: case C6_DPINT:
            if (std::isnan(x) || x >= 2147483648.0) bits = 0x7fffffff;
            else if (x < -2147483648.0) bits = 0x80000000;
            else bits = uint32_t(int64_t(ins.opcode == C6_DPINT ? std::nearbyint(x) : std::trunc(x)));
            explicit_bits = true; break;
        default: throw std::runtime_error("unsupported double instruction");
        }
        if (!explicit_bits) bits = double_bits(answer);
        const auto &dst = ins.operands[ins.count - 1];
        uint64_t due = job.issue + double_delay(ins.opcode);
        if (dst.kind == C6_PAIR) {
            writes.push_back({due, uint32_t(dst.aux), uint32_t(bits)});
            writes.push_back({due + 1, uint32_t(dst.reg), uint32_t(bits >> 32)});
        } else result(writes, dst, bits, due + 1);
    }
    // Fills op.micro when the instruction has exactly the operand shape the Micro form
    // assumes; anything else, including malformed operand counts, keeps the general path.
    bool compile(Op &op) {
        const auto &ins = op.ins;
        Micro m;
        if (ins.predicate >= 0 && !op.predicate) return false;
        auto plain = [](int32_t reg) { return reg >= 0 && reg < 96 && reg != 67 && reg != 68 && reg != 71 && reg != int32_t(TSCL) && reg != 89; };
        auto dst = [&](unsigned i) {
            const auto &operand = ins.operands[i];
            if (operand.kind != C6_REGISTER || operand.reg < 0 || operand.reg >= 96) return false;
            m.dst = uint8_t(operand.reg); return true;
        };
        auto memory = [&](unsigned i) {
            const auto &operand = ins.operands[i];
            if (operand.kind != C6_MEMORY || !plain(operand.reg) || (operand.aux >= 0 && !plain(operand.aux))) return false;
            m.base = &regs[operand.reg]; m.index = operand.aux >= 0 ? &regs[operand.aux] : nullptr;
            m.displacement = operand.value; m.mode = uint8_t(operand.flags);
            return operand.flags < 16;
        };
        // A register pair as a destination: low word in dst, high word in high.
        auto pair_dst = [&](unsigned i) {
            const auto &operand = ins.operands[i];
            if (operand.kind != C6_PAIR || operand.reg < 0 || operand.reg >= 96 || operand.aux < 0 || operand.aux >= 96) return false;
            m.dst = uint8_t(operand.aux); m.high = uint8_t(operand.reg); return true;
        };
        auto binary = [&](Micro::Kind kind) {
            if (ins.count != 3 || !op.source[0] || !op.source[1] || !dst(2)) return false;
            m.kind = kind; m.a = op.source[0]; m.b = op.source[1]; return true;
        };
        auto unary = [&](Micro::Kind kind) {
            if (ins.count != 2 || !op.source[0] || !dst(1)) return false;
            m.kind = kind; m.a = op.source[0]; return true;
        };
        bool ok = false;
        switch (ins.opcode) {
        case C6_SPLOOP: case C6_SPLOOPD: case C6_SPLOOPW: case C6_SPMASK: case C6_SPKERNEL: ok = true; break;
        case C6_MVK: case C6_MV: ok = unary(Micro::MOV); break;
        case C6_ZERO: ok = ins.count == 1 && dst(0); m.kind = Micro::MOV; m.a = constant(0); break;
        case C6_MVKH: ok = unary(Micro::MVKH) && op.source[1]; m.b = op.source[1]; break;
        case C6_ADD: ok = binary(Micro::ADD); break;
        case C6_ADDK: ok = ins.count == 2 && op.source[0] && op.source[1] && dst(1);
            m.kind = Micro::ADD; m.a = op.source[1]; m.b = op.source[0]; break;
        case C6_SUB: ok = binary(Micro::SUB); break;
        case C6_AND: ok = binary(Micro::AND); break;
        case C6_OR: ok = binary(Micro::OR); break;
        case C6_XOR: ok = binary(Micro::XOR); break;
        case C6_ANDN: ok = binary(Micro::ANDN); break;
        case C6_NOT: ok = unary(Micro::NOT); break;
        case C6_NEG: ok = unary(Micro::NEG); break;
        case C6_SHL: ok = binary(Micro::SHL); break;
        case C6_SHR: ok = binary(Micro::SHR); break;
        case C6_SHRU: ok = binary(Micro::SHRU); break;
        case C6_CMPEQ: ok = binary(Micro::CMPEQ); break;
        case C6_CMPGT: ok = binary(Micro::CMPGT); break;
        case C6_CMPLT: ok = binary(Micro::CMPLT); break;
        case C6_CMPGTU: ok = binary(Micro::CMPGTU); break;
        case C6_CMPLTU: ok = binary(Micro::CMPLTU); break;
        case C6_EXT: case C6_EXTU: {
            const auto &left = ins.operands[1], &right = ins.operands[2];
            ok = ins.count == 4 && op.source[0] && dst(3) && left.kind == C6_IMMEDIATE && right.kind == C6_IMMEDIATE &&
                uint32_t(left.value) <= 31 && uint32_t(right.value) <= 31;
            m.kind = ins.opcode == C6_EXT ? Micro::EXT : Micro::EXTU; m.a = op.source[0];
            m.left = uint8_t(left.value); m.right = uint8_t(right.value); break;
        }
        case C6_ADDAB: case C6_ADDAH: case C6_ADDAW: case C6_ADDAD: case C6_SUBAB: case C6_SUBAH: case C6_SUBAW:
            ok = binary(Micro::ADDSCALED);
            m.scale = ins.opcode == C6_ADDAH || ins.opcode == C6_SUBAH ? 2 :
                ins.opcode == C6_ADDAW || ins.opcode == C6_SUBAW ? 4 : ins.opcode == C6_ADDAD ? 8 : 1;
            if (ins.opcode >= C6_SUBAB && ins.opcode <= C6_SUBAW) m.scale = -m.scale;
            break;
        case C6_MPY: case C6_MPYU: case C6_MPYSU: case C6_MPYUS:
            ok = binary(Micro::MPY16);
            m.sign = uint8_t((ins.opcode == C6_MPY || ins.opcode == C6_MPYSU ? 1 : 0) | (ins.opcode == C6_MPY || ins.opcode == C6_MPYUS ? 2 : 0));
            break;
        // The low word of a 32 x 32 product does not depend on the operands' signedness.
        case C6_MPY32: case C6_MPY32U: case C6_MPY32SU: case C6_MPY32US:
            ok = binary(Micro::MPY32);
            if (!ok && ins.count == 3 && op.source[0] && op.source[1] && pair_dst(2)) {
                ok = true; m.kind = Micro::MPY32WIDE; m.a = op.source[0]; m.b = op.source[1];
                m.sign = uint8_t((ins.opcode == C6_MPY32 || ins.opcode == C6_MPY32SU ? 1 : 0) |
                                 (ins.opcode == C6_MPY32 || ins.opcode == C6_MPY32US ? 2 : 0));
            }
            break;
        // Signed 16 x signed 32 into a register pair; sign bit 4 selects the 16-bit source.
        case C6_MPYLI:
            if (ins.count == 3 && op.source[0] && op.source[1] && pair_dst(2)) {
                ok = true; m.kind = Micro::MPY32WIDE; m.a = op.source[0]; m.b = op.source[1]; m.sign = 4 | 2;
            }
            break;
        case C6_LMBD: ok = binary(Micro::LMBD); break;
        case C6_MVD: ok = unary(Micro::MOVLATE); break;
        case C6_ROTL: ok = binary(Micro::ROTL); break;
        case C6_DINT: ok = ins.count == 0; m.kind = Micro::DINT; break;
        case C6_RINT: ok = ins.count == 0; m.kind = Micro::RINT; break;
        case C6_MVC: {
            // A move, when nothing else happens: the source is a general register or a control register that
            // reads as its stored value, and the destination is a general register or a control register that
            // only holds what is written (IRP, NRP, ILC, RILC, NTSR, REP). A read of TSCL has its own form. The
            // others keep the general path: they mask the value, mirror it into another register, raise an
            // error or can make an interrupt deliverable.
            const auto &from = ins.operands[0], &to = ins.operands[1];
            auto holds = [](int32_t reg) { return reg < 64 || reg == 69 || reg == 70 || reg == 76 || reg == 77 || reg == 82 || reg == 86; };
            if (ins.count == 2 && to.kind == C6_REGISTER && (to.reg == 64 || to.reg == 65) && op.source[0]) {
                ok = true; m.kind = to.reg == 64 ? Micro::CSRW : Micro::IERW; m.a = op.source[0]; break;
            }
            if (ins.count != 2 || to.kind != C6_REGISTER || !holds(to.reg)) break;
            if (from.kind == C6_REGISTER && from.reg == int32_t(TSCL)) { ok = to.reg < 64 && dst(1); m.kind = Micro::TSC; }
            else ok = unary(Micro::MOV);
            break;
        }
        case C6_ABSSP: ok = unary(Micro::ABSSP); break;
        case C6_SET: case C6_CLR: {
            const auto &low = ins.operands[1], &top = ins.operands[2];
            ok = ins.count == 4 && op.source[0] && dst(3) && low.kind == C6_IMMEDIATE && top.kind == C6_IMMEDIATE &&
                uint32_t(low.value) <= uint32_t(top.value) && uint32_t(top.value) <= 31;
            if (ok) {
                uint32_t x = uint32_t(low.value), y = uint32_t(top.value);
                m.kind = ins.opcode == C6_SET ? Micro::OR : Micro::ANDN; m.a = op.source[0];
                m.b = constant(uint32_t(((uint64_t(1) << (y - x + 1)) - 1) << x));
            }
            break;
        }
        case C6_LDDW: case C6_LDNDW:
            ok = ins.count == 2 && memory(0) && pair_dst(1);
            m.kind = Micro::LOAD; m.size = 8; m.aligned = ins.opcode != C6_LDNDW; break;
        case C6_STDW: case C6_STNDW: {
            const auto &value = ins.operands[0];
            ok = ins.count == 2 && value.kind == C6_PAIR && plain(value.reg) && plain(value.aux) && memory(1);
            if (ok) { m.kind = Micro::STORE; m.size = 8; m.aligned = ins.opcode != C6_STNDW; m.a = &regs[value.aux]; m.b = &regs[value.reg]; }
            break;
        }
        case C6_ADDSP: ok = binary(Micro::ADDSP); break;
        case C6_SUBSP: ok = binary(Micro::SUBSP); break;
        case C6_MPYSP: ok = binary(Micro::MPYSP); break;
        case C6_INTSP: ok = unary(Micro::INTSP); break;
        case C6_INTSPU: ok = unary(Micro::INTSPU); break;
        case C6_SPTRUNC: ok = unary(Micro::SPTRUNC); break;
        case C6_SPINT: ok = unary(Micro::SPINT); break;
        case C6_CMPEQSP: ok = binary(Micro::CMPEQSP); break;
        case C6_CMPGTSP: ok = binary(Micro::CMPGTSP); break;
        case C6_CMPLTSP: ok = binary(Micro::CMPLTSP); break;
        case C6_LDW: case C6_LDH: case C6_LDHU: case C6_LDB: case C6_LDBU: case C6_LDNW:
            ok = ins.count == 2 && memory(0) && dst(1);
            m.kind = Micro::LOAD;
            m.size = ins.opcode == C6_LDB || ins.opcode == C6_LDBU ? 1 : ins.opcode == C6_LDH || ins.opcode == C6_LDHU ? 2 : 4;
            m.sign = ins.opcode == C6_LDB || ins.opcode == C6_LDH; m.aligned = ins.opcode != C6_LDNW;
            break;
        case C6_STW: case C6_STH: case C6_STB: case C6_STNW:
            ok = ins.count == 2 && op.source[0] && memory(1);
            m.kind = Micro::STORE; m.a = op.source[0];
            m.size = ins.opcode == C6_STB ? 1 : ins.opcode == C6_STH ? 2 : 4; m.aligned = ins.opcode != C6_STNW;
            break;
        case C6_B:
            ok = ins.count == 1 && op.source[0];
            m.kind = Micro::BRANCH; m.a = op.source[0];
            m.restore = ins.operands[0].kind == C6_REGISTER && (ins.operands[0].reg == 69 || ins.operands[0].reg == 70)
                ? uint8_t(ins.operands[0].reg - 68) : 0;
            break;
        case C6_BNOP:
            ok = ins.count == 2 && op.source[0] && op.source[1];
            m.kind = Micro::BRANCH; m.a = op.source[0]; m.b = op.source[1]; m.sets_extra = true; break;
        case C6_CALLP:
            ok = ins.count == 2 && op.source[0] && dst(1);
            m.kind = Micro::BRANCH; m.a = op.source[0]; m.link = true; break;
        case C6_BDEC: case C6_BPOS:
            ok = ins.count == 2 && op.source[0] && op.source[1] && dst(1);
            m.kind = ins.opcode == C6_BDEC ? Micro::BDEC : Micro::BPOS; m.a = op.source[0]; m.b = op.source[1]; break;
        case C6_NOP:
            ok = !ins.count || (ins.count == 1 && ins.operands[0].kind == C6_IMMEDIATE &&
                                ins.operands[0].value >= 1 && ins.operands[0].value <= 9);
            m.kind = Micro::NOP; m.extra = ins.count ? uint32_t(ins.operands[0].value) - 1 : 0; break;
        case C6_ADDKPC:
            ok = (ins.count == 2 || (ins.count == 3 && op.source[2])) && op.source[0] && dst(1);
            m.kind = Micro::ADDKPC; m.a = op.source[0]; m.b = op.source[2]; m.sets_extra = ins.count == 3; break;
        default: break;
        }
        if (ok) op.micro = m;
        return ok;
    }
    // Whether nothing but the block's own packets can happen during its static ticks.
    bool block_ready(Block &block, uint64_t end) {
        if (cycles + block.ticks + 1 > end || cycles + block.ticks >= board.next_event() ||
            (held_cycle && cycles + block.ticks >= held_cycle) || !branches.empty() || !pending.empty() ||
            !late.empty() || !irq_writes.empty() || loop_active || !draining.empty() || recur.recording ||
            board.pending_interrupts || sat_due ||
            ((regs[65] & regs[66] & 0xfff0) && (regs[64] & 1) && (regs[65] & 2))) { block_refusals++; return false; }
        if (block.breakpoint_epoch != breakpoint_epoch) {
            block.breakpoint_epoch = breakpoint_epoch;
            block.breakpoint_free = std::none_of(block.later_packets.begin(), block.later_packets.end(),
                                                 [this](uint32_t at) { return breakpoints.contains(at); });
        }
        if (!block.breakpoint_free) { block_refusals++; return false; }
        for (const auto &[counter, value] : block.dependencies)
            if (*counter != value) { block.function = nullptr; return false; } // Its code changed.
        return true;
    }
    void block_bind() {
        auto &c = block_context;
        c.machine = this; c.regs = regs.data(); c.cycles = &cycles; c.packets = &packets;
        c.interrupt_blocked_until = &interrupt_blocked_until; c.pc = &pc; c.idle = &idle;
        c.fault_address = &fault_address; c.pending_count = &pending_count; c.due = due.data();
        c.held = held;
        c.tsc_running = &tsc_running; c.tsc_start = &tsc_start;
        c.direct_read = reinterpret_cast<const C6Direct *>(direct_read.data());
        c.direct_write = reinterpret_cast<const C6Direct *>(direct_write.data());
        c.delay_slow = [](void *machine, uint64_t at, uint32_t reg, uint32_t value) {
            static_cast<Machine *>(machine)->delay({at, reg, value});
        };
        c.branch = [](void *machine, uint64_t at, uint32_t target, uint32_t restore) {
            static_cast<Machine *>(machine)->branches.push_back({at, target, restore});
        };
    }
    struct BlockResult { uint32_t land, reg; std::string value, valid, flag; };
    struct BlockJump { uint32_t issue, restore; std::string taken, target; bool always; };
    // Host code for the instructions issued in one cycle, in the staging order of issue_fast.
    struct BlockCode {
        std::string compute, stores, commits, fresh_declarations;
        std::vector<BlockResult> fresh; std::vector<BlockJump> fresh_jumps;
        uint32_t extra = 0, fault = 0;
        bool memory = false, load_present = false, branch_packet = false;
        bool unmasks = false;  // May make an interrupt deliverable (RINT, a write to CSR or IER): a block ends after it.
        bool timed = false;    // Reads the cycle count: not for a loop body, whose host code is not tied to cycles.
        unsigned branch_ops = 0;
    };
    static std::string block_text(const char *format, auto... values) {
        char buffer[512]; std::snprintf(buffer, sizeof buffer, format, values...); return std::string(buffer);
    }
    // Adds one Micro form issued at `step`; false if it has no host form here.
    bool block_op(const Op &op, uint32_t step, uint32_t next, uint32_t &ids, BlockCode &code) {
        auto text = [](const char *format, auto... values) { return block_text(format, values...); };
        auto is_register = [&](const uint32_t *p) { return p >= regs.data() && p < regs.data() + regs.size(); };
        auto src = [&](const uint32_t *p) {
            return is_register(p) ? text("R[%u]", unsigned(p - regs.data())) : text("0x%08xu", *p);
        };
            const Micro &m = op.micro;
            uint32_t id = ids++, address = op.ins.address;
            bool conditional = op.predicate != nullptr;
            code.fault = address;
            if (op.flags & Op::LOAD) code.load_present = true;
            if (op.flags & Op::BRANCH) code.branch_packet = true;
            if (op.flags & (Op::LOOP | Op::UNSUPPORTED)) return false;
            std::string A = m.a ? src(m.a) : "", B = m.b ? src(m.b) : "", work;
            auto now = [&](uint32_t reg, const std::string &expression, const char *tag = "n") {
                code.compute += text("uint32_t %s%u = 0; bool %se%u = false;\n", tag, id, tag, id);
                work += text("%s%u = %s; %se%u = true; ", tag, id, expression.c_str(), tag, id);
                code.commits += text("if (%se%u) R[%u] = %s%u;\n", tag, id, reg, tag, id);
            };
            auto later = [&](uint32_t delay, uint32_t reg, const std::string &expression, const char *tag = "r") {
                code.fresh_declarations += text("uint32_t %s%u = 0; bool %sv%u = false;\n", tag, id, tag, id);
                work += text("%s%u = %s; %sv%u = true; ", tag, id, expression.c_str(), tag, id);
                code.fresh.push_back({step + delay - 1, reg, text("%s%u", tag, id), conditional || m.kind == Micro::BDEC || m.kind == Micro::BPOS ? text("%sv%u", tag, id) : "", text("%sv%u", tag, id)});
            };
            auto jump = [&](bool always) {
                code.fresh_declarations += text("uint32_t jt%u = 0; bool jv%u = false;\n", id, id);
                work += text("jt%u = %s; jv%u = true; ", id, A.c_str(), id);
                code.fresh_jumps.push_back({step, m.restore, text("jv%u", id), text("jt%u", id), always});
                code.branch_ops++;
            };
            auto single = [&](const char *operation) { return "c6b_bits(c6b_single(" + A + ") " + operation + " c6b_single(" + B + "))"; };
            auto compare = [&](const char *operation) { return "uint32_t(c6b_single(" + A + ") " + operation + " c6b_single(" + B + "))"; };
            switch (m.kind) {
            case Micro::SKIP: break;
            case Micro::MOV: now(m.dst, A); break;
            case Micro::MVKH: now(m.dst, "(" + B + " & 0xffffu) | (" + A + " & 0xffff0000u)"); break;
            case Micro::ADD: now(m.dst, A + " + " + B); break;
            case Micro::SUB: now(m.dst, A + " - " + B); break;
            case Micro::AND: now(m.dst, A + " & " + B); break;
            case Micro::OR: now(m.dst, A + " | " + B); break;
            case Micro::XOR: now(m.dst, A + " ^ " + B); break;
            case Micro::ANDN: now(m.dst, A + " & ~" + B); break;
            case Micro::NOT: now(m.dst, "~" + A); break;
            case Micro::NEG: now(m.dst, "0u - " + A); break;
            case Micro::SHL: now(m.dst, "(" + B + " & 63) >= 32 ? 0u : " + A + " << (" + B + " & 63)"); break;
            case Micro::SHRU: now(m.dst, "(" + B + " & 63) >= 32 ? 0u : " + A + " >> (" + B + " & 63)"); break;
            case Micro::SHR: now(m.dst, "uint32_t(int32_t(" + A + ") >> ((" + B + " & 63) < 31 ? (" + B + " & 63) : 31))"); break;
            case Micro::CMPEQ: now(m.dst, "uint32_t(" + A + " == " + B + ")"); break;
            case Micro::CMPGT: now(m.dst, "uint32_t(int32_t(" + A + ") > int32_t(" + B + "))"); break;
            case Micro::CMPLT: now(m.dst, "uint32_t(int32_t(" + A + ") < int32_t(" + B + "))"); break;
            case Micro::CMPGTU: now(m.dst, "uint32_t(" + A + " > " + B + ")"); break;
            case Micro::CMPLTU: now(m.dst, "uint32_t(" + A + " < " + B + ")"); break;
            case Micro::EXT: now(m.dst, text("uint32_t(int32_t(%s << %u) >> %u)", A.c_str(), m.left, m.right)); break;
            case Micro::EXTU: now(m.dst, text("(%s << %u) >> %u", A.c_str(), m.left, m.right)); break;
            case Micro::ADDSCALED: now(m.dst, text("%s + uint32_t(c6b_signed(%s) * %d)", A.c_str(), B.c_str(), m.scale)); break;
            case Micro::MPY16: {
                std::string x = m.sign & 1 ? "int64_t(int16_t(" + A + "))" : "int64_t(" + A + " & 0xffffu)";
                std::string y = m.sign & 2 ? "int64_t(int16_t(" + B + "))" : "int64_t(" + B + " & 0xffffu)";
                later(2, m.dst, "uint32_t(uint64_t(" + x + " * " + y + "))"); break;
            }
            case Micro::MPY32: later(4, m.dst, A + " * " + B); break;
            case Micro::MPY32WIDE: {
                std::string x = m.sign & 4 ? "uint64_t(int64_t(int16_t(" + A + ")))" : m.sign & 1 ? "uint64_t(c6b_signed(" + A + "))" : "uint64_t(" + A + ")";
                std::string y = m.sign & 2 ? "uint64_t(c6b_signed(" + B + "))" : "uint64_t(" + B + ")";
                later(4, m.dst, "uint32_t(" + x + " * " + y + ")");
                later(4, m.high, "uint32_t((" + x + " * " + y + ") >> 32)", "h"); break;
            }
            case Micro::LMBD: now(m.dst, "c6b_lmbd(" + A + ", " + B + ")"); break;
            case Micro::MOVLATE: later(4, m.dst, A); break;
            case Micro::ROTL: later(2, m.dst, "std::rotl(" + A + ", int(" + B + " & 31))"); break;
            // The four below as in issue_general. The last three can make a pending interrupt deliverable.
            case Micro::DINT: now(72, "(R[72] & ~3u) | ((R[64] & 1u) << 1)", "t"); now(64, "R[64] & ~1u"); break;
            case Micro::RINT: now(72, "(R[72] & ~1u) | ((R[72] >> 1) & 1u)", "t"); now(64, "(R[64] & ~1u) | ((R[72] >> 1) & 1u)"); code.unmasks = true; break;
            case Micro::CSRW:
                now(72, "(R[72] & ~1u) | (" + A + " & 1u)", "t"); now(81, "(R[81] & ~1u) | ((" + A + " >> 1) & 1u)", "i"); now(64, A);
                code.unmasks = true; break;
            case Micro::IERW: now(65, "(" + A + " & 0xfff2u) | (R[65] & 2u) | 1u"); code.unmasks = true; break;
            case Micro::TSC: {
                // The count at this step, as Machine::reg gives it; TSCH takes the high half (SPRUFE8B 2.9.13).
                code.timed = true;
                std::string count = text("c6b_tsc(c, C0 + %u)", step);
                now(m.dst, "uint32_t(" + count + ")");
                now(75, "uint32_t(" + count + " >> 32)", "t"); break;
            }
            case Micro::ABSSP: now(m.dst, "(" + A + " & 0x7f800000u) ? " + A + " & 0x7fffffffu : 0u"); break;
            case Micro::ADDSP: later(4, m.dst, single("+")); break;
            case Micro::SUBSP: later(4, m.dst, single("-")); break;
            case Micro::MPYSP: later(4, m.dst, single("*")); break;
            case Micro::INTSP: later(4, m.dst, "c6b_bits(float(int32_t(" + A + ")))"); break;
            case Micro::INTSPU: later(4, m.dst, "c6b_bits(float(" + A + "))"); break;
            case Micro::SPTRUNC: later(4, m.dst, "c6b_fix(" + A + ", false)"); break;
            case Micro::SPINT: later(4, m.dst, "c6b_fix(" + A + ", true)"); break;
            case Micro::CMPEQSP: now(m.dst, compare("==")); break;
            case Micro::CMPGTSP: now(m.dst, compare(">")); break;
            case Micro::CMPLTSP: now(m.dst, compare("<")); break;
            case Micro::LOAD: case Micro::STORE: {
                if (!m.base || !is_register(m.base) || (m.index && !is_register(m.index))) return false;
                code.memory = true;
                std::string offset = m.index ? "c6b_signed(" + src(m.index) + ")" : text("int64_t(%lldll)", static_cast<long long>(m.displacement));
                if (m.mode & C6_SCALED) offset = "(" + offset + " * " + std::to_string(m.size) + ")";
                if (m.mode & C6_MINUS) offset = "(-" + offset + ")";
                code.compute += text("uint32_t b%u = 0, u%u = 0, a%u = 0;\n", id, id, id);
                work += text("b%u = %s; u%u = b%u + uint32_t(%s); a%u = %s%u; ", id, src(m.base).c_str(), id, id, offset.c_str(), id, m.mode & C6_POST ? "b" : "u", id);
                if (m.mode & (C6_PRE | C6_POST)) now(uint32_t(m.base - regs.data()), text("u%u", id), "w");
                if (m.aligned && m.size > 1) work += text("slow |= (a%u & %uu) != 0; ", id, m.size - 1u);
                if (m.kind == Micro::LOAD) {
                    code.compute += text("uint64_t q%u = 0;\n", id);
                    work += text("q%u = c6b_load(c, a%u, %u, slow, LL[%u]); ", id, id, m.size, m.dst >= 32 ? 1u : 0u);
                    later(5, m.dst, m.sign && m.size == 1 ? text("uint32_t(int32_t(int8_t(q%u)))", id) :
                          m.sign && m.size == 2 ? text("uint32_t(int32_t(int16_t(q%u)))", id) : text("uint32_t(q%u)", id));
                    if (m.size == 8) later(5, m.high, text("uint32_t(q%u >> 32)", id), "h");
                } else {
                    code.compute += text("uint64_t s%u = 0; bool se%u = false;\n", id, id);
                    work += text("s%u = %s; se%u = true; slow |= !c6b_writable(c, a%u, %u); ", id, m.size == 8 ? ("uint64_t(" + A + ") | uint64_t(" + B + ") << 32").c_str() : A.c_str(), id, id, m.size);
                    code.stores += text("if (se%u) c6b_store(c, a%u, s%u, %u);\n", id, id, id, m.size);
                }
                break;
            }
            case Micro::BDEC: case Micro::BPOS: {
                std::string inner;
                std::swap(inner, work);
                jump(false);
                if (m.kind == Micro::BDEC) now(m.dst, B + " - 1");
                work = inner + "if (c6b_signed(" + B + ") >= 0) { " + work + "} ";
                break;
            }
            case Micro::BRANCH:
                if (m.sets_extra) { if (is_register(m.b)) return false; code.extra = *m.b; }
                if (m.link) { if (conditional) return false; now(m.dst, text("0x%08xu", next)); code.extra = 5; }
                jump(!conditional);
                break;
            case Micro::NOP:
                if (conditional) return false;
                code.extra = std::max(code.extra, m.extra); break;
            case Micro::ADDKPC:
                if (m.sets_extra) { if (conditional || is_register(m.b)) return false; code.extra = *m.b; }
                now(m.dst, A); break;
            default: return false;
            }
            if (!work.empty()) {
                if (conditional) code.compute += text("if ((R[%u] != 0) != %s) { %s}\n", unsigned(op.predicate - regs.data()), op.ins.invert ? "true" : "false", work.c_str());
                else code.compute += work + "\n";
            }
        return true;
    }
    // Plans host code for the packets from `entry` along the fall-through path, up to the
    // landing of the first branch that is always taken. Delayed results become locals
    // assigned at their landing step; whatever is still in flight at an exit is handed to
    // the ordinary queues. Returns false if the first packet cannot be compiled.
    // `continuation` is the next PC when the block ended only for length.
    static constexpr uint32_t BLOCK_STEPS = 48;
    bool block_plan(uint32_t entry, Block &block, std::string *source, uint32_t &continuation) {
        std::vector<BlockResult> results; std::vector<BlockJump> jumps;
        std::string declarations, body;
        uint32_t step = 0, at = entry, issued = 0, fault = entry, ids = 0;
        int64_t blocked = -1;
        bool ended = false;
        continuation = 0; block.dependencies.clear(); block.later_packets.clear();
        auto text = [](const char *format, auto... values) {
            char buffer[512]; std::snprintf(buffer, sizeof buffer, format, values...); return std::string(buffer);
        };
        auto leave = [&](uint32_t at_step, uint32_t idle_value, uint32_t next, bool ordinary_tick) {
            std::string out = text("{ *c->cycles = C0 + %u; *c->packets += %u; *c->pc = 0x%08xu; *c->idle = %u; *c->fault_address = 0x%08xu;",
                                   at_step, issued, next, idle_value, fault);
            if (blocked >= 0) out += text(" *c->interrupt_blocked_until = C0 + %u;", unsigned(blocked) + 6);
            for (const auto &r : results) if (r.land >= at_step)
                out += text(" %sc6b_push(c, C0 + %u, %u, %s);", r.valid.empty() ? "" : ("if (" + r.valid + ") ").c_str(), r.land + 1, r.reg, r.value.c_str());
            for (const auto &j : jumps) if (j.issue + 5 >= at_step)
                out += text(" %sc->branch(c->machine, C0 + %u, %s, %u);", j.always ? "" : ("if (" + j.taken + ") ").c_str(), j.issue + 6, j.target.c_str(), j.restore);
            return out + text(" return %s; }\n", ordinary_tick ? "true" : "false");
        };
        while (!ended) {
            const Packet *packet = fetch(at);
            if (!packet || !packet->executable || !valid(*packet) || packet->loop_control || !(packet->nop_cycles || packet->fast)) break;
            uint32_t total = packet->nop_cycles;
            BlockCode code;
            bool ok = true;
            if (!packet->nop_cycles) for (const Op &op : packet->ops) if (!block_op(op, step, packet->next, ids, code)) { ok = false; break; }
            if (!packet->nop_cycles) total = 1 + (packet->protected_load && code.load_present ? std::max(code.extra, 4u) : code.extra);
            // After an instruction that can unmask an interrupt the run loop must look for one at once, so the
            // block ends with that packet; if the packet goes on waiting, the interpreter runs it.
            if (!ok || code.branch_ops > 1 || code.extra > 9 || (code.unmasks && total != 1)) {
                if (!issued) block_reason = "no host form for a packet instruction at " + hex(code.fault);
                break;
            }
            if (step + total > BLOCK_STEPS) { continuation = step ? at : 0; break; }
            // An access that is not plain RAM, or is misaligned, leaves before its packet: the
            // interpreter then runs the whole packet, including any fault it raises.
            std::string refuse = code.memory ? "if (slow) " + leave(step, 0, at, false) + "c->held[0] = LL[0]; c->held[1] = LL[1];\n" : std::string();
            fault = packet->nop_cycles ? packet->ops.front().ins.address : code.fault;
            if (!packet->nop_cycles && code.branch_packet) blocked = step;
            for (uint32_t i = 0; i < packet->dependency_count; i++)
                if (std::find(block.dependencies.begin(), block.dependencies.end(), packet->dependencies[i]) == block.dependencies.end())
                    block.dependencies.push_back(packet->dependencies[i]);
            declarations += code.fresh_declarations;
            results.insert(results.end(), code.fresh.begin(), code.fresh.end());
            jumps.insert(jumps.end(), code.fresh_jumps.begin(), code.fresh_jumps.end());
            if (issued++) block.later_packets.push_back(at);
            body += text("// step %u: packet 0x%08x\n{\n", step, at) + code.compute + refuse + code.stores + code.commits;
            for (uint32_t wait = 0; wait < total && !ended; wait++) {
                uint32_t now_step = step + wait;
                if (wait) body += "{\n";
                for (const auto &j : jumps) if (j.issue + 5 == now_step) {
                    body += (j.always ? std::string() : "if (" + j.taken + ") ") + leave(now_step, total - wait, packet->next, true);
                    ended = j.always;
                }
                if (!ended) {
                    if (now_step < 12) body += text("if (*c->pending_count) c6b_deliver(c, C0 + %u);\n", now_step + 1);
                    for (const auto &r : results) if (r.land == now_step)
                        body += text("%sR[%u] = %s;\n", r.valid.empty() ? "" : ("if (" + r.valid + ") ").c_str(), r.reg, r.value.c_str());
                    block.ticks = now_step + 1;
                }
                body += "}\n";
            }
            step += total; at = packet->next;
            if (code.unmasks && !ended) { continuation = at; break; }
        }
        if (!issued) return false;
        if (!ended) body += leave(step, 0, at, false);
        if (source) *source = text("extern \"C\" bool c6blk_%08x(C6BlockContext *c) {\n", entry) +
            "uint32_t *const R = c->regs; const uint64_t C0 = *c->cycles; bool slow = false; (void)slow; uint64_t LL[2] = {c->held[0], c->held[1]}; (void)LL;\n" + declarations + body + "}\n";
        return true;
    }
    // Plans host code for whole iterations of the SPLOOP or SPLOOPD whose control packet is
    // at `entry`, once every stage of the body is running (`block.steady` cycles after the
    // loop starts) and while the loop counter is not exhausted. A result still in flight at
    // the end of an iteration is carried in a local to the iteration where it lands. The
    // interpreter runs the first and last iterations, where stages come and go.
    bool loop_plan(uint32_t entry, Block &block, std::string *source) {
        const Packet *packet = fetch(entry);
        if (!packet || !packet->executable || !valid(*packet) || !packet->loop_control) return false;
        Loop shape;
        auto kept_status = status; auto kept_decode = decode_address;
        bool prepared = false;
        try { prepared = prepare_loop(*packet, shape); } catch (const std::runtime_error &) { }
        status = kept_status; decode_address = kept_decode;
        if (!prepared || shape.rows.empty()) { block_reason = "loop body cannot be prepared at " + hex(entry); return false; }
        const bool while_loop = shape.kind == C6_SPLOOPW;
        if (while_loop && (shape.predicate < 0 || shape.predicate >= 64)) return false;
        auto text = [](const char *format, auto... values) { return block_text(format, values...); };
        block.dependencies.clear(); block.later_packets.clear();
        auto depend = [&](const Packet &body) {
            for (uint32_t i = 0; i < body.dependency_count; i++)
                if (std::find(block.dependencies.begin(), block.dependencies.end(), body.dependencies[i]) == block.dependencies.end())
                    block.dependencies.push_back(body.dependencies[i]);
        };
        depend(*packet);
        uint32_t cursor = packet->next;
        for (size_t row = 0; row < shape.rows.size(); row++) {
            const Packet *body = fetch(cursor);
            if (!body) return false;
            depend(*body); cursor = body->next;
        }
        const uint32_t ii = shape.ii;
        uint32_t steady = ii, ids = 0, issued = 0, last_fault = 0;
        for (const auto &row : shape.rows) steady = std::max(steady, (row.stage + 1) * ii);
        while (steady <= 3) steady += ii;
        std::vector<BlockCode> phases(ii);
        std::vector<BlockResult> results;
        std::vector<uint32_t> issue_phase; // of each result
        std::string declarations;
        for (uint32_t phase = 0; phase < ii; phase++) {
            BlockCode &code = phases[phase];
            for (const auto &row : shape.rows) if (row.phase == phase) for (const Op &op : row.instructions) {
                if ((op.ins.reserved & 255) & row.mask) continue; // Masked: first iteration only.
                if (!op.fast || !block_op(op, phase, 0, ids, code)) {
                    block_reason = "no host form for loop instruction at " + hex(op.ins.address) + " (opcode " + std::to_string(op.ins.opcode) + ")";
                    return false;
                }
            }
            if (code.branch_ops || code.branch_packet || code.extra || !code.fresh_jumps.empty() || code.unmasks || code.timed) return false;
            if (code.fault) { issued++; last_fault = code.fault; }
            results.insert(results.end(), code.fresh.begin(), code.fresh.end());
            issue_phase.resize(results.size(), phase);
            declarations += code.fresh_declarations;
        }
        if (!issued) return false;
        auto carried = [&](const std::string &name, uint32_t lap) { return lap ? name + "_" + std::to_string(lap) : name; };
        for (const auto &r : results) for (uint32_t lap = 1; lap <= r.land / ii; lap++)
            declarations += text("uint32_t %s = 0; bool %s = false;\n", carried(r.value, lap).c_str(), carried(r.flag, lap).c_str());
        // Leaves before the issue of cycle `step` of the current iteration.
        // `sampled`: the condition history already holds the cycle being left, which the
        // interpreter will sample again.
        auto leave = [&](uint32_t step, bool sampled = false) {
            uint32_t count = 0, fault = last_fault;
            for (uint32_t phase = 0; phase < step; phase++) if (phases[phase].fault) { count++; fault = phases[phase].fault; }
            std::string out = text("{ *c->cycles = C0 + %u; *c->packets += packets + %u; *c->fault_address = 0x%08xu; c->boundaries = done;", step, count, fault);
            if (while_loop) out += sampled ? " c->history = history >> 1;" : " c->history = history;";
            for (size_t index = 0; index < results.size(); index++) for (uint32_t lap = 0; lap <= results[index].land / ii; lap++) {
                const auto &r = results[index];
                // The cycle being left has computed its results; the interpreter issues it again.
                if (r.land - lap * ii < step || (!lap && issue_phase[index] >= step)) continue;
                out += text(" if (%s) c6b_push(c, C0 + %u, %u, %s);", carried(r.flag, lap).c_str(), r.land - lap * ii + 1, r.reg, carried(r.value, lap).c_str());
            }
            return out + " return false; }\n";
        };
        std::string body = "for (;;) {\n";
        // A while-loop's condition is recorded every cycle and judged at each boundary on its value
        // 4 cycles earlier (SPRUFE8B 7.10.2); the interpreter ends the loop.
        const std::string condition = while_loop ? text("((R[%u] != 0) != %s)", unsigned(shape.predicate), shape.invert ? "true" : "false") : "";
        if (while_loop) body += "{ const uint32_t next = history << 1 | " + condition + "; if (!(next >> 4 & 1)) " + leave(0) + "history = next; }\n";
        for (uint32_t phase = 0; phase < ii; phase++) {
            const BlockCode &code = phases[phase];
            body += text("// cycle %u of %u\n{\n", phase, ii);
            if (while_loop && phase) body += "history = history << 1 | " + condition + ";\n";
            body += code.compute;
            if (code.memory) body += "if (slow) " + leave(phase, true) + "c->held[0] = LL[0]; c->held[1] = LL[1];\n";
            if (!phase) body += "done++;\n";
            body += code.stores + code.commits + text("if (*c->pending_count) c6b_deliver(c, C0 + %u);\n", phase + 1);
            for (const auto &r : results) if (r.land % ii == phase)
                body += text("if (%s) R[%u] = %s;\n", carried(r.flag, r.land / ii).c_str(), r.reg, carried(r.value, r.land / ii).c_str());
            body += "}\n";
        }
        for (const auto &r : results) {
            for (uint32_t lap = r.land / ii; lap; lap--)
                body += text("%s = %s; %s = %s; ", carried(r.value, lap).c_str(), carried(r.value, lap - 1).c_str(),
                             carried(r.flag, lap).c_str(), carried(r.flag, lap - 1).c_str());
            body += r.flag + " = false;\n";
        }
        body += text("C0 += %u; packets += %u;\nif (!--left) break;\n}\n", ii, issued) + leave(0);
        block.ticks = ii; block.steady = steady; block.loop = true;
        if (source) *source = text("extern \"C\" bool c6blk_%08x(C6BlockContext *c) {\n", entry) +
            "uint32_t *const R = c->regs; uint64_t C0 = *c->cycles, packets = 0; bool slow = false; (void)slow; uint64_t LL[2] = {c->held[0], c->held[1]}; (void)LL;\n"
            "uint32_t left = c->iterations, done = 0;\n" + (while_loop ? "uint32_t history = c->history;\n" : "") + declarations + body + "}\n";
        return true;
    }
    // How many whole iterations of the active loop its host code may run now; 0 for none.
    uint32_t loop_ready(Block &block, uint64_t end) {
        const bool while_loop = loop.kind == C6_SPLOOPW;
        if (loop.nested || cycles < loop.start + block.steady || loop.term >= 0 || (!while_loop && !loop.ilc) || loop.stopping || idle || loop.loading_only ||
            (cycles - loop.start) % loop.ii || !branches.empty() || !pending.empty() || !late.empty() ||
            !irq_writes.empty() || !draining.empty() || recur.recording || board.pending_interrupts ||
            ((regs[65] & regs[66] & 0xfff0) && (regs[64] & 1) && (regs[65] & 2))) return 0;
        uint64_t limit = std::min(end, board.next_event());
        if (held_cycle) limit = std::min(limit, held_cycle);
        if (limit <= cycles + 1) return 0;
        for (const auto &[counter, value] : block.dependencies)
            if (*counter != value) { block.function = nullptr; loop_native = nullptr; return 0; } // Its code changed.
        return uint32_t(std::min<uint64_t>({(limit - 1 - cycles) / loop.ii, while_loop ? UINT32_MAX : loop.ilc, 1u << 30}));
    }
    // Chooses the host code, if any, for the loop that has just begun at control packet `at`.
    void loop_bind(uint32_t at) {
        auto found = blocks.find(at);
        if (found != blocks.end() && found->second.loop && found->second.function) loop_native = &found->second;
        else if (block_heat_enabled) block_heat[at] += 16;
    }
    void issue_nop(const Packet &packet) {
        // A decoded, unconditional constant NOP still issues as a guest packet.
        // Its RAM dependencies were checked by run, just like other packets.
        fault_address = packet.ops.front().ins.address;
        idle = packet.nop_cycles; pc = packet.next; packets++;
    }
    // Executes Micro forms with the same staging order as the general path below: every
    // source is read before any result is committed; stores, then registers, then delays.
    void issue_fast(const Op *const *ops, size_t count, uint32_t next, uint32_t protected_load) {
        struct { uint32_t first, second; } now[2 * FAST_OPS]; // Deliberately uninitialized.
        Write later[2 * FAST_OPS];
        Store stores[FAST_OPS];
        Branch branch{0, 0, 0};
        unsigned immediates = 0, results = 0, stored = 0, branched = 0;
        uint32_t extra = 0;
        bool load_present = false;
        for (size_t index = 0; index < count; index++) {
            const Op &op = *ops[index];
            const Micro &m = op.micro;
            fault_address = op.ins.address;
            if (op.flags) {
                if (op.flags & Op::LOAD) load_present = true;
                if (op.flags & Op::BRANCH) interrupt_blocked_until = cycles + 6;
            }
            if (m.kind == Micro::SKIP) continue;
            if (op.predicate && ((*op.predicate != 0) == bool(op.ins.invert))) {
                // A skipped BNOP or ADDKPC still spends its NOP cycles (SPRUFE8B 3.8.10).
                if (op.ins.opcode == C6_BNOP || (m.kind == Micro::ADDKPC && m.sets_extra)) extra = *m.b;
                continue;
            }
            uint32_t x, y, v;
            switch (m.kind) {
            case Micro::SKIP: break;
            case Micro::MOV: now[immediates++] = {m.dst, *m.a}; break;
            case Micro::MVKH: now[immediates++] = {m.dst, (*m.b & 0xffffu) | (*m.a & 0xffff0000u)}; break;
            case Micro::ADD: now[immediates++] = {m.dst, *m.a + *m.b}; break;
            case Micro::SUB: now[immediates++] = {m.dst, *m.a - *m.b}; break;
            case Micro::AND: now[immediates++] = {m.dst, *m.a & *m.b}; break;
            case Micro::OR: now[immediates++] = {m.dst, *m.a | *m.b}; break;
            case Micro::XOR: now[immediates++] = {m.dst, *m.a ^ *m.b}; break;
            case Micro::ANDN: now[immediates++] = {m.dst, *m.a & ~*m.b}; break;
            case Micro::NOT: now[immediates++] = {m.dst, ~*m.a}; break;
            case Micro::NEG: now[immediates++] = {m.dst, 0u - *m.a}; break;
            case Micro::SHL: x = *m.a; y = *m.b & 63; now[immediates++] = {m.dst, y >= 32 ? 0 : x << y}; break;
            case Micro::SHRU: x = *m.a; y = *m.b & 63; now[immediates++] = {m.dst, y >= 32 ? 0 : x >> y}; break;
            case Micro::SHR: x = *m.a; y = *m.b & 63;
                now[immediates++] = {m.dst, uint32_t(signed32(x) >> std::min(y, 31u))}; break;
            case Micro::CMPEQ: now[immediates++] = {m.dst, *m.a == *m.b}; break;
            case Micro::CMPGT: now[immediates++] = {m.dst, int32_t(*m.a) > int32_t(*m.b)}; break;
            case Micro::CMPLT: now[immediates++] = {m.dst, int32_t(*m.a) < int32_t(*m.b)}; break;
            case Micro::CMPGTU: now[immediates++] = {m.dst, *m.a > *m.b}; break;
            case Micro::CMPLTU: now[immediates++] = {m.dst, *m.a < *m.b}; break;
            case Micro::EXT: x = *m.a << m.left; now[immediates++] = {m.dst, uint32_t(signed32(x) >> m.right)}; break;
            case Micro::EXTU: x = *m.a << m.left; now[immediates++] = {m.dst, x >> m.right}; break;
            case Micro::ADDSCALED: now[immediates++] = {m.dst, *m.a + uint32_t(signed32(*m.b) * m.scale)}; break;
            case Micro::MPY16: {
                int64_t sx = *m.a & 0xffff, sy = *m.b & 0xffff;
                if ((m.sign & 1) && sx & 0x8000) sx -= 0x10000;
                if ((m.sign & 2) && sy & 0x8000) sy -= 0x10000;
                later[results++] = {cycles + 2, m.dst, uint32_t(uint64_t(sx * sy))}; break;
            }
            case Micro::MPY32: later[results++] = {cycles + 4, m.dst, *m.a * *m.b}; break;
            case Micro::MPY32WIDE: {
                int64_t sx = *m.a, sy = *m.b;
                if (m.sign & 1) sx = signed32(*m.a);
                if (m.sign & 4) sx = int16_t(*m.a);
                if (m.sign & 2) sy = signed32(*m.b);
                uint64_t product = uint64_t(sx) * uint64_t(sy);
                later[results++] = {cycles + 4, m.dst, uint32_t(product)};
                later[results++] = {cycles + 4, m.high, uint32_t(product >> 32)}; break;
            }
            case Micro::LMBD:
                x = *m.a & 1; y = *m.b; v = 0;
                while (v < 32 && ((y >> (31 - v)) & 1) != x) v++;
                now[immediates++] = {m.dst, v}; break;
            case Micro::MOVLATE: later[results++] = {cycles + 4, m.dst, *m.a}; break;
            case Micro::ROTL: later[results++] = {cycles + 2, m.dst, std::rotl(*m.a, int(*m.b & 31))}; break;
            case Micro::DINT:
                now[immediates++] = {72, (regs[72] & ~3u) | ((regs[64] & 1u) << 1)};
                now[immediates++] = {64, regs[64] & ~1u}; break;
            case Micro::RINT:
                now[immediates++] = {72, (regs[72] & ~1u) | ((regs[72] >> 1) & 1)};
                now[immediates++] = {64, (regs[64] & ~1u) | ((regs[72] >> 1) & 1)}; break;
            case Micro::CSRW:
                now[immediates++] = {72, (regs[72] & ~1u) | (*m.a & 1)};
                now[immediates++] = {81, (regs[81] & ~1u) | ((*m.a >> 1) & 1)};
                now[immediates++] = {64, *m.a}; break;
            case Micro::IERW: now[immediates++] = {65, (*m.a & 0xfff2) | (regs[65] & 2) | 1}; break;
            case Micro::TSC: {
                uint64_t count = tsc_running && cycles >= tsc_start ? cycles - tsc_start : 0;
                recur.impure = true;
                now[immediates++] = {m.dst, uint32_t(count)};
                now[immediates++] = {uint8_t(TSCH), uint32_t(count >> 32)}; break;
            }
            case Micro::ABSSP: now[immediates++] = {m.dst, *m.a & 0x7f800000 ? *m.a & 0x7fffffff : 0}; break;
            case Micro::ADDSP: later[results++] = {cycles + 4, m.dst, single_bits(single(*m.a) + single(*m.b))}; break;
            case Micro::SUBSP: later[results++] = {cycles + 4, m.dst, single_bits(single(*m.a) - single(*m.b))}; break;
            case Micro::MPYSP: later[results++] = {cycles + 4, m.dst, single_bits(single(*m.a) * single(*m.b))}; break;
            case Micro::INTSP: later[results++] = {cycles + 4, m.dst, single_bits(float(signed32(*m.a)))}; break;
            case Micro::INTSPU: later[results++] = {cycles + 4, m.dst, single_bits(float(*m.a))}; break;
            case Micro::SPTRUNC: case Micro::SPINT: {
                double sx = single(*m.a);
                if (std::isnan(sx) || sx >= 2147483648.0) v = 0x7fffffff;
                else if (sx < -2147483648.0) v = 0x80000000;
                else v = uint32_t(int64_t(m.kind == Micro::SPINT ? std::nearbyint(sx) : std::trunc(sx)));
                later[results++] = {cycles + 4, m.dst, v}; break;
            }
            case Micro::CMPEQSP: now[immediates++] = {m.dst, single(*m.a) == single(*m.b)}; break;
            case Micro::CMPGTSP: now[immediates++] = {m.dst, single(*m.a) > single(*m.b)}; break;
            case Micro::CMPLTSP: now[immediates++] = {m.dst, single(*m.a) < single(*m.b)}; break;
            case Micro::LOAD: case Micro::STORE: {
                uint32_t base = *m.base;
                int64_t offset = m.index ? signed32(*m.index) : m.displacement;
                if (m.mode & C6_SCALED) offset *= m.size;
                if (m.mode & C6_MINUS) offset = -offset;
                uint32_t updated = base + uint32_t(offset);
                if (m.mode & (C6_PRE | C6_POST)) now[immediates++] = {uint32_t(m.base - regs.data()), updated};
                uint32_t addr = m.mode & C6_POST ? base : updated;
                if (m.kind == Micro::LOAD) {
                    if (m.aligned && (addr & (m.size - 1u))) addr = round_down(addr, m.size, "load");
                    uint64_t raw = cpu_load(addr, m.size, m.dst >= 32);
                    if (m.sign && m.size == 1 && raw & 0x80) raw |= 0xffffff00u;
                    if (m.sign && m.size == 2 && raw & 0x8000) raw |= 0xffff0000u;
                    later[results++] = {cycles + 5, m.dst, uint32_t(raw)};
                    if (m.size == 8) later[results++] = {cycles + 5, m.high, uint32_t(raw >> 32)};
                } else {
                    if (m.aligned && (addr & (m.size - 1u))) addr = round_down(addr, m.size, "store");
                    if (!writable_direct(addr, m.size) && !board.contains(addr, m.size) &&
                        !(board.reserved_low_writes && addr < Board::RESERVED_END) && !emifa(addr))
                        check(addr, m.size, C6_WRITE);
                    stores[stored++] = {addr, m.size == 8 ? *m.a | uint64_t(*m.b) << 32 : *m.a, m.size, op.ins.address};
                }
                break;
            }
            case Micro::BDEC: case Micro::BPOS:
                if (signed32(*m.b) >= 0) {
                    branch = {cycles + 6, *m.a, 0}; branched++;
                    if (m.kind == Micro::BDEC) now[immediates++] = {m.dst, *m.b - 1};
                }
                break;
            case Micro::BRANCH:
                branch = {cycles + 6, *m.a, m.restore}; branched++;
                if (m.sets_extra) extra = *m.b;
                if (m.link) { now[immediates++] = {m.dst, next}; extra = 5; }
                break;
            case Micro::NOP: extra = std::max(extra, m.extra); break;
            case Micro::ADDKPC:
                now[immediates++] = {m.dst, *m.a};
                if (m.sets_extra) extra = *m.b;
                break;
            }
        }
        if (branched > 1) throw std::runtime_error("multiple branches in one packet are not supported");
        if (extra > 9) throw std::runtime_error("unsupported NOP count");
        for (unsigned i = 0; i < stored; i++) {
            const auto &store = stores[i];
            if (store_direct(store.address, store.value, store.size)) continue;
            uint8_t data[8];
            for (uint32_t byte = 0; byte < store.size; byte++) data[byte] = uint8_t(store.value >> (byte * 8));
            write(store.address, data, store.size, true, store.pc);
        }
        for (unsigned i = 0; i < immediates; i++) regs[now[i].first] = now[i].second;
        for (unsigned i = 0; i < results; i++) {
            // Due within six cycles here, so only a full slot needs the general queue.
            auto &slot = due[later[i].due % Due::SLOTS];
            if (slot.count == Due::ROOM || !pending.empty()) { delay(later[i]); continue; }
            slot.writes[slot.count++] = {later[i].reg, later[i].value};
            pending_count++;
        }
        if (branched) branches.push_back(branch);
        idle = 1 + (protected_load && load_present ? std::max(extra, 4u) : extra);
        pc = next; packets++;
    }
    static constexpr size_t FAST_OPS = 16;
    void issue(const Op *const *ops, size_t count, uint32_t next, uint32_t protected_load) {
        bool fast = count <= FAST_OPS;
        for (size_t index = 0; fast && index < count; index++) fast = ops[index]->fast;
        if (fast) issue_fast(ops, count, next, protected_load);
        else issue_general(ops, count, next, protected_load);
    }
    void issue_general(const Op *const *ops, size_t count, uint32_t next, uint32_t protected_load) {
        auto &immediate = issue_immediate, &delayed = issue_delayed;
        auto &stores = issue_stores;
        auto &issued_branches = issue_branches;
        immediate.clear(); delayed.clear(); stores.clear(); issued_branches.clear();
        uint32_t extra = 0;
        bool software_exception = false, no_return = false;
        bool load_present = false;
        for (size_t index = 0; index < count; index++) {
            const Op &op = *ops[index];
            const auto &ins = op.ins;
            fault_address = ins.address;
            if (op.flags) {
                if (op.flags & Op::LOOP) continue;
                if (op.flags & Op::UNSUPPORTED) throw std::runtime_error("unsupported instruction at " + hex(ins.address));
                // PROT inserts the load's four NOPs during instruction decode. They remain
                // present when the load's predicate is false (SPRUFE8B 3.10.2.2).
                if (op.flags & Op::LOAD) load_present = true;
                // Every branch blocks interruption of its delay slots, even when not taken.
                if (op.flags & Op::BRANCH) interrupt_blocked_until = cycles + 6;
            }
            if (ins.predicate >= 0 && (((op.predicate ? *op.predicate : reg(ins.predicate)) != 0) == bool(ins.invert))) {
                if (ins.opcode == C6_BNOP) extra = value(ins.operands[1]);
                if (ins.opcode == C6_ADDKPC && ins.count == 3) extra = value(ins.operands[2]);
                continue;
            }
            // Shadows the general operand reader for the scalar sources resolved at install.
            auto value = [&](const c6_operand &operand) -> uint32_t {
                auto source = op.source[&operand - ins.operands];
                return source ? *source : this->value(operand);
            };
            const auto &a = ins.operands[0], &b = ins.operands[1], &c = ins.operands[2], &d = ins.operands[3];
            auto put = [&](const c6_operand &dst, uint64_t v) {
                if (dst.kind == C6_REGISTER && uint32_t(dst.reg) < 96) immediate.push_back({cycles, uint32_t(dst.reg), uint32_t(v)});
                else result(immediate, dst, v, cycles);
            };
            auto later = [&](const c6_operand &dst, uint64_t v, uint32_t slots) {
                if (dst.kind == C6_REGISTER && uint32_t(dst.reg) < 96) delayed.push_back({cycles + slots + 1, uint32_t(dst.reg), uint32_t(v)});
                else result(delayed, dst, v, cycles + slots + 1);
            };
            // A saturating instruction with `slots` delay slots clipped its result: SAT follows the result by a cycle.
            auto clipped = [&](uint32_t slots) {
                uint64_t due = cycles + slots + 2;
                sat_due = sat_due ? std::min(sat_due, due) : due;
                // ins.reserved holds the unit: L1, S1, M1, D1, L2, S2, M2, D2 from bit 0. SSR: L1, L2, S1, S2, M1, M2.
                static constexpr uint32_t ssr[8] = {0x01, 0x04, 0x10, 0, 0x02, 0x08, 0x20, 0};
                for (unsigned unit = 0; unit < 8; unit++) if (ins.reserved >> unit & 1) sat_units |= ssr[unit];
            };
            auto half = [](uint32_t word, bool high, bool is_signed) -> int64_t {
                uint32_t part = high ? word >> 16 : word & 0xffff;
                return is_signed ? int64_t(int16_t(part)) : int64_t(part);
            };
            uint32_t x = 0, y = 0, v = 0;
            switch (ins.opcode) {
            case C6_SPDP: {
                if (b.kind != C6_PAIR) throw std::runtime_error("SPDP needs a pair destination");
                uint64_t bits = double_bits(double(single(value(a))));
                delayed.push_back({cycles + 1, uint32_t(b.aux), uint32_t(bits)});
                delayed.push_back({cycles + 2, uint32_t(b.reg), uint32_t(bits >> 32)});
                break;
            }
            case C6_MPYSP2DP: case C6_MPYSPDP: case C6_MPYDP: case C6_ADDDP: case C6_SUBDP:
            case C6_INTDP: case C6_INTDPU: case C6_DPTRUNC: case C6_DPINT: case C6_DPSP:
            case C6_CMPEQDP: case C6_CMPGTDP: case C6_CMPLTDP: case C6_ABSDP: case C6_RCPDP: case C6_RSQRDP: {
                DoubleJob job{cycles, ins, {}, {}, {}, {}};
                bool waiting = false;
                bool once = ins.opcode == C6_DPTRUNC || ins.opcode == C6_DPINT || ins.opcode == C6_DPSP || ins.opcode == C6_ABSDP || ins.opcode == C6_RCPDP || ins.opcode == C6_RSQRDP;
                for (unsigned index = 0; index + 1 < ins.count; index++) {
                    const auto &src = ins.operands[index];
                    if (src.kind == C6_PAIR) {
                        job.low[index] = reg(src.aux);
                        if (once) job.high[index] = reg(src.reg);
                        else { job.due[index] = cycles + (ins.opcode == C6_MPYDP && index == 0 ? 2 : 1); waiting = true; }
                    } else job.scalar[index] = value(src);
                }
                if (waiting) late.push_back(job); else finish_double(job, delayed);
                break;
            }
            case C6_DINT: case C6_RINT: {
                c6_operand csr{C6_REGISTER, 64, 0, -1, 0}, tsr{C6_REGISTER, 72, 0, -1, 0};
                if (ins.opcode == C6_DINT) {
                    put(tsr, (regs[72] & ~3u) | ((regs[64] & 1u) << 1));
                    put(csr, regs[64] & ~1u);
                } else {
                    put(tsr, (regs[72] & ~1u) | ((regs[72] >> 1) & 1));
                    put(csr, (regs[64] & ~1u) | ((regs[72] >> 1) & 1));
                }
                break;
            }
            case C6_SPMASK: case C6_SPKERNEL: case C6_SPMASKR: break; // SPMASKR: the run loop starts the reload.
            case C6_SPKERNELR: throw std::runtime_error("SPKERNELR outside a loop body is not implemented");
            case C6_NOP:
                v = ins.count ? value(a) : 1;
                if (!v || v > 9) throw std::runtime_error("NOP count must be 1..9");
                extra = std::max(extra, v - 1); break;
            case C6_MVK: case C6_MV: put(b, value(a)); break;
            // SPRUFE8B DMV: src1 to the odd register of dst, src2 to the even one; no delay slots.
            case C6_DMV: put(c, (uint64_t(value(a)) << 32) | value(b)); break;
            case C6_SWE: software_exception = true; break;
            case C6_SWENR: software_exception = true; no_return = true; break;
            case C6_IDLE: idling = true; break;
            // SPRUFE8B MAXU4 / MINU4: per unsigned byte, the larger / smaller of src1 and src2; no delay slots.
            case C6_MAXU4: case C6_MINU4: {
                uint32_t x = value(a), y = value(b), r = 0;
                for (unsigned shift = 0; shift < 32; shift += 8) {
                    uint32_t p = x >> shift & 0xffu, q = y >> shift & 0xffu;
                    r |= (ins.opcode == C6_MAXU4 ? std::max(p, q) : std::min(p, q)) << shift;
                }
                put(c, r); break;
            }
            case C6_MVKH: put(b, (value(b) & 0xffffu) | (value(a) & 0xffff0000u)); break;
            case C6_MVC:
                v = value(a);
                if (b.reg == 64) v = (v & ~0x100u) | (regs[64] & 0x100u); // EN is read-only.
                if (b.reg == 66) throw std::runtime_error("IFR is read-only; use ISR/ICR");
                if (b.reg == 83) throw std::runtime_error("EFR is read-only; use ECR");
                if (b.reg == 84) { regs[83] &= ~v; break; }   // ECR clears EFR bits (SPRUFE8B 2.9.2)
                if (b.reg == 67 || b.reg == 68) {
                    irq_writes.push_back({cycles + 2, b.reg == 67 ? v & 0xfff0 : 0, b.reg == 68 ? v & 0xfff0 : 0});
                    break;
                }
                if (b.reg == 65) v = (v & 0xfff2) | (regs[65] & 2) | 1;
                if (b.reg == 71) v &= ~1023u;
                if (b.reg == 87) v &= 0x070000ff;
                if (b.reg == int32_t(AMR) && v) throw std::runtime_error("circular addressing is not implemented");
                if (b.reg == int32_t(TSCL)) {
                    if (!tsc_running) { tsc_running = true; tsc_start = cycles + 1; }
                    break;
                }
                if (b.reg == int32_t(TSCH)) throw std::runtime_error("TSCH is read-only");
                if ((b.reg == 78 || b.reg == 79) && ((v >> 9 & 3) || (v >> 25 & 3)))
                    throw std::runtime_error("non-default floating-point rounding mode is not implemented");
                if (a.kind == C6_REGISTER && a.reg == int32_t(TSCL)) regs[TSCH] = uint32_t((tsc_running && cycles >= tsc_start ? cycles - tsc_start : 0) >> 32);
                if (b.reg == 64 || b.reg == 72) {
                    c6_operand other{C6_REGISTER, b.reg == 64 ? 72 : 64, 0, -1, 0};
                    put(other, (reg(other.reg) & ~1u) | (v & 1));
                }
                if (b.reg == 64 || b.reg == 81) {
                    c6_operand other{C6_REGISTER, b.reg == 64 ? 81 : 64, 0, -1, 0};
                    put(other, b.reg == 64 ? (regs[81] & ~1u) | ((v >> 1) & 1)
                                         : (regs[64] & ~2u) | ((v & 1) << 1));
                }
                put(b, v); break;
            case C6_MVD: later(b, value(a), 3); break;
            case C6_ZERO: put(a, 0); break;
            case C6_ADD:
                if (c.kind == C6_PAIR) put(c, uint64_t(long_value(a) + long_value(b)) & 0xffffffffffull);
                else put(c, value(a) + value(b));
                break;
            case C6_ADDK: put(b, value(b) + value(a)); break;
            case C6_SUB:
                if (c.kind == C6_PAIR) put(c, uint64_t(long_value(a) - long_value(b)) & 0xffffffffffull);
                else put(c, value(a) - value(b));
                break;
            case C6_SUBU: put(c, (uint64_t(value(a)) - value(b)) & 0xffffffffffull); break;
            case C6_ADDU: put(c, (uint64_t(value(a)) + (b.kind == C6_PAIR ? pair(b) & 0xffffffffffull : value(b))) & 0xffffffffffull); break;
            case C6_SAT: { int64_t wide = long_value(a); put(b, saturated(wide)); if (wide != signed32(saturated(wide))) clipped(0); break; }
            // SPRUFE8B SADD / SSUB: src1 + src2 or src1 - src2, saturated to the destination's 32 or 40 bits.
            case C6_SADD: case C6_SSUB: {
                bool wide = c.kind == C6_PAIR;
                int64_t left = a.kind == C6_PAIR ? long_value(a) : signed32(value(a)), right = b.kind == C6_PAIR ? long_value(b) : signed32(value(b));
                int64_t sum = ins.opcode == C6_SADD ? left + right : left - right;
                int64_t low = wide ? -(int64_t(1) << 39) : -(int64_t(1) << 31), high = -low - 1;
                int64_t kept = std::clamp(sum, low, high);
                put(c, wide ? uint64_t(kept) & 0xffffffffffull : uint64_t(uint32_t(kept)));
                if (kept != sum) clipped(0);
                break;
            }
            // SPRUFE8B 16 x 16 multiplies of one half of each source: which half, and signed or not, by name
            // (H or L, then U or S; MPYH and MPYHL signed, MPYHU and MPYHLU unsigned). One delay slot.
            case C6_MPYH: case C6_MPYHU: case C6_MPYHUS: case C6_MPYHSU: case C6_MPYHL: case C6_MPYHLU: case C6_MPYHULS:
            case C6_MPYHSLU: case C6_MPYLUHS: case C6_MPYLSHU: {
                bool h1 = ins.opcode != C6_MPYLUHS && ins.opcode != C6_MPYLSHU;
                bool h2 = ins.opcode == C6_MPYH || ins.opcode == C6_MPYHU || ins.opcode == C6_MPYHUS || ins.opcode == C6_MPYHSU || !h1;
                bool s1 = ins.opcode == C6_MPYH || ins.opcode == C6_MPYHSU || ins.opcode == C6_MPYHL || ins.opcode == C6_MPYHSLU || ins.opcode == C6_MPYLSHU;
                bool s2 = ins.opcode == C6_MPYH || ins.opcode == C6_MPYHUS || ins.opcode == C6_MPYHL || ins.opcode == C6_MPYHULS || ins.opcode == C6_MPYLUHS;
                later(c, uint64_t(half(value(a), h1, s1) * half(value(b), h2, s2)), 1); break;
            }
            // SPRUFE8B SMPY, SMPYH, SMPYHL, SMPYLH: the signed product of two halves, doubled; 8000 0000h
            // (both -32768) becomes 7FFF FFFFh and sets SAT. One delay slot. SMPY2 does the low halves into
            // the even register and the high halves into the odd one, with three.
            case C6_SMPY: case C6_SMPYH: case C6_SMPYHL: case C6_SMPYLH: case C6_SMPY2: {
                auto doubled = [&](bool h1, bool h2, uint32_t slots) -> uint32_t {
                    int64_t product = half(value(a), h1, true) * half(value(b), h2, true) * 2;
                    if (product != 0x80000000ll) return uint32_t(product);
                    clipped(slots); return 0x7fffffffu;
                };
                if (ins.opcode == C6_SMPY2) {
                    if (c.kind != C6_PAIR) throw std::runtime_error("SMPY2 needs a pair destination");
                    uint32_t low = doubled(false, false, 3), high = doubled(true, true, 3);
                    later(c, uint64_t(high) << 32 | low, 3);
                } else later(c, doubled(ins.opcode == C6_SMPYH || ins.opcode == C6_SMPYHL, ins.opcode == C6_SMPYH || ins.opcode == C6_SMPYLH, 1), 1);
                break;
            }
            // SPRUFE8B packed 16-bit and 8-bit arithmetic: each half or byte on its own, no carry between
            // them, CSR.SAT untouched. ADD2/SUB2/ADD4/SUB4 wrap; SADD2/SSUB2 saturate signed halves, SADDU4
            // unsigned bytes, SADDUS2 an unsigned half of src1 plus a signed half of src2 to unsigned
            // (SADDSU2: the sources the other way round); ABS2 gives 7FFFh for 8000h; MAX2/MIN2 compare signed.
            case C6_ADD2: case C6_SUB2: case C6_SADD2: case C6_SSUB2: case C6_SADDUS2: case C6_SADDSU2: case C6_MAX2: case C6_MIN2: case C6_AVG2: {
                uint32_t r = 0; x = value(a); y = value(b);
                for (int high = 0; high < 2; high++) {
                    int64_t p = half(x, high, true), q = half(y, high, true), part;
                    switch (ins.opcode) {
                    case C6_ADD2: part = p + q; break;
                    case C6_SUB2: part = p - q; break;
                    case C6_SADD2: part = std::clamp<int64_t>(p + q, -32768, 32767); break;
                    case C6_SSUB2: part = std::clamp<int64_t>(p - q, -32768, 32767); break;
                    case C6_SADDUS2: part = std::clamp<int64_t>(half(x, high, false) + q, 0, 65535); break;
                    case C6_SADDSU2: part = std::clamp<int64_t>(p + half(y, high, false), 0, 65535); break;
                    case C6_MAX2: part = std::max(p, q); break;
                    case C6_MIN2: part = std::min(p, q); break;
                    default: part = (p + q + 1) >> 1; break; // AVG2
                    }
                    r |= (uint32_t(part) & 0xffffu) << (high * 16);
                }
                if (ins.opcode == C6_AVG2) later(c, r, 1); else put(c, r);
                break;
            }
            case C6_ADD4: case C6_SUB4: case C6_SADDU4: case C6_AVGU4: {
                uint32_t r = 0; x = value(a); y = value(b);
                for (unsigned shift = 0; shift < 32; shift += 8) {
                    uint32_t p = x >> shift & 0xffu, q = y >> shift & 0xffu;
                    uint32_t part = ins.opcode == C6_ADD4 ? p + q : ins.opcode == C6_SUB4 ? p - q : ins.opcode == C6_SADDU4 ? std::min(p + q, 255u) : (p + q + 1) >> 1;
                    r |= (part & 0xffu) << shift;
                }
                if (ins.opcode == C6_AVGU4) later(c, r, 1); else put(c, r);
                break;
            }
            case C6_ABS2: {
                x = value(a);
                int64_t low = std::min<int64_t>(std::abs(half(x, false, true)), 32767), high = std::min<int64_t>(std::abs(half(x, true, true)), 32767);
                put(b, uint32_t(high) << 16 | uint32_t(low)); break;
            }
            // SPRUFE8B BITR: bit 31 to bit 0 and so on, one delay slot. SWAP4: the two bytes of each half
            // change places. SHLMB / SHRMB: src2 moved up / down a byte, the freed byte from src1's top / bottom.
            case C6_BITR: {
                x = value(a);
                for (unsigned bit = 0; bit < 32; bit++) v |= (x >> bit & 1u) << (31 - bit);
                later(b, v, 1); break;
            }
            case C6_SWAP4: x = value(a); put(b, (x & 0xff00ff00u) >> 8 | (x & 0x00ff00ffu) << 8); break;
            case C6_SHLMB: put(c, value(b) << 8 | value(a) >> 24); break;
            case C6_SHRMB: put(c, value(b) >> 8 | value(a) << 24); break;
            // SPRUFE8B MPYU4 / MPYSU4: the four byte products as 16-bit values, bytes 0 and 1 in the even
            // register and 2 and 3 in the odd one; three delay slots. MPYSU4 takes src1's bytes as signed;
            // MPYUS4 is the same instruction with the sources exchanged.
            case C6_MPYU4: case C6_MPYSU4: case C6_MPYUS4: {
                if (c.kind != C6_PAIR) throw std::runtime_error("MPYU4/MPYSU4 needs a pair destination");
                x = value(ins.opcode == C6_MPYUS4 ? b : a); y = value(ins.opcode == C6_MPYUS4 ? a : b);
                uint64_t wide = 0;
                for (unsigned index = 0; index < 4; index++) {
                    int32_t p = ins.opcode == C6_MPYU4 ? int32_t(x >> (index * 8) & 0xff) : int32_t(int8_t(x >> (index * 8)));
                    wide |= uint64_t(uint32_t(p * int32_t(y >> (index * 8) & 0xff)) & 0xffffu) << (index * 16);
                }
                later(c, wide, 3); break;
            }
            // The rest of the packed set (SPRUFE8B; no delay slots unless said). Comparisons give one bit per
            // half or byte, bit 0 for the lowest; XPND2/XPND4 turn such bits back into masks and BITC4 counts
            // the ones of each byte (one delay slot each).
            case C6_CMPEQ2: case C6_CMPGT2:
                x = value(a); y = value(b);
                for (int high = 0; high < 2; high++)
                    v |= uint32_t(ins.opcode == C6_CMPEQ2 ? half(x, high, false) == half(y, high, false) : half(x, high, true) > half(y, high, true)) << high;
                put(c, v); break;
            case C6_CMPEQ4: case C6_CMPGTU4: case C6_SUBABS4:
                x = value(a); y = value(b);
                for (unsigned index = 0; index < 4; index++) {
                    uint32_t p = x >> (index * 8) & 0xffu, q = y >> (index * 8) & 0xffu;
                    if (ins.opcode == C6_SUBABS4) v |= (p > q ? p - q : q - p) << (index * 8);
                    else v |= uint32_t(ins.opcode == C6_CMPEQ4 ? p == q : p > q) << index;
                }
                put(c, v); break;
            case C6_XPND2: x = value(a); later(b, (x & 2 ? 0xffff0000u : 0) | (x & 1 ? 0xffffu : 0), 1); break;
            case C6_XPND4:
                x = value(a);
                for (unsigned index = 0; index < 4; index++) if (x >> index & 1) v |= 0xffu << (index * 8);
                later(b, v, 1); break;
            case C6_BITC4:
                x = value(a);
                for (unsigned index = 0; index < 4; index++) v |= uint32_t(std::popcount(x >> (index * 8) & 0xffu)) << (index * 8);
                later(b, v, 1); break;
            // PACKH2: the high halves of src1 and src2. PACKH4: the high byte of each half, src1's above src2's.
            // UNPKHU4 / UNPKLU4: the two bytes of the high / low half, each zero-extended to a half.
            case C6_PACKH2: put(c, (value(a) & 0xffff0000u) | value(b) >> 16); break;
            case C6_PACKH4: x = value(a); y = value(b); put(c, (x & 0xff000000u) | (x << 8 & 0x00ff0000u) | (y >> 16 & 0xff00u) | (y >> 8 & 0xffu)); break;
            case C6_UNPKHU4: x = value(a); put(b, (x >> 8 & 0x00ff0000u) | (x >> 16 & 0xffu)); break;
            case C6_UNPKLU4: x = value(a); put(b, (x << 8 & 0x00ff0000u) | (x & 0xffu)); break;
            // SPACK2: src1 and src2 as signed 32-bit values, each saturated to a signed half. SPACKU4: the four
            // signed halves, each saturated to an unsigned byte. Neither is said to touch SAT.
            case C6_SPACK2:
                put(c, uint32_t(std::clamp<int64_t>(signed32(value(a)), -32768, 32767) & 0xffff) << 16 |
                       uint32_t(std::clamp<int64_t>(signed32(value(b)), -32768, 32767) & 0xffff)); break;
            case C6_SPACKU4:
                x = value(a); y = value(b);
                put(c, uint32_t(std::clamp<int64_t>(half(x, true, true), 0, 255)) << 24 | uint32_t(std::clamp<int64_t>(half(x, false, true), 0, 255)) << 16 |
                       uint32_t(std::clamp<int64_t>(half(y, true, true), 0, 255)) << 8 | uint32_t(std::clamp<int64_t>(half(y, false, true), 0, 255))); break;
            case C6_SHRU2: x = value(a); y = value(b) & 31; put(c, y >= 16 ? 0 : (x >> 16 >> y) << 16 | (x & 0xffffu) >> y); break;
            // ADDSUB2, SADDSUB, SADDSUB2: the sum in the odd register and the difference in the even one, per
            // half without saturation, of the whole words with it (SAT), per half with it (no SAT).
            case C6_ADDSUB2: case C6_SADDSUB2: case C6_SADDSUB: {
                if (c.kind != C6_PAIR) throw std::runtime_error("ADDSUB2/SADDSUB/SADDSUB2 needs a pair destination");
                x = value(a); y = value(b);
                uint32_t sum = 0, difference = 0;
                if (ins.opcode == C6_SADDSUB) {
                    int64_t wide_sum = signed32(x) + signed32(y), wide_difference = signed32(x) - signed32(y);
                    sum = saturated(wide_sum); difference = saturated(wide_difference);
                    if (signed32(sum) != wide_sum || signed32(difference) != wide_difference) clipped(0);
                } else for (int high = 0; high < 2; high++) {
                    int64_t p = half(x, high, true), q = half(y, high, true), plus = p + q, minus = p - q;
                    if (ins.opcode == C6_SADDSUB2) { plus = std::clamp<int64_t>(plus, -32768, 32767); minus = std::clamp<int64_t>(minus, -32768, 32767); }
                    sum |= (uint32_t(plus) & 0xffffu) << (high * 16); difference |= (uint32_t(minus) & 0xffffu) << (high * 16);
                }
                put(c, uint64_t(sum) << 32 | difference); break;
            }
            // Dot products with three delay slots. DOTPN2: high x high minus low x low, signed. DOTPRSU2 and
            // DOTPNRSU2: src1's halves signed, src2's unsigned, summed or differenced, plus 8000h, shifted
            // right 16. DOTPU4 / DOTPSU4: the four byte products summed, src1's bytes unsigned / signed.
            case C6_DOTPN2: later(c, uint64_t(half(value(a), true, true) * half(value(b), true, true) - half(value(a), false, true) * half(value(b), false, true)), 3); break;
            case C6_DOTPRSU2: case C6_DOTPNRSU2: {
                int64_t high = half(value(a), true, true) * half(value(b), true, false), low = half(value(a), false, true) * half(value(b), false, false);
                later(c, uint64_t(((ins.opcode == C6_DOTPRSU2 ? high + low : high - low) + 0x8000) >> 16), 3); break;
            }
            case C6_DOTPU4: case C6_DOTPSU4: {
                x = value(a); y = value(b);
                int64_t sum = 0;
                for (unsigned index = 0; index < 4; index++)
                    sum += (ins.opcode == C6_DOTPU4 ? int64_t(x >> (index * 8) & 0xff) : int64_t(int8_t(x >> (index * 8)))) * int64_t(y >> (index * 8) & 0xff);
                later(c, uint64_t(sum), 3); break;
            }
            // A signed half of src1 times the signed 32 bits of src2, plus 4000h, shifted right 15, low 32 bits;
            // three delay slots. MPY2IR does both halves (high to the odd register) and saturates 8000h x
            // 8000 0000h to 7FFF FFFFh with SAT.
            case C6_MPYHIR: case C6_MPYLIR: later(c, uint64_t((half(value(a), ins.opcode == C6_MPYHIR, true) * signed32(value(b)) + 0x4000) >> 15), 3); break;
            case C6_MPY2IR: {
                if (c.kind != C6_PAIR) throw std::runtime_error("MPY2IR needs a pair destination");
                uint32_t parts[2];
                for (int high = 0; high < 2; high++) {
                    int64_t factor = half(value(a), high, true);
                    if (factor == -32768 && value(b) == 0x80000000u) { parts[high] = 0x7fffffffu; clipped(3); }
                    else parts[high] = uint32_t((factor * signed32(value(b)) + 0x4000) >> 15);
                }
                later(c, uint64_t(parts[1]) << 32 | parts[0], 3); break;
            }
            // SMPY32: the high 32 bits of the doubled signed product, saturated (only 8000 0000h squared).
            case C6_SMPY32:
                if (value(a) == 0x80000000u && value(b) == 0x80000000u) { later(c, 0x7fffffffu, 3); clipped(3); }
                else later(c, uint64_t((signed32(value(a)) * signed32(value(b)) * 2) >> 32), 3);
                break;
            // RPACK2: each source doubled with saturation; the two high halves, src1's above. Sets SAT.
            case C6_RPACK2: {
                int64_t first = signed32(value(a)) * 2, second = signed32(value(b)) * 2;
                uint32_t kept_first = saturated(first), kept_second = saturated(second);
                if (signed32(kept_first) != first || signed32(kept_second) != second) clipped(0);
                put(c, (kept_first & 0xffff0000u) | kept_second >> 16); break;
            }
            // SSHVL / SSHVR: src2 shifted left / right by the signed count in src1, the other way for a negative
            // count, counts beyond 31 taken as 31; left shifts saturate. One delay slot.
            case C6_SSHVL: case C6_SSHVR: {
                int64_t wide = signed32(value(a)), count = std::clamp<int64_t>(signed32(value(b)), -31, 31);
                if (ins.opcode == C6_SSHVR) count = -count;
                if (count >= 0) { int64_t shifted = wide * (int64_t(1) << count); v = saturated(shifted); if (signed32(v) != shifted) clipped(1); }
                else v = uint32_t(wide >> -count);
                later(c, v, 1); break;
            }
            // CMPY: (a_hi + j a_lo)(b_hi + j b_lo) on signed halves: the real part, hi x hi - lo x lo, to the odd
            // register and the imaginary part, lo x hi + hi x lo, saturated, to the even one. CMPYR packs both
            // into one register as msb16(sat(part + 8000h)), CMPYR1 as msb16(sat((part + 4000h) << 1)). Three
            // delay slots; SAT when anything clips.
            case C6_CMPY: case C6_CMPYR: case C6_CMPYR1: {
                int64_t ah = half(value(a), true, true), al = half(value(a), false, true), bh = half(value(b), true, true), bl = half(value(b), false, true);
                bool clip = false;
                auto sat32 = [&](int64_t wide) { uint32_t kept = saturated(wide); clip |= signed32(kept) != wide; return int64_t(signed32(kept)); };
                int64_t imaginary = sat32(al * bh + ah * bl), real = sat32(ah * bh - al * bl);
                if (ins.opcode == C6_CMPY) {
                    if (c.kind != C6_PAIR) throw std::runtime_error("CMPY needs a pair destination");
                    later(c, uint64_t(uint32_t(real)) << 32 | uint32_t(imaginary), 3);
                } else {
                    auto rounded = [&](int64_t part) { return uint32_t(ins.opcode == C6_CMPYR ? sat32(part + 0x8000) : sat32((part + 0x4000) * 2)) >> 16; };
                    uint32_t low = rounded(imaginary), high = rounded(real);
                    later(c, high << 16 | low, 3);
                }
                if (clip) clipped(3);
                break;
            }
            // DDOTP4: src1's two signed halves dotted with the signed bytes of src2's low half (even register)
            // and of its high half (odd one). DDOTPH2 / DDOTPL2: a 64-bit src1 as three overlapping pairs of
            // halves dotted with src2's two; H gives the top pair (odd) and the middle pair (even), L the middle
            // pair (odd) and the bottom pair (even), each saturated. The R forms pack msb16(sat(dot + 8000h)) of
            // the same two into one register. Three delay slots; SAT when anything clips.
            case C6_DDOTP4: {
                if (c.kind != C6_PAIR) throw std::runtime_error("DDOTP4 needs a pair destination");
                int64_t high = half(value(a), true, true), low = half(value(a), false, true); y = value(b);
                later(c, uint64_t(uint32_t(high * int8_t(y >> 24) + low * int8_t(y >> 16))) << 32 | uint32_t(high * int8_t(y >> 8) + low * int8_t(y)), 3); break;
            }
            case C6_DDOTPH2: case C6_DDOTPL2: case C6_DDOTPH2R: case C6_DDOTPL2R: {
                if (a.kind != C6_PAIR) throw std::runtime_error("DDOTPH2/DDOTPL2 needs a pair source");
                uint32_t odd = reg(a.reg), even = reg(a.aux); y = value(b);
                int64_t h2 = half(y, true, true), l2 = half(y, false, true);
                bool clip = false;
                auto sat32 = [&](int64_t wide) { uint32_t kept = saturated(wide); clip |= signed32(kept) != wide; return kept; };
                int64_t top = half(odd, true, true) * h2 + half(odd, false, true) * l2, middle = half(odd, false, true) * h2 + half(even, true, true) * l2,
                        bottom = half(even, true, true) * h2 + half(even, false, true) * l2;
                bool upper = ins.opcode == C6_DDOTPH2 || ins.opcode == C6_DDOTPH2R;
                int64_t first = upper ? top : middle, second = upper ? middle : bottom;   // odd register or high half, then even or low
                if (ins.opcode == C6_DDOTPH2 || ins.opcode == C6_DDOTPL2) {
                    if (c.kind != C6_PAIR) throw std::runtime_error("DDOTPH2/DDOTPL2 needs a pair destination");
                    later(c, uint64_t(sat32(first)) << 32 | sat32(second), 3);
                } else later(c, (sat32(first + 0x8000) & 0xffff0000u) | sat32(second + 0x8000) >> 16, 3);
                if (clip) clipped(3);
                break;
            }
            // DEAL: the odd bits of src2 to the high half and the even bits to the low half. SHFL: the reverse.
            // One delay slot. SHFL3: bit i of lsb16(src2), lsb16(src1) and msb16(src1) to bits 3i, 3i+1 and 3i+2
            // of a 48-bit result; none.
            case C6_DEAL: case C6_SHFL:
                x = value(a);
                for (unsigned bit = 0; bit < 16; bit++) {
                    if (ins.opcode == C6_DEAL) v |= (x >> (2 * bit) & 1u) << bit | (x >> (2 * bit + 1) & 1u) << (16 + bit);
                    else v |= (x >> bit & 1u) << (2 * bit) | (x >> (16 + bit) & 1u) << (2 * bit + 1);
                }
                later(b, v, 1); break;
            case C6_SHFL3: {
                if (c.kind != C6_PAIR) throw std::runtime_error("SHFL3 needs a pair destination");
                x = value(a); y = value(b);
                uint64_t wide = 0;
                for (unsigned bit = 0; bit < 16; bit++)
                    wide |= uint64_t(y >> bit & 1u) << (3 * bit) | uint64_t(x >> bit & 1u) << (3 * bit + 1) | uint64_t(x >> (16 + bit) & 1u) << (3 * bit + 2);
                put(c, wide); break;
            }
            // Galois field multiplies, three delay slots. GMPY: src1 by the low nine bits of src2, reduced by
            // GPLYA (.M1) or GPLYB (.M2), as the manual's C. XORMPY: the same with a zero polynomial. GMPY4: per
            // byte, in the field GFPGFR names (size in bits 26-24 plus one, polynomial in bits 7-0); the
            // manual's examples are all for its reset value, 8 bits and 1Dh, and other sizes are this reading.
            case C6_GMPY: case C6_XORMPY: {
                uint32_t polynomial = ins.opcode == C6_XORMPY ? 0 : regs[ins.reserved & 0x40 ? 92 : 91];
                x = value(a); y = value(b);
                for (uint32_t mask = 0x100; mask > 1; mask >>= 1) {
                    if (y & mask) v ^= x;
                    v = v & 0x80000000u ? polynomial ^ (v << 1) : v << 1;
                }
                if (y & 1) v ^= x;
                later(c, v, 3); break;
            }
            case C6_GMPY4: {
                unsigned size = (regs[87] >> 24 & 7) + 1;
                uint32_t polynomial = (regs[87] & 0xffu) | 1u << size;
                x = value(a); y = value(b);
                for (unsigned index = 0; index < 4; index++) {
                    uint32_t p = x >> (index * 8) & 0xffu, q = y >> (index * 8) & 0xffu, product = 0;
                    for (unsigned bit = 0; bit < 8; bit++) if (q >> bit & 1) product ^= p << bit;
                    for (int bit = 14; bit >= int(size); bit--) if (product >> bit & 1) product ^= polynomial << (bit - size);
                    v |= (product & 0xffu) << (index * 8);
                }
                later(c, v, 3); break;
            }
            // MPYI / MPYID: the 32 x 32 product, low 32 bits after eight delay slots; MPYID's high word a cycle later.
            case C6_MPYI: later(c, uint64_t(uint32_t(value(a)) * uint32_t(value(b))), 8); break;
            case C6_MPYID: {
                if (c.kind != C6_PAIR) throw std::runtime_error("MPYID needs a pair destination");
                uint64_t wide = uint64_t(signed32(value(a)) * signed32(value(b)));
                delayed.push_back({cycles + 9, uint32_t(c.aux), uint32_t(wide)});
                delayed.push_back({cycles + 10, uint32_t(c.reg), uint32_t(wide >> 32)});
                break;
            }
            // SPRUFE8B DPACKX2: dst_e = lsb16(src1):msb16(src2), dst_o = lsb16(src2):msb16(src1); no delay slots.
            case C6_DPACKX2:
                if (c.kind != C6_PAIR) throw std::runtime_error("DPACKX2 needs a pair destination");
                x = value(a); y = value(b);
                put(c, uint64_t(y << 16 | x >> 16) << 32 | (x << 16 | y >> 16)); break;
            case C6_ADDSUB:
                if (c.kind != C6_PAIR) throw std::runtime_error("ADDSUB needs a pair destination");
                put(c, (uint64_t(value(a) + value(b)) << 32) | (value(a) - value(b))); break;
            // SPRUFE8B DPACK2: dst_e = lsb16(src1):lsb16(src2), dst_o = msb16(src1):msb16(src2); no delay slots.
            case C6_DPACK2:
                if (c.kind != C6_PAIR) throw std::runtime_error("DPACK2 needs a pair destination");
                put(c, (uint64_t((value(a) & 0xffff0000) | (value(b) >> 16)) << 32) | (value(a) << 16) | (value(b) & 0xffff)); break;
            case C6_AND: put(c, value(a) & value(b)); break;
            case C6_OR: put(c, value(a) | value(b)); break;
            case C6_XOR: put(c, value(a) ^ value(b)); break;
            case C6_ANDN: put(c, value(a) & ~value(b)); break;
            case C6_NOT: put(b, ~value(a)); break;
            case C6_NEG: put(b, 0u - value(a)); break;
            case C6_SHL: case C6_SHR: case C6_SHRU:
                if (a.kind == C6_PAIR) {
                    y = std::min(value(b) & 63, 40u);
                    uint64_t bits = pair(a) & 0xffffffffffull;
                    if (ins.opcode == C6_SHL) bits <<= y;
                    else if (ins.opcode == C6_SHRU) bits >>= y;
                    else bits = uint64_t(long_value(a) >> y);
                    put(c, bits & 0xffffffffffull); break;
                }
                x = value(a); y = value(b) & 63;
                // SHL of a 32-bit source into a pair keeps 40 bits of the result (the xuint to ulong form).
                if (ins.opcode == C6_SHL && c.kind == C6_PAIR) { put(c, (uint64_t(x) << std::min(y, 40u)) & 0xffffffffffull); break; }
                if (ins.opcode == C6_SHL) v = y >= 32 ? 0 : x << y;
                else if (ins.opcode == C6_SHRU) v = y >= 32 ? 0 : x >> y;
                else v = uint32_t(signed32(x) >> std::min(y, 31u));
                put(c, v); break;
            case C6_CMPEQ: put(c, a.kind == C6_PAIR || b.kind == C6_PAIR ? long_value(a) == long_value(b) : value(a) == value(b)); break;
            case C6_CMPGT: put(c, long_value(a) > long_value(b)); break;
            case C6_CMPLT: put(c, long_value(a) < long_value(b)); break;
            case C6_CMPGTU: put(c, value(a) > value(b)); break;
            case C6_CMPLTU: put(c, value(a) < value(b)); break;
            case C6_SET: case C6_CLR: {
                const c6_operand *dst = &d;
                if (ins.count == 3) { v = value(b); x = (v >> 5) & 31; y = v & 31; dst = &c; } // register form: bits 9-5 and 4-0
                else { x = value(b); y = value(c); }
                if (x > y || y > 31) throw std::runtime_error("unsupported bitfield bounds");
                uint32_t mask = uint32_t(((uint64_t(1) << (y - x + 1)) - 1) << x);
                put(*dst, ins.opcode == C6_SET ? value(a) | mask : value(a) & ~mask); break;
            }
            case C6_EXT: case C6_EXTU: {
                uint32_t left, right;
                const c6_operand *dst;
                if (ins.count == 3) { x = value(b); left = (x >> 5) & 31; right = x & 31; dst = &c; }
                else { left = value(b); right = value(c); dst = &d; }
                if (left > 31 || right > 31) throw std::runtime_error("unsupported extract bounds");
                x = value(a) << left;
                put(*dst, ins.opcode == C6_EXT ? uint32_t(signed32(x) >> right) : x >> right); break;
            }
            case C6_LDW: case C6_LDH: case C6_LDHU: case C6_LDB: case C6_LDBU:
            case C6_LDDW: case C6_LDNW: case C6_LDNDW: {
                uint32_t size = ins.opcode == C6_LDB || ins.opcode == C6_LDBU ? 1 :
                    ins.opcode == C6_LDH || ins.opcode == C6_LDHU ? 2 :
                    ins.opcode == C6_LDDW || ins.opcode == C6_LDNDW ? 8 : 4;
                uint32_t addr = address(a, size, immediate);
                if (ins.opcode != C6_LDNW && ins.opcode != C6_LDNDW && addr % size)
                    addr = round_down(addr, size, "load");
                uint64_t raw = cpu_load(addr, size, b.reg >= 32);
                if (ins.opcode == C6_LDB && raw & 0x80) raw |= 0xffffff00u;
                if (ins.opcode == C6_LDH && raw & 0x8000) raw |= 0xffff0000u;
                later(b, raw, 4); load_present = true; break;
            }
            case C6_STW: case C6_STH: case C6_STB: case C6_STDW: case C6_STNW: case C6_STNDW: {
                uint32_t size = ins.opcode == C6_STB ? 1 : ins.opcode == C6_STH ? 2 :
                    ins.opcode == C6_STDW || ins.opcode == C6_STNDW ? 8 : 4;
                uint32_t addr = address(b, size, immediate);
                if (ins.opcode != C6_STNW && ins.opcode != C6_STNDW && addr % size)
                    addr = round_down(addr, size, "store");
                if (!writable_direct(addr, size) && !board.contains(addr, size) &&
                    !(board.reserved_low_writes && addr < Board::RESERVED_END) && !emifa(addr))
                    check(addr, size, C6_WRITE);
                stores.push_back({addr, pair(a), size, ins.address}); break;
            }
            case C6_BDEC: case C6_BPOS:
                if (signed32(value(b)) >= 0) {
                    issued_branches.push_back({cycles + 6, value(a)});
                    if (ins.opcode == C6_BDEC) put(b, value(b) - 1);
                }
                break;
            case C6_B: case C6_BNOP: case C6_CALLP:
                issued_branches.push_back({cycles + 6, value(a),
                    ins.opcode == C6_B && a.kind == C6_REGISTER && (a.reg == 69 || a.reg == 70) ? uint32_t(a.reg - 68) : 0});
                if (ins.opcode == C6_BNOP) extra = value(b);
                if (ins.opcode == C6_CALLP) { put(b, next); extra = 5; }
                break;
            case C6_ADDKPC: put(b, value(a)); if (ins.count == 3) extra = value(c); break;
            case C6_ADDAB: case C6_ADDAH: case C6_ADDAW: case C6_ADDAD:
            case C6_SUBAB: case C6_SUBAH: case C6_SUBAW: {
                int scale = ins.opcode == C6_ADDAH || ins.opcode == C6_SUBAH ? 2 :
                    ins.opcode == C6_ADDAW || ins.opcode == C6_SUBAW ? 4 : ins.opcode == C6_ADDAD ? 8 : 1;
                if (ins.opcode >= C6_SUBAB && ins.opcode <= C6_SUBAW) scale = -scale;
                put(c, value(a) + uint32_t(signed32(value(b)) * scale)); break;
            }
            case C6_MPY: case C6_MPYU: case C6_MPYSU: case C6_MPYUS: {
                int64_t sx = value(a) & 0xffff, sy = value(b) & 0xffff;
                if ((ins.opcode == C6_MPY || ins.opcode == C6_MPYSU) && sx & 0x8000) sx -= 0x10000;
                if ((ins.opcode == C6_MPY || ins.opcode == C6_MPYUS) && sy & 0x8000) sy -= 0x10000;
                later(c, uint64_t(sx * sy), 1); break;
            }
            case C6_MPY32: case C6_MPY32U: case C6_MPY32SU: case C6_MPY32US: case C6_MPYLI: {
                int64_t sx = value(a), sy = value(b);
                if (ins.opcode == C6_MPYLI) { sx &= 0xffff; if (sx & 0x8000) sx -= 0x10000; sy = signed32(uint32_t(sy)); }
                else {
                    if (ins.opcode == C6_MPY32 || ins.opcode == C6_MPY32SU) sx = signed32(uint32_t(sx));
                    if (ins.opcode == C6_MPY32 || ins.opcode == C6_MPY32US) sy = signed32(uint32_t(sy));
                }
                later(c, uint64_t(sx) * uint64_t(sy), 3); break;
            }
            // SPRUFE8B MPYLH / MPYLHU: lsb16(src1) x msb16(src2), both signed or both unsigned; 1 delay slot.
            case C6_MPYLH: case C6_MPYLHU: {
                int64_t sx = value(a) & 0xffff, sy = value(b) >> 16;
                if (ins.opcode == C6_MPYLH) { if (sx & 0x8000) sx -= 0x10000; if (sy & 0x8000) sy -= 0x10000; }
                later(c, uint64_t(sx * sy), 1); break;
            }
            // SPRUFE8B DOTP2: a_hi x b_hi + a_lo x b_lo of signed packed halves, to a register or
            // sign-extended to a pair. MPY2: a_lo x b_lo to the even register, a_hi x b_hi to the odd
            // one. Both have 3 delay slots.
            case C6_DOTP2: case C6_MPY2: {
                int64_t ah = int16_t(value(a) >> 16), al = int16_t(value(a)), bh = int16_t(value(b) >> 16), bl = int16_t(value(b));
                if (ins.opcode == C6_DOTP2) later(c, uint64_t(ah * bh + al * bl), 3);
                else later(c, uint64_t(ah * bh) << 32 | uint32_t(al * bl), 3);
                break;
            }
            case C6_MPYHI: {
                int64_t sx = value(a) >> 16;
                if (sx & 0x8000) sx -= 0x10000;
                later(c, uint64_t(sx * signed32(value(b))), 3); break;
            }
            case C6_SHR2: {
                x = value(a); y = value(b) & 31;
                int64_t high = x >> 16, low = x & 0xffff;
                if (high & 0x8000) high -= 0x10000;
                if (low & 0x8000) low -= 0x10000;
                put(c, ((uint32_t(high >> y) & 0xffff) << 16) | (uint32_t(low >> y) & 0xffff)); break;
            }
            case C6_ADDSP: case C6_SUBSP: case C6_MPYSP: {
                float sx = single(value(a)), sy = single(value(b));
                float answer = ins.opcode == C6_ADDSP ? sx + sy : ins.opcode == C6_SUBSP ? sx - sy : sx * sy;
                later(c, single_bits(answer), 3); break;
            }
            case C6_INTSP: case C6_INTSPU: {
                float answer = ins.opcode == C6_INTSP ? float(signed32(value(a))) : float(value(a));
                later(b, single_bits(answer), 3); break;
            }
            case C6_SPTRUNC: case C6_SPINT: {
                double sx = single(value(a));
                if (std::isnan(sx) || sx >= 2147483648.0) v = 0x7fffffff;
                else if (sx < -2147483648.0) v = 0x80000000;
                else v = uint32_t(int64_t(ins.opcode == C6_SPINT ? std::nearbyint(sx) : std::trunc(sx)));
                later(b, v, 3); break;
            }
            case C6_CMPEQSP: case C6_CMPGTSP: case C6_CMPLTSP: {
                float sx = single(value(a)), sy = single(value(b));
                put(c, ins.opcode == C6_CMPEQSP ? sx == sy : ins.opcode == C6_CMPGTSP ? sx > sy : sx < sy); break;
            }
            case C6_ABSSP: put(b, value(a) & 0x7f800000 ? value(a) & 0x7fffffff : 0); break;
            case C6_RCPSP: case C6_RSQRSP: {
                float sx = single(value(a));
                if (std::isnan(sx)) v = 0x7fffffff;
                else if (sx == 0) v = 0x7f800000 | (std::signbit(sx) ? 0x80000000 : 0);
                else if (ins.opcode == C6_RSQRSP && sx < 0) v = 0x7fffffff;
                else if (std::isinf(sx)) v = sx < 0 ? 0x80000000 : 0;
                else v = uint32_t(estimate(single_bits(sx), 32, ins.opcode == C6_RSQRSP));
                put(b, v); break;
            }
            case C6_ROTL:
                x = value(a); y = value(b) & 31;
                later(c, y ? (x << y) | (x >> (32 - y)) : x, 1); break;
            case C6_LMBD:
                x = value(a) & 1; y = value(b); v = 0;
                while (v < 32 && ((y >> (31 - v)) & 1) != x) v++;
                put(c, v); break;
            case C6_NORM:
                x = value(a); v = 0;
                while (v < 31 && ((x >> (30 - v)) & 1) == (x >> 31)) v++;
                put(b, v); break;
            case C6_ABS: { int64_t sx = signed32(value(a)); put(b, saturated(sx < 0 ? -sx : sx)); break; }
            case C6_SUBC:
                x = value(a); y = value(b); put(c, x >= y ? ((x - y) << 1) | 1 : x << 1); break;
            case C6_PACK2: case C6_PACKHL2: case C6_PACKLH2: case C6_PACKL4:
                x = value(a); y = value(b);
                if (ins.opcode == C6_PACK2) v = (x << 16) | (y & 0xffff);
                else if (ins.opcode == C6_PACKHL2) v = (x & 0xffff0000) | (y & 0xffff);
                else if (ins.opcode == C6_PACKLH2) v = (x << 16) | (y >> 16);
                else v = ((x >> 16 & 255) << 24) | ((x & 255) << 16) | ((y >> 16 & 255) << 8) | (y & 255);
                put(c, v); break;
            case C6_SSHL: {
                int64_t sx = signed32(value(a)); y = value(b) & 63;
                uint32_t kept = y >= 32 ? (sx == 0 ? 0 : sx < 0 ? 0x80000000u : 0x7fffffffu) : saturated(sx * (int64_t(1) << y));
                put(c, kept);
                if (y >= 32 ? sx != 0 : signed32(kept) != sx * (int64_t(1) << y)) clipped(0);
                break;
            }
            default: throw std::runtime_error("unsupported opcode at " + hex(ins.address));
            }
        }
        if (issued_branches.size() > 1) throw std::runtime_error("multiple branches in one packet are not supported");
        if (extra > 9) throw std::runtime_error("unsupported NOP count");
        for (const auto &store : stores) {
            if (store_direct(store.address, store.value, store.size)) continue;
            uint8_t data[8];
            for (uint32_t i = 0; i < store.size; i++) data[i] = uint8_t(store.value >> (i * 8));
            write(store.address, data, store.size, true, store.pc);
        }
        for (const auto &write : immediate) regs[write.reg] = write.value;
        for (const auto &write : delayed) delay(write);
        if (!issued_branches.empty()) branches.insert(branches.end(), issued_branches.begin(), issued_branches.end());
        idle = 1 + (protected_load && load_present ? std::max(extra, 4u) : extra);
        pc = next; packets++;
        if (software_exception) {
            // SWE (SPRUFE8B 6.4, bit values as SYS/BIOS c64p Exception.xdc): taken after this execute packet.
            // NRP = the following packet, NTSR = TSR; TSR.GIE/SGIE cleared and EXC set; CSR.GIE and IER.NMIE
            // cleared; EFR.SXF set; entry through the NMI/exception vector (ISTP + 0x20). B NRP returns.
            if (!(regs[72] & 4)) throw std::runtime_error("SWE with TSR.GEE clear is not implemented");
            if (!branches.empty() || interrupt_due || loop_active || !draining.empty())
                throw std::runtime_error("SWE with branches, interrupt entry or loops in flight is not implemented");
            // SWENR differs (SPRUFE8B SWENR): NRP and NTSR are left alone, TSR.IB is set and entry is at REP.
            if (!no_return) { regs[70] = next; regs[82] = regs[72]; }
            regs[72] = (regs[72] & ~3u) | 0x400 | (no_return ? 0x8000u : 0);
            regs[64] &= ~1u;
            regs[65] &= ~2u;
            regs[83] |= 1;
            interrupt_target = no_return ? regs[86] : (regs[71] & ~1023u) + 32;
            interrupt_due = cycles + 9;
            idle = 0;
        }
    }
    void tick() {
        cycles++;
        if (!irq_writes.empty()) {
            uint32_t irq_set = 0, irq_clear = 0;
            for (const auto &write : irq_writes) if (write.due <= cycles) { irq_set |= write.set; irq_clear |= write.clear; }
            std::erase_if(irq_writes, [this](const auto &write) { return write.due <= cycles; });
            regs[66] = (regs[66] & ~irq_clear) | irq_set;
            recur.cleared |= irq_clear;
        }
        if (cycles >= board.next_event()) board.advance(cycles);
        if (held_cycle && cycles >= held_cycle) release_held();
        regs[66] |= board.pending_interrupts; board.pending_interrupts = 0;
        if (sat_due && cycles >= sat_due) [[unlikely]] { regs[64] |= 0x200; regs[88] |= sat_units; sat_due = 0; sat_units = 0; }
        if (pending_count) {
            auto &slot = due[cycles % Due::SLOTS];
            for (uint32_t i = 0; i < slot.count; i++) regs[slot.writes[i].first] = slot.writes[i].second;
            pending_count -= slot.count; slot.count = 0;
            if (!pending.empty()) {
                for (const auto &write : pending) if (write.due <= cycles) regs[write.reg] = write.value;
                pending_count -= uint32_t(std::erase_if(pending, [this](const Write &write) { return write.due <= cycles; }));
            }
        }
        if (!late.empty()) {
            for (auto &job : late) {
                bool waiting = false;
                for (unsigned index = 0; index + 1 < job.instruction.count; index++) {
                    if (job.due[index] && job.due[index] <= cycles) {
                        job.high[index] = reg(job.instruction.operands[index].reg); job.due[index] = 0;
                    }
                    waiting |= job.due[index] != 0;
                }
                if (!waiting) {
                    issue_delayed.clear(); finish_double(job, issue_delayed);
                    for (const auto &write : issue_delayed) delay(write);
                    job.instruction.opcode = C6_UNSUPPORTED;
                }
            }
            std::erase_if(late, [](const auto &job) { return job.instruction.opcode == C6_UNSUPPORTED; });
        }
        if (idle) idle--;
        bool landed = false;
        if (!branches.empty() && branches.front().due <= cycles) {
            landed = recur.active;
            if (branches.front().restore) {
                regs[72] = regs[branches.front().restore == 1 ? 81 : 82];
                regs[64] = (regs[64] & ~1u) | (regs[72] & 1);
                if (branches.front().restore == 2) regs[65] |= 2;
                // SPLX is modelled only as this marker of a return to an interrupted loop.
                if (regs[72] & 0x4000) { regs[72] &= ~0x4000u; loop_resume = true; loop_resume_pc = branches.front().target; }
            }
            pc = branches.front().target; branches.erase(branches.begin());
            block_seek = true;
            // The loop buffer goes idle, unless it is reloading: then program fetch stops instead.
            if (reload_pending) reload_landed = true;
            else { loop_active = false; loop.reload = false; draining.clear(); }
            idle = 0; idling = false; // SPRUFE8B 4.4.2: a completed branch terminates a multicycle NOP.
            if (stop_on_return && pc == return_address) status = C6_RETURNED;
        }
        if (interrupt_due && cycles >= interrupt_due) {
            pc = interrupt_target; idle = 0; idling = false; interrupt_due = 0;
        }
        if (landed) recurrence();
    }
    void release_held() {
        for (const auto &entry : recur.ahead) {
            std::memcpy(entry.page->data.data() + entry.offset, entry.after.data(), entry.size);
            ++entry.page->versions[entry.offset / 32];
        }
        recur.ahead.clear();
        board.pending_interrupts |= held_interrupts;
        held_interrupts = 0; held_cycle = 0;
    }
    // Runs the device event due at `due`, which lies within the next period, before the CPU
    // gets there. True if the CPU cannot tell: the period may then be skipped like any other.
    bool look_ahead(uint64_t due) {
        auto &r = recur;
        uint64_t anchor = cycles;
        r.ahead.clear(); r.looking = true; r.looks++;
        cycles = due; // Device accesses made by the event's DMA carry the event's own cycle.
        try { board.advance(due); }
        catch (...) { r.looking = false; cycles = anchor; throw; }
        r.looking = false; cycles = anchor;
        // A flag is nothing new only if it stays set through the whole period: one the loop
        // clears and sets again is set here at the anchor, yet clear when the event arrives.
        uint32_t raised = board.pending_interrupts & (~regs[66] | r.steady_cleared);
        if (!raised && r.proven) {
            board.pending_interrupts = 0; // Only flags that are set throughout: nothing to deliver.
            r.ahead.clear();
            return true;
        }
        // The CPU must not see this before `due`. Put back what the event overwrote in RAM
        // the loop touches and hold its interrupt flags; tick() releases both at `due`.
        if (!r.proven) for (auto entry = r.ahead.rbegin(); entry != r.ahead.rend(); ++entry) {
            std::memcpy(entry->page->data.data() + entry->offset, entry->before.data(), entry->size);
            ++entry->page->versions[entry->offset / 32];
        } else r.ahead.clear();
        held_interrupts = board.pending_interrupts; board.pending_interrupts = 0;
        held_cycle = due; r.held++;
        r.stop();
        return false;
    }
    void recurrence() {
        auto &r = recur;
        if (held_cycle) return;
        bool settled = !pending_count && late.empty() && branches.empty() && irq_writes.empty() &&
            !interrupt_due && !loop_active && draining.empty() && !idle && status == C6_BUDGET &&
            !board.pending_interrupts && !sat_due;
        uint64_t blocked = interrupt_blocked_until > cycles ? interrupt_blocked_until - cycles : 0;
        bool again = false; // Measure the next period from this same landing.
        if (r.recording || r.proven) {
            bool expired = interrupt_count != r.interrupts ||
                (r.recording && (r.impure || cycles - r.cycle > Recurrence::MAX_CYCLES));
            if (!expired && (pc != r.anchor || !settled)) return;
            bool same = !expired && blocked == r.blocked && fault_address == r.fault_address &&
                tsc_running == r.tsc_running && regs == r.regs;
            if (same && r.recording && unchanged_memory()) {
                r.recording = false; r.proven = true; r.proofs++;
                r.constant = !r.varying; r.steady_cleared = r.cleared;
                r.period = cycles - r.cycle; r.issued = packets - r.packets;
                r.favorite = r.anchor; r.favorite_failures = 0; r.backoff = 64;
            }
            if (same && r.proven) {
                for (;;) {
                    uint64_t due = board.next_event();
                    if (due <= cycles) break; // Eager polling, or an event already owed.
                    uint64_t limit = std::min(r.run_end, due - 1);
                    uint64_t count = limit > cycles ? (limit - cycles) / r.period : 0;
                    cycles += count * r.period; packets += count * r.issued;
                    if (blocked) interrupt_blocked_until = cycles + blocked;
                    r.skips += count != 0; r.skipped_cycles += count * r.period; r.skipped_packets += count * r.issued;
                    // Only an event inside this run's budget may run early: the host must never
                    // see a device ahead of the cycle count it is given.
                    if (!r.constant || due > r.run_end || due - cycles > r.period || !look_ahead(due)) break;
                }
                return;
            }
            // Same PC, other state: a longer period may still match. Not for long, though: a
            // snapshot taken where an interrupt returned differs from every later arrival.
            if (!expired && !same && r.recording && ++r.mismatches < 8) return;
            bool retry = !expired; // The state or RAM moved on: measure the next period from here.
            bool interrupted = interrupt_count != r.interrupts;
            r.stop();
            if (retry) again = true;
            else if (!interrupted) {
                // An interrupt says nothing about the anchor. Anything else counts against it.
                r.abandoned++;
                if (r.anchor == r.favorite && ++r.favorite_failures >= 4) r.favorite = 0;
                r.cooldown = packets + r.backoff; r.backoff = std::min<uint64_t>(r.backoff * 2, 262144);
            }
        }
        // While an anchor is known to repeat, other landings are tried only occasionally.
        if (!settled || (!again && pc != r.favorite && packets < r.cooldown + (r.favorite ? 4194304 : 0))) return;
        if (pc != r.favorite) r.cooldown = std::max(r.cooldown, packets);
        r.recording = true; r.impure = false; r.anchor = pc; r.attempts++;
        r.cycle = cycles; r.packets = packets; r.blocked = blocked;
        r.interrupts = interrupt_count; r.fault_address = fault_address; r.tsc_running = tsc_running;
        r.regs = regs; r.stores.clear(); r.loads.clear(); r.varying = false; r.mismatches = 0;
        r.cleared = 0;
    }
    bool unchanged_memory() {
        auto &r = recur;
        if (!++r.stamp) { for (auto &slot : r.slots) slot.stamp = 0; r.stamp = 1; }
        // The first logged value of each stored word is its content at the snapshot. A device
        // write during the period would also be logged here, so it must have changed nothing.
        for (const auto &[word, old] : r.stores) {
            auto &slot = r.slot(word);
            if (slot.stamp == r.stamp) continue;
            slot = {word, r.stamp, old};
            uint64_t now; std::memcpy(&now, find_page(word)->data.data() + word % PAGE, 8);
            if (now != old) return false;
        }
        for (uint32_t word : r.loads) r.slot(word) = {word, r.stamp, 0};
        return true;
    }
    bool interrupt() {
        if (interrupt_due) {
            if (cycles < interrupt_due) return true;
            pc = interrupt_target; idle = 0; idling = false; interrupt_due = 0;
        }
        if (!interruptible()) return false;
        if (loop_active) {
            // The loop pipes down first: advance_loop drains it and then enters the interrupt.
            if (loop_interruptible()) { loop.interrupted = true; loop.term = int64_t(cycles - loop.start); }
            return false;
        }
        return enter_interrupt();
    }
    // An enabled interrupt is pending and nothing architectural blocks it. Interruption of
    // protected waits needs additional modeling; those wait for the end of the multicycle NOP.
    // A nested loop waiting for its SPMASKR, or still reloading, is not interruptible (7.13.1).
    // SPRUFE8B 5.5.4: a multicycle NOP (IDLE included) is interrupted like any instruction. After its first
    // cycle the PC is already the next packet's, so that is the return address and the rest of the NOP is dropped.
    bool interruptible() const {
        if (!(regs[65] & regs[66] & 0xfff0) || !(regs[64] & 1) || !(regs[65] & 2) || !branches.empty() ||
            cycles < interrupt_blocked_until || loop.reload || reload_pending) return false;
        for (const auto &buffer : draining) if (cycles - buffer.start < buffer.end) return false;
        return true;
    }
    // SPRUFE8B 7.13.1: on a stage boundary, with the body loaded, the termination condition false,
    // past the first 3 cycles of an SPLOOPD or SPLOOPW, and enough iterations left (ILC at least
    // the number of loading stages) that the loop does not exit early when it is piped up again.
    // An invocation started by a reload is not interrupted here: the interrupt waits for its end.
    bool loop_interruptible() const {
        if (cycles <= loop.start || loop.term >= 0 || loop.stopping || loop.loading_only || loop.from_reload) return false;
        uint64_t time = cycles - loop.start;
        if (time % loop.ii || time < loop.boundary || (loop.kind != C6_SPLOOP && time <= 3)) return false;
        if (loop.kind == C6_SPLOOPW) return loop.history >> 3 & 1; // This cycle is not in the history yet.
        return loop.ilc >= loop.boundary / loop.ii;
    }
    bool enter_interrupt() {
        if (!interruptible()) return false;
        unsigned number = std::countr_zero(regs[65] & regs[66] & 0xfff0);
        regs[69] = pc; regs[81] = regs[72];
        if (loop_resume) { if (loop_resume_pc == pc) { regs[81] |= 0x4000; loop_interrupt_count++; } loop_resume = false; }
        regs[72] = (regs[72] & ~0x44cbu) | 0x200;
        regs[64] = (regs[64] & ~3u) | 2;
        irq_writes.push_back({cycles + 2, 0, 1u << number});
        interrupt_target = (regs[71] & ~1023u) + number * 32;
        interrupt_due = cycles + 9; interrupt_count++;
        return true;
    }
    template <bool Profile> bool advance_wait(uint64_t end) {
        // No instructions issue in this interval. Stop at every CPU/device event
        // so tick retains its exact ordering and any resulting DMA/IRQ side effects.
        // Late floating-point source reads and interrupt entry use ordinary ticks.
        if (!late.empty() || interrupt_due || board.pending_interrupts) return false;
        uint64_t stop = std::min(cycles + std::min(uint64_t(idle), end - cycles), board.next_event());
        if (held_cycle) stop = std::min(stop, held_cycle);
        if (pending_count) stop = std::min(stop, next_result());
        for (const auto &write : irq_writes) stop = std::min(stop, write.due);
        if (!branches.empty()) stop = std::min(stop, branches.front().due);
        if (stop <= cycles + 1) return false;
        uint32_t skipped = uint32_t(stop - cycles - 1);
        if constexpr (Profile) {
            guest_profile.wait_cycles += skipped + 1;
            guest_profile.wait_advances++; guest_profile.coalesced += skipped;
        }
        cycles += skipped; idle -= skipped;
        tick();
        return true;
    }
    template <bool Profile> uint32_t run_impl(uint64_t budget) {
        if (status == C6_RETURNED || status == C6_FAULT) return status;
        status = C6_BUDGET;
        if (budget > std::numeric_limits<uint64_t>::max() - cycles) throw std::runtime_error("cycle budget overflow");
        uint64_t end = cycles + budget;
        recur.stop(); recur.run_end = end;
        recur.active = recur.enabled && !Profile;
        while (cycles < end) {
            [[maybe_unused]] uint64_t previous_packets = packets;
            [[maybe_unused]] bool was_draining = !draining.empty();
            [[maybe_unused]] uint32_t issue_pc = pc;
            if (reload_pending) [[unlikely]] reload_step();
            if (idling) [[unlikely]] idle = 0x40000000; // Never runs out; only the events above end it.
            if (interrupt()) {
                if constexpr (Profile) guest_profile.irq_cycles++;
                tick(); continue;
            }
            if (idle > 1 && !loop_active && draining.empty() && advance_wait<Profile>(end)) {
                if (status == C6_RETURNED) break;
                continue;
            }
            if constexpr (!Profile) if (loop_native && loop_active) if (uint32_t count = loop_ready(*loop_native, end)) {
                uint64_t before = cycles;
                block_context.iterations = count; block_context.boundaries = 0; block_context.history = loop.history;
                loop_native->function(&block_context);
                if (loop.kind != C6_SPLOOPW) loop.ilc -= block_context.boundaries;
                else loop.history = block_context.history;
                loop.started += block_context.boundaries;
                block_entries++; block_cycles += cycles - before; block_loop_cycles += cycles - before;
                if (cycles != before) continue;
                loop_native = nullptr; // It refused its first cycle: interpret this loop.
            }
            if (loop_active && cycles >= loop.start && advance_loop()) {
                if constexpr (Profile) {
                    guest_profile.loop_cycles++;
                    if (packets != previous_packets) guest_profile.packet(loop.pc, true);
                }
                tick(); continue;
            }
            if constexpr (Profile) issue_pc = pc;
            if (!idle) {
                fault_address = pc;
                if ((breakpoint_bits[(pc >> 1) % 65536 / 64] >> ((pc >> 1) % 64) & 1) && breakpoints.contains(pc))
                    return status = C6_BREAKPOINT;
                if constexpr (!Profile) if (blocks_enabled) {
                    const auto &slot = block_slots[block_slot(pc)];
                    if (slot.block && slot.pc == pc && slot.block->function && block_ready(*slot.block, end)) {
                        uint64_t before = cycles;
                        bool ordinary_tick = slot.block->function(&block_context);
                        block_entries++; block_cycles += cycles - before; block_seek = true;
                        if (ordinary_tick) { tick(); if (status == C6_RETURNED) break; continue; }
                        if (cycles != before) continue;
                        // The block refused its first packet: interpret it.
                    } else if (block_heat_enabled && block_seek && branches.empty()) { block_heat[pc]++; block_seek = false; }
                }
                const auto *decoded = fetch(pc);
                if (!decoded || !decoded->executable) {
                    check(pc, 2, C6_EXECUTE);
                    if (decoded) decoded->executable = true;
                }
                if (!decoded || !valid(*decoded)) { decode_address = pc; return status = C6_DECODE; }
                // Ordinary packets need no loop state. In particular, do not initialize
                // a Loop's counters/vector on every instruction issue in the hot path.
                bool candidate = decoded->loop_control, resumed = false;
                uint32_t loop_at = pc;
                if (candidate) {
                    loop_candidate = Loop{};
                    if (!prepare_loop(*decoded, loop_candidate)) return status;
                    resumed = loop_resume && loop_resume_pc == pc; loop_resume = false;
                }
                // 7.13.2: on the return to an interrupted loop its SPLOOP packet executes nothing.
                if (resumed) [[unlikely]] { draining.clear(); issue(nullptr, 0, decoded->next, 0); }
                else if (!draining.empty() || decoded->reload_control) {
                    uint32_t mask = 0;
                    for (const auto &op : decoded->ops)
                        if (op.ins.opcode == C6_SPMASK || op.ins.opcode == C6_SPMASKR) mask |= op.ins.count ? value(op.ins.operands[0]) : 0;
                    buffered_ops.assign(decoded->refs.begin(), decoded->refs.end());
                    epilog(mask, buffered_ops);
                    issue(buffered_ops.data(), buffered_ops.size(), decoded->next, decoded->protected_load);
                } else if (decoded->nop_cycles) issue_nop(*decoded);
                else if (decoded->fast) issue_fast(decoded->refs.data(), decoded->refs.size(), decoded->next, decoded->protected_load);
                else {
                    issue_general(decoded->refs.data(), decoded->refs.size(), decoded->next, decoded->protected_load);
                    // No block can start with this packet, so the code after it would otherwise never be
                    // offered as an entry: look for (and count) one again at the next packet.
                    block_seek = true;
                }
                if (candidate) { begin_loop(std::move(loop_candidate), resumed); if (blocks_enabled) loop_bind(loop_at); }
                if (decoded->reload_control) {
                    if (loop.kernel_reload) throw std::runtime_error("SPMASKR after a loop that reloads by SPKERNELR");
                    begin_reload(cycles + 1);
                }
            } else if (!draining.empty()) {
                buffered_ops.clear();
                epilog(0, buffered_ops);
                if (!buffered_ops.empty()) {
                    uint32_t remaining = idle, next = pc;
                    issue(buffered_ops.data(), buffered_ops.size(), pc, 0);
                    idle = remaining; pc = next;
                }
            }
            if constexpr (Profile) {
                if (was_draining) guest_profile.drain_cycles++;
                if (packets != previous_packets) {
                    guest_profile.issue_cycles++; guest_profile.packet(issue_pc, false);
                } else guest_profile.wait_cycles++;
            }
            tick();
            if (status == C6_RETURNED) break;
        }
        return status;
    }
    uint32_t run(uint64_t budget) { return guest_profile.enabled ? run_impl<true>(budget) : run_impl<false>(budget); }
};

template <typename Function> int guarded(Machine *machine, Function fn) {
    try { fn(); return 0; }
    catch (const std::exception &error) { machine->error = error.what(); return -1; }
}
}

extern "C" {
uint32_t c6_abi_version() { return 2; }
uint32_t c6_decode_address(void *handle) { return static_cast<Machine *>(handle)->decode_address; }
void *c6_create() { try { return new Machine; } catch (...) { return nullptr; } }
void c6_destroy(void *handle) { delete static_cast<Machine *>(handle); }
const char *c6_error(void *handle) { return static_cast<Machine *>(handle)->error.c_str(); }
int c6_map(void *handle, uint32_t address, uint64_t size, uint32_t permissions) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] { m->map(address, size, permissions); });
}
int c6_alias(void *handle, uint32_t address, uint32_t target, uint64_t size) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] { m->alias(address, target, size); });
}
int c6_read(void *handle, uint32_t address, void *data, uint32_t size) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] { auto out = static_cast<uint8_t *>(data);
        if (m->board.contains(address, size)) {
            uint32_t value = m->board.read(address, size, m->cycles, m->pc, false);
            for (uint32_t i = 0; i < size; i++) out[i] = uint8_t(value >> (i * 8));
            return;
        }
        m->check(address, size, C6_READ);
        for (uint32_t i = 0; i < size; i++) out[i] = m->byte(address + i); });
}
int c6_write(void *handle, uint32_t address, const void *data, uint32_t size) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] { m->write(address, static_cast<const uint8_t *>(data), size, false); });
}
int c6_reset(void *handle, uint32_t pc, uint32_t sentinel, uint32_t stop) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] { m->reset(pc, sentinel, stop); });
}
int c6_set_register(void *handle, uint32_t reg, uint32_t value) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (reg == TSCL || reg == TSCH) throw std::runtime_error("TSC debug writes are not implemented");
        m->reg(int32_t(reg)); m->regs[reg] = value;
        if (reg == 64) { m->regs[72] = (m->regs[72] & ~1u) | (value & 1); m->regs[81] = (m->regs[81] & ~1u) | ((value >> 1) & 1); }
        if (reg == 72) m->regs[64] = (m->regs[64] & ~1u) | (value & 1);
        if (reg == 81) m->regs[64] = (m->regs[64] & ~2u) | ((value & 1) << 1);
    });
}
int c6_get_state(void *handle, c6_state *state) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] {
        state->cycles = m->cycles; state->packets = m->packets; state->pc = m->pc; state->status = m->status;
        state->idle_cycles = m->idle; state->pending_writes = uint32_t(m->pending_count + m->late.size());
        state->pending_branches = uint32_t(m->branches.size()); state->fault_address = m->fault_address;
        for (uint32_t i = 0; i < 96; i++) state->registers[i] = m->reg(int32_t(i));
    });
}
int c6_install(void *handle, uint32_t pc, uint32_t next, uint32_t prot, uint32_t begin, uint32_t size,
               const c6_instruction *instructions, uint32_t count) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] {
        if (!count || count > 8 || !size || size > 96 || begin % 32 || size % 32)
            throw std::runtime_error("invalid decoded packet");
        m->check(begin, size, C6_READ);
        Packet packet{next, prot, std::vector<Op>(count), {}, false, {}, 0};
        for (uint32_t index = 0; index < count; index++) {
            auto &op = packet.ops[index]; op.ins = instructions[index];
            if (op.ins.count > 4) throw std::runtime_error("too many operands");
            packet.refs.push_back(&op);
            // Registers whose reads are computed (ISR/ICR, ISTP, TSCL, PCE1) keep the general path.
            auto plain = [](int32_t reg) { return reg >= 0 && reg < 96 && reg != 67 && reg != 68 && reg != 71 && reg != int32_t(TSCL) && reg != 89; };
            for (uint32_t i = 0; i < op.ins.count; i++) {
                const auto &operand = op.ins.operands[i];
                if (operand.kind == C6_IMMEDIATE) op.source[i] = m->constant(uint32_t(operand.value));
                else if (operand.kind == C6_REGISTER && plain(operand.reg)) op.source[i] = &m->regs[operand.reg];
            }
            if (plain(op.ins.predicate)) op.predicate = &m->regs[op.ins.predicate];
            uint32_t opcode = op.ins.opcode;
            op.flags = (Machine::starts_loop(opcode) ? Op::LOOP : 0u) | (opcode == C6_UNSUPPORTED ? Op::UNSUPPORTED : 0u) |
                (opcode >= C6_LDW && opcode <= C6_LDNDW ? Op::LOAD : 0u) |
                (opcode == C6_B || opcode == C6_BNOP || opcode == C6_BDEC || opcode == C6_BPOS || opcode == C6_CALLP ? Op::BRANCH : 0u);
        }
        packet.fast = count <= Machine::FAST_OPS;
        for (auto &op : packet.ops) {
            op.fast = m->micro_enabled && m->compile(op);
            packet.fast &= op.fast;
        }
        packet.loop_control = std::any_of(packet.ops.begin(), packet.ops.end(), [](const auto &op) {
            return Machine::starts_loop(op.ins.opcode);
        });
        packet.reload_control = std::any_of(packet.ops.begin(), packet.ops.end(), [](const auto &op) {
            return op.ins.opcode == C6_SPMASKR;
        });
        if (count == 1) {
            const auto &ins = packet.ops.front().ins;
            if (ins.opcode == C6_NOP && ins.predicate < 0 && ins.count <= 1 &&
                (!ins.count || (ins.operands[0].kind == C6_IMMEDIATE &&
                               ins.operands[0].value >= 1 && ins.operands[0].value <= 9)))
                packet.nop_cycles = ins.count ? uint32_t(ins.operands[0].value) : 1;
        }
        for (uint64_t fp = begin; fp < uint64_t(begin) + size; fp += 32) {
            const auto counter = m->version(uint32_t(fp));
            packet.dependencies[packet.dependency_count++] = {counter, *counter};
        }
        m->cache[pc] = std::move(packet);
    });
}
int c6_run(void *handle, uint64_t budget) {
    auto m = static_cast<Machine *>(handle);
    try { return int(m->run(budget)); }
    catch (const std::exception &error) { m->error = error.what(); m->status = C6_FAULT; return C6_FAULT; }
}
int c6_breakpoint(void *handle, uint32_t address, uint32_t enabled) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] {
        if (enabled) m->breakpoints.insert(address); else m->breakpoints.erase(address);
        m->breakpoint_epoch++;
        m->breakpoint_bits.fill(0);
        for (uint32_t at : m->breakpoints) m->breakpoint_bits[(at >> 1) % 65536 / 64] |= uint64_t(1) << ((at >> 1) % 64);
    });
}
int c6_enable_board(void *handle) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] { m->enable_board(false); });
}
int c6_enable_board_profile(void *handle, uint32_t profile) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (profile > 1) throw std::runtime_error("unknown board handoff profile");
        m->enable_board(profile == 1);
    });
}
int c6_nor_load(void *handle, uint32_t chip, uint32_t offset, const uint8_t *data, uint32_t size) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (!m->board.enabled || chip >= 2) throw std::runtime_error("invalid SPI NOR chip");
        m->board.flash[chip].load(offset, data, size);
    });
}
int c6_nor_read(void *handle, uint32_t chip, uint32_t offset, uint8_t *data, uint32_t size) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (!m->board.enabled || chip >= 2 || uint64_t(offset) + size > 0x1000000)
            throw std::runtime_error("invalid SPI NOR backing range");
        auto &nor = m->board.flash[chip]; nor.advance(m->cycles);
        for (uint32_t i = 0; i < size; i++) data[i] = nor.at(offset + i);
    });
}
int c6_nor_stats(void *handle, uint32_t chip, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (!m->board.enabled || chip >= 2) throw std::runtime_error("invalid SPI NOR chip");
        auto &nor = m->board.flash[chip]; nor.advance(m->cycles);
        fields[0] = nor.commands; fields[1] = nor.bytes_read; fields[2] = nor.programs;
        fields[3] = nor.erases; fields[4] = nor.status();
    });
}
int c6_board_eager_polling(void *handle, uint32_t enabled) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] { m->board.set_eager_polling(enabled != 0); });
}
int c6_reserved_low_writes(void *handle, uint32_t enabled) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (!m->board.enabled || m->cycles || !m->board.reserved_writes.empty())
            throw std::runtime_error("reserved-low policy must be selected before execution on a fresh board");
        if (enabled) for (const auto &region : m->regions) if (region.begin < Board::RESERVED_END)
            throw std::runtime_error("reserved-low policy conflicts with mapped RAM");
        m->board.reserved_low_writes = enabled != 0;
    });
}
int c6_reserved_low_reads(void *handle, uint32_t enabled) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (!m->board.enabled || m->cycles || m->board.reserved_read_count)
            throw std::runtime_error("reserved-low policy must be selected before execution on a fresh board");
        if (enabled) for (const auto &region : m->regions) if (region.begin < Board::RESERVED_END)
            throw std::runtime_error("reserved-low policy conflicts with mapped RAM");
        m->board.reserved_low_reads = enabled != 0;
    });
}
int c6_reserved_low_read_stats(void *handle, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        fields[0] = m->board.reserved_low_reads; fields[1] = m->board.reserved_read_count; fields[2] = m->board.reserved_reads.size();
    });
}
int c6_reserved_low_read(void *handle, uint32_t index, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (index >= m->board.reserved_reads.size()) throw std::runtime_error("invalid reserved-low trace index");
        const auto &row = m->board.reserved_reads[index];
        fields[0] = row.cycle; fields[1] = row.pc; fields[2] = row.address; fields[3] = row.size; fields[4] = row.value;
    });
}
int c6_reserved_low_stats(void *handle, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        fields[0] = m->board.reserved_low_writes; fields[1] = m->board.reserved_writes.size();
    });
}
int c6_emifa_stores(void *handle, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        fields[0] = m->emifa_stores; fields[1] = m->emifa_address; fields[2] = m->emifa_pc;
    });
}
int c6_reserved_low_write(void *handle, uint32_t index, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (index >= m->board.reserved_writes.size()) throw std::runtime_error("invalid reserved-low trace index");
        const auto &row = m->board.reserved_writes[index];
        fields[0] = row.cycle; fields[1] = row.pc; fields[2] = row.address; fields[3] = row.size; fields[4] = row.value;
    });
}
int c6_usb_stats(void *handle, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (!m->board.enabled) throw std::runtime_error("board is not enabled");
        auto &usb = m->board.usb;
        fields[0] = usb.resets; fields[1] = usb.phy_ready; fields[2] = usb.soft_connect();
        fields[3] = usb.interrupt_mask(); fields[4] = usb.interrupt_source(); fields[5] = usb.interrupts;
    });
}
int c6_usb_attach(void *handle, uint32_t attached) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (!m->board.enabled) throw std::runtime_error("the USB host needs the board");
        m->board.usb.attach(attached != 0, m->cycles); m->board.rescheduled();
    });
}
int c6_usb_bus_reset(void *handle) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (!m->board.enabled) throw std::runtime_error("the USB host needs the board");
        m->board.usb.reset_bus(m->cycles); m->board.rescheduled();
    });
}
int c6_usb_sof(void *handle, uint32_t enabled) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (!m->board.enabled) throw std::runtime_error("the USB host needs the board");
        m->board.usb.sof(enabled != 0, m->cycles); m->board.rescheduled();
    });
}
int c6_usb_toggle_reset(void *handle, uint32_t endpoint) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (!m->board.enabled) throw std::runtime_error("the USB host needs the board");
        m->board.usb.toggle_reset(endpoint);
    });
}
int c6_usb_submit(void *handle, uint32_t kind, uint32_t endpoint, const uint8_t *setup, const uint8_t *data, uint32_t size,
                  uint32_t length, uint32_t max_packet, uint64_t timeout, uint32_t *id) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (!m->board.enabled) throw std::runtime_error("the USB host needs the board");
        if (kind > Usb::IN || size > 65535 || length > 65535) throw std::runtime_error("invalid USB transfer");
        Usb::Transfer transfer;
        transfer.kind = uint8_t(kind); transfer.endpoint = uint8_t(endpoint);
        if (kind == Usb::CONTROL) std::copy(setup, setup + 8, transfer.setup.begin());
        transfer.data.assign(data, data + size);
        transfer.length = length; transfer.packet = max_packet;
        *id = m->board.usb.submit(std::move(transfer), timeout, m->cycles); m->board.rescheduled();
    });
}
int c6_usb_transfer(void *handle, uint32_t id, uint64_t *fields, uint8_t *data, uint32_t capacity) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        m->board.advance(m->cycles);
        const Usb::Transfer *transfer = m->board.usb.find(id);
        if (!transfer) throw std::runtime_error("unknown USB transfer (finished ones are kept until read, the latest 256)");
        uint32_t copied = uint32_t(std::min<size_t>(capacity, transfer->data.size()));
        std::copy(transfer->data.begin(), transfer->data.begin() + copied, data);
        fields[0] = transfer->status; fields[2] = transfer->submitted;
        fields[1] = transfer->naks + (transfer == &m->board.usb.peer().queue.front() ? m->board.usb.parked_naks(m->cycles) : 0);
        fields[3] = transfer->completed; fields[4] = transfer->data.size(); fields[5] = copied; fields[6] = transfer->offset;
        if (transfer->status != Usb::PENDING) m->board.usb.forget(id);
    });
}
int c6_usb_run(void *handle, uint32_t id, uint64_t budget) {
    auto m = static_cast<Machine *>(handle);
    try {
        while (budget && m->board.usb.pending(id)) {
            uint64_t slice = std::min<uint64_t>(budget, 1024);
            uint64_t before = m->cycles;
            uint32_t status = m->run(slice);
            if (status != C6_BUDGET) return int(status);
            if (m->cycles == before) break;
            budget -= std::min(budget, m->cycles - before);
        }
        return C6_BUDGET;
    } catch (const std::exception &error) { m->error = error.what(); m->status = C6_FAULT; return C6_FAULT; }
}
int c6_usb_host_stats(void *handle, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (!m->board.enabled) throw std::runtime_error("the USB host needs the board");
        m->board.advance(m->cycles);
        const auto &usb = m->board.usb; const auto &host = usb.peer();
        fields[0] = uint64_t(host.port); fields[1] = host.vbus; fields[2] = host.address; fields[3] = host.configuration;
        fields[4] = usb.function_address(); fields[5] = host.resets; fields[6] = host.sof; fields[7] = host.sofs;
        fields[8] = host.frame; fields[9] = host.suspended; fields[10] = host.naks + usb.parked_naks(m->cycles); fields[11] = host.stalls;
        fields[12] = host.errors; fields[13] = host.toggle_errors; fields[14] = host.transfers; fields[15] = host.queue.size();
        fields[16] = usb.fifo_overflows; fields[17] = usb.fifo_underflows; fields[18] = usb.wrapper_control();
        fields[19] = usb.connected();
    });
}
int c6_usb_endpoint(void *handle, uint32_t number, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (!m->board.enabled || number < 1 || number > 4) throw std::runtime_error("USB0 has endpoints 1 to 4 besides endpoint 0");
        const auto &e = m->board.usb.endpoint(number);
        fields[0] = e.txmaxp; fields[1] = e.rxmaxp; fields[2] = e.txsz; fields[3] = e.rxsz; fields[4] = e.txadd; fields[5] = e.rxadd;
        fields[6] = e.tx_packets; fields[7] = e.rx_packets; fields[8] = e.tx_stall; fields[9] = e.rx_stall;
        fields[10] = e.txcsrh; fields[11] = e.rxcsrh;
    });
}
int c6_usb_reserved_status_stats(void *handle, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        fields[0] = m->board.usb_reserved_count; fields[1] = m->board.usb_reserved_reads.size();
    });
}
int c6_usb_reserved_status_read(void *handle, uint32_t index, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (index >= m->board.usb_reserved_reads.size()) throw std::runtime_error("invalid USB reserved-status trace index");
        const auto &r = m->board.usb_reserved_reads[index];
        fields[0] = r.cycle; fields[1] = r.pc; fields[2] = r.address; fields[3] = r.size; fields[4] = r.value;
    });
}
int c6_i2c_stats(void *handle, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (!m->board.enabled) throw std::runtime_error("board is not enabled");
        auto &i = m->board.i2c; auto &c = m->board.codec;
        fields[0] = i.starts; fields[1] = i.stops; fields[2] = i.bytes_sent;
        fields[3] = i.bytes_received; fields[4] = i.nacks;
        fields[5] = c.writes; fields[6] = c.resets; fields[7] = c.current_page(); fields[8] = c.trace.size();
    });
}
int c6_codec_register(void *handle, uint32_t page, uint32_t reg, uint32_t *value) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (!m->board.enabled) throw std::runtime_error("board is not enabled");
        *value = m->board.codec.inspect(page, reg);
    });
}
int c6_codec_write(void *handle, uint32_t index, uint64_t *cycle, uint32_t *fields) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        auto &trace = m->board.codec.trace;
        if (!m->board.enabled || index >= trace.size()) throw std::runtime_error("invalid codec trace index");
        auto &w = trace[index]; *cycle = w.cycle;
        fields[0] = w.page; fields[1] = w.reg; fields[2] = w.value;
    });
}
int c6_audio_stats(void *handle, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (!m->board.enabled) throw std::runtime_error("board is not enabled");
        auto &a = m->board.mcasp;
        fields[0] = a.transmitted; fields[1] = a.received; fields[2] = a.underruns; fields[3] = a.overruns;
        fields[4] = a.output.size(); fields[5] = a.output.empty() ? 0 : a.output.front().cycle;
        fields[6] = a.output.empty() ? 0 : a.output.front().slot; fields[7] = a.output.empty() ? 0 : a.output.back().cycle;
    });
}
int c6_audio_copy(void *handle, uint32_t offset, uint32_t *words, uint32_t count) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        auto &output = m->board.mcasp.output;
        if (!m->board.enabled || uint64_t(offset) + count > output.size()) throw std::runtime_error("invalid audio capture range");
        for (uint32_t i = 0; i < count; i++) words[i] = output[offset + i].value;
    });
}
int c6_audio_input(void *handle, const uint8_t *data, uint32_t size, uint32_t loop) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (!m->board.enabled || loop > 1) throw std::runtime_error("invalid audio input configuration");
        m->board.mcasp.load_input(data, size, loop != 0);
    });
}
int c6_audio_input_stats(void *handle, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (!m->board.enabled) throw std::runtime_error("board is not enabled");
        m->board.mcasp.input_stats(fields);
    });
}
uint64_t c6_mmio_count(void *handle) { return static_cast<Machine *>(handle)->board.accesses; }
int c6_sd_load(void *handle, const uint8_t *data, uint32_t size) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (!m->board.enabled || m->cycles) throw std::runtime_error("SD backing must be loaded on an enabled board before execution");
        m->board.mmcsd.card.load(data, size); m->board.gpio_input(4, 0, false);
    });
}
int c6_sd_read(void *handle, uint32_t offset, uint8_t *data, uint32_t size) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        auto &image = m->board.mmcsd.card.image;
        if (!m->board.enabled || image.empty() || uint64_t(offset) + size > image.size())
            throw std::runtime_error("invalid SD backing read range");
        std::copy_n(image.begin() + offset, size, data);
    });
}
int c6_sd_stats(void *handle, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (!m->board.enabled) throw std::runtime_error("board is not enabled");
        auto &c = m->board.mmcsd.card;
        fields[0] = c.image.size(); fields[1] = c.state; fields[2] = c.width; fields[3] = c.commands;
        fields[4] = c.bytes_read; fields[5] = c.bytes_written; fields[6] = c.trace.size();
    });
}
int c6_sd_command(void *handle, uint32_t index, uint64_t *cycle, uint32_t *fields) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        auto &trace = m->board.mmcsd.card.trace;
        if (!m->board.enabled || index >= trace.size()) throw std::runtime_error("invalid SD command trace index");
        auto &row = trace[index]; *cycle = row.cycle;
        fields[0] = row.command; fields[1] = row.argument; fields[2] = row.response; fields[3] = row.state;
    });
}
int c6_mmio_access(void *handle, uint64_t sequence, uint64_t *cycle, uint32_t *fields) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] {
        auto access = m->board.access(sequence); *cycle = access.cycle;
        fields[0] = access.pc; fields[1] = access.address; fields[2] = access.value;
        fields[3] = access.size; fields[4] = access.write;
    });
}
int c6_packet_info(void *handle, uint32_t pc, uint32_t *fields, c6_instruction *instructions) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] {
        auto found = m->cache.find(pc);
        if (found == m->cache.end()) throw std::runtime_error("packet is not cached");
        const auto &packet = found->second;
        fields[0] = packet.next; fields[1] = packet.protected_load; fields[2] = uint32_t(packet.ops.size());
        fields[3] = m->valid(packet);
        for (const auto &op : packet.ops) *instructions++ = op.ins;
    });
}
int c6_gpio_input(void *handle, uint32_t bank, uint32_t pin, uint32_t high) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] { m->board.gpio_input(bank, pin, high != 0); });
}
int c6_key_input(void *handle, uint32_t key, uint32_t down) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] { m->board.key_input(key, down != 0); });
}
int c6_fast_forward(void *handle, uint32_t enabled) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] { m->recur.enabled = enabled != 0; });
}
int c6_micro(void *handle, uint32_t enabled) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] { m->micro_enabled = enabled != 0; });
}
int c6_blocks(void *handle, uint32_t enabled, uint32_t heat) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] { m->block_bind(); m->blocks_enabled = enabled != 0; m->block_heat_enabled = heat != 0; });
}
int c6_block_hot(void *handle, uint32_t *pcs, uint64_t *counts, uint32_t capacity, uint32_t *count) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] {
        std::vector<std::pair<uint64_t, uint32_t>> rows;
        for (const auto &[pc, heat] : m->block_heat) rows.push_back({heat, pc});
        std::sort(rows.rbegin(), rows.rend());
        *count = uint32_t(std::min<size_t>(rows.size(), capacity));
        for (uint32_t i = 0; i < *count; i++) { pcs[i] = rows[i].second; counts[i] = rows[i].first; }
    });
}
int c6_block_source(void *handle, uint32_t pc, char *buffer, uint32_t capacity, uint32_t *fields) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] {
        Block block; std::string source; uint32_t continuation = 0;
        fields[0] = fields[1] = fields[2] = 0;
        m->block_reason = "not straight fast code at " + hex(pc);
        if (!m->block_plan(pc, block, &source, continuation) && !m->loop_plan(pc, block, &source)) {
            std::snprintf(buffer, capacity, "%s", m->block_reason.c_str()); // The reason, for diagnosis.
            return;
        }
        if (source.size() + 1 > capacity) throw std::runtime_error("block source buffer too small");
        std::memcpy(buffer, source.c_str(), source.size() + 1);
        fields[0] = uint32_t(source.size()); fields[1] = block.ticks; fields[2] = continuation;
    });
}
int c6_block_install(void *handle, uint32_t pc, void *function) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] {
        Block block; uint32_t continuation = 0;
        if (!m->block_plan(pc, block, nullptr, continuation) && !m->loop_plan(pc, block, nullptr))
            throw std::runtime_error("block cannot be planned at " + hex(pc));
        block.function = reinterpret_cast<C6BlockFunction>(function);
        m->loop_native = nullptr; // It may point at the entry replaced here.
        auto &stored = m->blocks[pc] = std::move(block);
        if (!stored.loop) m->block_slots[Machine::block_slot(pc)] = {pc, &stored};
    });
}
int c6_block_stats(void *handle, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] {
        fields[0] = m->blocks_enabled; fields[1] = m->blocks.size(); fields[2] = m->block_entries;
        fields[3] = m->block_cycles; fields[4] = m->block_refusals; fields[5] = m->block_loop_cycles;
    });
}
int c6_fast_forward_stats(void *handle, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        const auto &r = m->recur;
        fields[0] = r.enabled; fields[1] = r.skips; fields[2] = r.skipped_cycles; fields[3] = r.skipped_packets;
        fields[4] = r.attempts; fields[5] = r.abandoned; fields[6] = r.proofs; fields[7] = r.looks; fields[8] = r.held;
    });
}
uint64_t c6_interrupt_count(void *handle) { return static_cast<Machine *>(handle)->interrupt_count; }
uint64_t c6_loop_interrupt_count(void *handle) { return static_cast<Machine *>(handle)->loop_interrupt_count; }
int c6_guest_profile(void *handle, uint32_t period) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        if (period > 1000000) throw std::runtime_error("guest sample period must be 0..1000000");
        auto &p = m->guest_profile;
        if (!period) {
            if (p.enabled) {
                p.end_cycle = m->cycles; p.end_packet = m->packets; p.end_irq = m->interrupt_count;
                p.enabled = false;
            }
        } else {
            p = GuestProfile{}; p.enabled = true; p.period = p.countdown = period;
            p.begin_cycle = m->cycles; p.begin_packet = m->packets; p.begin_irq = m->interrupt_count;
        }
    });
}
int c6_guest_profile_stats(void *handle, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        auto &p = m->guest_profile; p.snapshot();
        fields[0] = p.enabled; fields[1] = p.period;
        fields[2] = (p.enabled ? m->cycles : p.end_cycle) - p.begin_cycle;
        fields[3] = (p.enabled ? m->packets : p.end_packet) - p.begin_packet;
        fields[4] = (p.enabled ? m->interrupt_count : p.end_irq) - p.begin_irq;
        fields[5] = p.issue_cycles; fields[6] = p.wait_cycles;
        fields[7] = p.loop_cycles; fields[8] = p.irq_cycles; fields[9] = p.drain_cycles;
        fields[10] = p.loop_packets; fields[11] = p.wait_advances; fields[12] = p.coalesced;
        fields[13] = p.samples; fields[14] = p.dropped; fields[15] = p.rows.size();
    });
}
int c6_guest_profile_pc(void *handle, uint32_t index, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle); return guarded(m, [&] {
        const auto &p = m->guest_profile;
        if (!p.rows_valid || index >= p.rows.size()) throw std::runtime_error("invalid guest profile PC snapshot/index");
        const auto &[key, samples] = p.rows[index];
        fields[0] = uint32_t(key); fields[1] = key >> 32; fields[2] = samples;
    });
}
int c6_uart_receive(void *handle, uint32_t index, uint32_t byte) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] { m->board.uart_receive(index, uint8_t(byte)); });
}
int c6_panel_stream(void *handle, uint32_t enabled) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] { m->board.panel_stream(enabled != 0, m->cycles); });
}
int c6_panel_level(void *handle, uint32_t channel, uint32_t value) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] { m->board.panel_level(channel, value); });
}
int c6_panel_stream_stats(void *handle, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] {
        fields[0] = m->board.panel.enabled; fields[1] = m->board.panel.messages;
        for (unsigned channel = 0; channel < 16; channel++) fields[2 + channel] = m->board.panel.levels[channel];
    });
}
int c6_uart_sent(void *handle, uint32_t index, uint64_t since, uint8_t *data, uint32_t capacity, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] {
        if (!m->board.enabled || index >= m->board.uart_sent.size()) throw std::runtime_error("invalid UART index");
        const auto &sent = m->board.uart_sent[index];
        uint64_t first = std::max(since, sent.count > sent.bytes.size() ? sent.count - sent.bytes.size() : 0);
        uint64_t copied = 0;
        for (uint64_t at = first; at < sent.count && copied < capacity; at++) data[copied++] = sent.bytes[at % sent.bytes.size()];
        fields[0] = sent.count; fields[1] = copied;
    });
}
int c6_uart_sent_cycles(void *handle, uint32_t index, uint64_t since, uint64_t *cycles, uint32_t capacity, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] {
        if (!m->board.enabled || index >= m->board.uart_sent.size()) throw std::runtime_error("invalid UART index");
        const auto &sent = m->board.uart_sent[index];
        uint64_t first = std::max(since, sent.count > sent.cycles.size() ? sent.count - sent.cycles.size() : 0);
        uint64_t copied = 0;
        for (uint64_t at = first; at < sent.count && copied < capacity; at++) cycles[copied++] = sent.cycles[at % sent.cycles.size()];
        fields[0] = sent.count; fields[1] = copied;
    });
}
int c6_midi_in(void *handle, const uint8_t *data, uint32_t size) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] { m->board.midi_in(data, size, m->cycles); });
}
int c6_midi_loopback(void *handle, uint32_t enabled) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] { m->board.midi_loopback(enabled != 0); });
}
int c6_midi_stats(void *handle, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] {
        if (!m->board.enabled) throw std::runtime_error("MIDI IN needs the board");
        const auto &midi = m->board.midi; auto state = m->board.midi_state();
        fields[0] = midi.queue.size(); fields[1] = midi.delivered; fields[2] = midi.ignored; fields[3] = midi.looped;
        fields[4] = midi.loopback; fields[5] = midi.queue.empty() ? 0 : midi.next;
        fields[6] = state.character_cycles; fields[7] = state.fifo; fields[8] = state.overruns; fields[9] = state.line_errors;
    });
}
int c6_gpio_schedule(void *handle, uint32_t bank, uint32_t pin, uint32_t high, uint64_t cycle) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] { m->board.gpio_schedule(bank, pin, high != 0, cycle, m->cycles); });
}
int c6_gpio_schedule_clear(void *handle, uint32_t bank, uint32_t pin) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] { m->board.gpio_schedule_clear(bank, pin); });
}
int c6_gpio_watch(void *handle, uint32_t bank, uint32_t pin, uint32_t enabled) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] { m->board.gpio_watch(bank, pin, enabled != 0, m->cycles); });
}
int c6_gpio_trace(void *handle, uint64_t since, uint64_t *rows, uint32_t capacity, uint64_t *fields) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] {
        if (!m->board.enabled) throw std::runtime_error("the GPIO trace needs the board");
        const auto &trace = m->board.gpio_trace;
        uint64_t first = std::max(since, trace.count > trace.rows.size() ? trace.count - trace.rows.size() : 0);
        uint64_t copied = 0;
        for (uint64_t at = first; at < trace.count && copied < capacity; at++, copied++) {
            const auto &row = trace.rows[at % trace.rows.size()];
            rows[copied * 2] = row.cycle; rows[copied * 2 + 1] = uint64_t(row.bank) << 16 | row.pin << 8 | row.high;
        }
        fields[0] = trace.count; fields[1] = copied; fields[2] = m->board.gpio_scheduled.size();
    });
}
int c6_oled_frame(void *handle, uint8_t *data, uint64_t *bytes, uint32_t *fields) {
    auto m = static_cast<Machine *>(handle);
    return guarded(m, [&] {
        const auto &oled = m->board.oled;
        std::copy(oled.ram.begin(), oled.ram.end(), data); *bytes = oled.bytes;
        fields[0] = oled.on; fields[1] = oled.contrast; fields[2] = oled.remap; fields[3] = oled.cursor % 8192;
    });
}
uint64_t c6_oled_first_frame_cycle(void *handle) { return static_cast<Machine *>(handle)->board.oled.first_frame_cycle; }
}
