#include "codec.h"
#include <cstdio>
#include <stdexcept>

uint8_t Codec::mask(unsigned bank, unsigned reg) const {
    if (reg == 0) return 1;
    if (bank == 1 && 65 <= reg && reg <= 76) return 255;
    if (bank == 0) switch (reg) {
    case 1: return 0x80;
    case 2: case 3: case 5: case 9: case 10: case 12: case 15: case 16:
    case 17: case 18: case 19: case 22: case 43: case 44: return 255;
    case 4: case 6: return 0xfc;
    case 7: case 42: return 0xfe;
    case 8: return 0xf7;
    case 21: case 24: case 86: case 93: return 0xf8;
    case 37: return 0xf0;
    case 41: return 0xf3;
    case 107: return 0xfc;
    }
    char text[100]; std::snprintf(text, sizeof text, "unimplemented codec page %u register %u", bank, reg);
    throw std::runtime_error(text);
}
void Codec::reset_registers() {
    regs = {}; page = pointer = 0;
    regs[0][3] = 0x10; regs[0][4] = 4;
    for (unsigned reg : {15, 16, 43, 44}) regs[0][reg] = 0x80;
    for (unsigned reg : {17, 18}) regs[0][reg] = 0xff;
    for (unsigned reg : {19, 21, 22, 24}) regs[0][reg] = 0x78;
    regs[0][86] = regs[0][93] = 2; // gain/power status transitions remain unmodeled
    constexpr uint8_t hpf[] = {0x39, 0x55, 0xf3, 0x2d, 0x53, 0x7e};
    for (unsigned i = 0; i < 12; i++) regs[1][65 + i] = hpf[i % 6];
}
void Codec::reset() { reset_registers(); writes = resets = 0; trace.clear(); expect_pointer = true; }
bool Codec::send(uint8_t value, uint64_t cycle) {
    if (expect_pointer) {
        if (value >= 128) throw std::runtime_error("codec register address exceeds 127");
        pointer = value; expect_pointer = false; return true;
    }
    uint32_t old_page = page, old_pointer = pointer;
    uint8_t writable = mask(page, pointer);
    if (pointer == 0) {
        if (value > 1) throw std::runtime_error("unimplemented codec page selection");
        page = value;
    } else if (page == 0 && pointer == 1 && (value & 0x80)) { reset_registers(); resets++; }
    else regs[page][pointer] = (regs[page][pointer] & ~writable) | (value & writable);
    writes++;
    trace.push_back({cycle, old_page, old_pointer, value});
    if (trace.size() > 256) trace.pop_front();
    pointer = uint8_t((old_pointer + 1) & 127);
    return true;
}
uint8_t Codec::inspect(unsigned bank, unsigned reg) const {
    if (bank >= 2 || reg >= 128) throw std::runtime_error("invalid codec register");
    (void)mask(bank, reg);
    return reg == 0 ? page : regs[bank][reg];
}
uint8_t Codec::receive() {
    uint8_t value = inspect(page, pointer); pointer = uint8_t((pointer + 1) & 127); return value;
}
