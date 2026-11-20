#include "edma.h"
#include <cstdio>
#include <stdexcept>

namespace {
std::runtime_error unknown(uint32_t offset) {
    char text[80]; std::snprintf(text, sizeof text, "unimplemented EDMA3 CC0 register 0x%08x", 0x01c00000 + offset);
    return std::runtime_error(text);
}
bool config(uint32_t off) {
    return (off >= 0x200 && off < 0x220 && !(off & 3)) ||
           (off >= 0x240 && off < 0x250 && !(off & 3)) || off == 0x260 || off == 0x284 ||
           (off >= 0x340 && off < 0x360 && !(off & 3)) ||
           (off >= 0x380 && off < 0x390 && !(off & 3)) || off == 0x620;
}
bool high_half(uint32_t off) { return off >= 0x1000 && off < 0x1078 && (off & 7) == 4; }
}
uint32_t Edma::access_mask(uint32_t offset, uint32_t &global) {
    if (offset >= 0x2000 && offset < 0x2800) {
        unsigned region = (offset - 0x2000) / 0x200;
        global = 0x1000 + (offset & 0x1ff);
        if (global >= 0x1080) return registers[0x380 + region * 4] & 255;
        if (high_half(global)) return 0;
        return registers[0x340 + region * 8];
    }
    global = offset;
    return 0xffffffff;
}
void Edma::event(unsigned channel) {
    if (channel >= 32) throw std::runtime_error("invalid EDMA channel");
    if (registers[0x1000] & (1u << channel)) registers[0x300] |= 1u << channel;
    registers[0x1000] |= 1u << channel;
    work_pending = true;
}
void Edma::refresh_interrupt(bool force) {
    // The C6748 DSP sees EDMA3_0_CC0_INT1 (event 8), shadow region 1.
    bool high = registers[0x1068] & registers[0x1050] & registers[0x348];
    if (high && (!irq_high || force)) interrupt();
    irq_high = high;
}
void Edma::transfer(unsigned channel) {
    auto &p = params[channel];
    uint32_t opt = p[0], acnt = p[2] & 0xffff, bcnt = p[2] >> 16, ccnt = p[7] & 0xffff;
    if (!acnt || !bcnt || !ccnt) return; // exhausted/null PaRAM cannot move data
    if (opt & 0x00c00808) throw std::runtime_error("EDMA static, early completion or chaining mode is not implemented");
    bool constant_src = opt & 1, constant_dst = opt & 2;
    if ((constant_src || constant_dst) && (acnt != 4 || ((opt >> 8) & 7) != 2 ||
        (constant_src && (p[1] & 31)) || (constant_dst && (p[3] & 31))))
        throw std::runtime_error("EDMA FIFO supports only one 32-bit word at a 32-byte-aligned port per array");
    unsigned tcc = opt >> 12 & 63;
    if (tcc > 31) throw std::runtime_error("EDMA TCC exceeds C6748's 32 completion codes");
    bool ab = opt & 4;
    uint32_t arrays = ab ? bcnt : 1;
    auto sx = constant_src ? 0 : int16_t(p[4]), dx = constant_dst ? 0 : int16_t(p[4] >> 16);
    uint32_t src = p[1], dst = p[3];
    // Each A array is contiguous. B indices select the next array, including negative strides.
    for (uint32_t index = 0; index < arrays; index++) copy(src + uint32_t(index * sx), dst + uint32_t(index * dx), acnt);
    if (ab || bcnt == 1) {
        if (!constant_src) p[1] += uint32_t(int16_t(p[6]));
        if (!constant_dst) p[3] += uint32_t(int16_t(p[6] >> 16));
        p[7] = --ccnt;
        if (!ab) p[2] = acnt | (p[5] & 0xffff0000);
    } else {
        p[1] += uint32_t(sx); p[3] += uint32_t(dx); p[2] = acnt | ((bcnt - 1) << 16);
    }
    if (!ccnt) {
        uint32_t link = p[5] & 0xffff;
        if (link != 0xffff) {
            if (link < 0x4000 || link >= 0x5000 || (link & 31)) throw std::runtime_error("invalid EDMA PaRAM link");
            p = params[(link - 0x4000) / 32];
        } else { p.fill(0); p[5] = 0xffff; }
        if (opt & 0x100000) registers[0x1068] |= 1u << tcc;
    } else if (opt & 0x200000) registers[0x1068] |= 1u << tcc;
    refresh_interrupt();
}
void Edma::service() {
    if (!work_pending) return;
    for (unsigned count = 0; count < 4096; count++) {
        uint32_t ready = manual | (registers[0x1000] & registers[0x1020]);
        if (!ready) { work_pending = false; return; }
        unsigned channel = 0;
        while (!(ready & (1u << channel))) channel++;
        manual &= ~(1u << channel); registers[0x1000] &= ~(1u << channel);
        transfer(channel);
    }
    throw std::runtime_error("EDMA event service did not settle");
}
uint32_t Edma::read(uint32_t offset) {
    if (offset & 3) throw unknown(offset);
    if (offset >= 0x4000 && offset < 0x5000) return params[(offset - 0x4000) / 32][offset / 4 % 8];
    if (config(offset)) return registers[offset];
    if (offset == 0x300 || offset == 0x310 || offset == 0x318) return registers[offset];
    if (offset == 0x304 || offset == 0x308 || offset == 0x30c || offset == 0x314 || offset == 0x31c || offset == 0x320 ||
        offset == 0x600 || offset == 0x604 || offset == 0x640) return 0;
    uint32_t global, mask = access_mask(offset, global);
    if (high_half(global)) return 0; // 32 DMA channels and TCCs on C6748.
    switch (global) {
    case 0x1000: case 0x1020: case 0x1038: case 0x1050: case 0x1068:
    case 0x1080: case 0x1084: case 0x1090: return registers[global] & mask;
    case 0x1008: case 0x1010: case 0x1018: case 0x1028: case 0x1030: case 0x1040:
    case 0x1058: case 0x1060: case 0x1070: case 0x1078: case 0x1088: case 0x108c: case 0x1094: return 0;
    default: throw unknown(offset);
    }
}
void Edma::write(uint32_t offset, uint32_t value) {
    if (offset & 3) throw unknown(offset);
    if (offset >= 0x4000 && offset < 0x5000) {
        unsigned set = (offset - 0x4000) / 32, word = offset / 4 % 8;
        for (unsigned channel = 0; channel < 8; channel++) {
            uint32_t map = registers[0x200 + channel * 4];
            if ((registers[0x1084] & (1u << channel)) && ((map >> 5) & 127) == set && ((map >> 2) & 7) == word)
                throw std::runtime_error("EDMA QDMA transfer trigger is not implemented");
        }
        params[set][word] = value; return;
    }
    if (config(offset)) { registers[offset] = value; refresh_interrupt(); return; }
    if (offset == 0x308) { registers[0x300] &= ~value; return; }
    if (offset == 0x30c || offset == 0x320) return;
    if (offset == 0x314) { registers[0x310] &= ~value; return; }
    if (offset == 0x31c) { registers[0x318] &= ~value; return; }
    uint32_t global, mask = access_mask(offset, global);
    value &= mask;
    if (high_half(global)) return;
    switch (global) {
    case 0x1008: registers[0x1000] &= ~value; break;
    case 0x1010:
        manual |= value; work_pending = true;
        break;
    case 0x1028: registers[0x1020] &= ~value; break;
    case 0x1030:
        registers[0x1020] |= value; work_pending = true;
        break;
    case 0x1040: registers[0x1038] &= ~value; break;
    case 0x1058: registers[0x1050] &= ~value; break;
    case 0x1060: registers[0x1050] |= value; break;
    case 0x1070: registers[0x1068] &= ~value; break;
    case 0x1078: refresh_interrupt(value & 1); break;
    case 0x1088: registers[0x1084] &= ~(value & 255); break;
    case 0x108c: registers[0x1084] |= value & 255; break;
    case 0x1094: registers[0x1090] &= ~(value & 255); break;
    default: throw unknown(offset);
    }
    refresh_interrupt();
}
