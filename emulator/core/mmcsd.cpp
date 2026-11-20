#include "mmcsd.h"
#include <algorithm>
#include <stdexcept>

namespace {
constexpr uint32_t DXRDY = 0x200, DRRDY = 0x400, RSPDNE = 4, TOUTRS = 16;
uint32_t response_crc(uint32_t index, uint32_t response) {
    uint64_t bits = (uint64_t(index) << 32) | response;
    uint32_t crc = 0;
    for (int bit = 39; bit >= 0; bit--) {
        bool feedback = ((crc >> 6) ^ (bits >> bit)) & 1;
        crc = (crc << 1) & 127;
        if (feedback) crc ^= 9;
    }
    return crc * 2 + 1;
}
uint32_t mask_for(uint32_t offset) {
    switch (offset) {
    case 0: return 0x6c7;
    case 4: return 0x3ff;
    case 0x10: return 0x1eff;
    case 0x14: return 0x3ffff;
    case 0x18: return 0xffff;
    case 0x1c: return 0xfff;
    case 0x20: return 0xffff;
    case 0x2c: return 0xffffffff;
    case 0x30: return 0x1ffbf;
    case 0x34: case 0x38: case 0x3c: case 0x40: case 0x44: return 0xffffffff;
    case 0x64: case 0x6c: return 0; // SDIO disabled; nonzero configuration is unsupported.
    case 0x74: return 31;
    default: throw std::runtime_error("unimplemented MMCSD register write");
    }
}
}

void MmcSd::reset() {
    regs.fill(0); regs[1] = 255; regs[2] = DXRDY;
    regs[0x1c / 4] = 512; regs[0x24 / 4] = 65535;
    last_cycle = fraction = clocks_left = 0;
    pending = no_timeout = irq = false;
    data_active = data_crc = false; data_position = 0; fifo.clear(); reply = {}; card = {};
    dma_enabled = false; dma_remaining = 0;
}
void MmcSd::notify() {
    bool active = regs[2] & regs[4];
    if (active && !irq) interrupt();
    irq = active;
}
void MmcSd::advance(uint64_t cycle) {
    uint64_t elapsed = cycle >= last_cycle ? cycle - last_cycle : 0;
    last_cycle = cycle;
    if ((!pending && !data_active) || (regs[0] & 2) || !(regs[1] & 0x100) || !clock_running()) return;
    // Profile: 372 MHz DSP, 186 MHz function clock. DIV4 doubles the divider.
    uint64_t period = 4 * ((regs[1] & 255) + 1) * ((regs[1] & 0x200) ? 2 : 1);
    uint64_t elapsed_clocks = (elapsed + fraction) / period;
    fraction = (elapsed + fraction) % period;
    while (clocks_left && elapsed_clocks >= clocks_left) {
        elapsed_clocks -= clocks_left; clocks_left = 0;
        if (pending) {
            if (no_timeout) return;
            complete_command();
        } else data_clock();
    }
    if (clocks_left) clocks_left -= elapsed_clocks;
    else fraction = 0;
}
uint64_t MmcSd::next_event() const {
    if ((!pending && !data_active) || no_timeout || !clocks_left || (regs[0] & 2) || !(regs[1] & 0x100) || !clock_running()) return UINT64_MAX;
    uint64_t period = 4 * ((regs[1] & 255) + 1) * ((regs[1] & 0x200) ? 2 : 1);
    uint64_t clocks = clocks_left;
    if (data_active && !pending && !data_crc && !reply.write && !(regs[0x74 / 4] & 2)) {
        // Received bytes that change nothing but the FIFO's contents need no event of their own: advance
        // clocks them in whenever it is next called, which every register and DMA access does first. Such a
        // byte ends no block, and leaves DRRDY as it is: the FIFO stays under its threshold, or the flag is
        // already set. The event is the first byte that is not one of these, or the one that fills the FIFO.
        uint64_t each = 8 / ((regs[0] & 4) ? 4 : 1);
        size_t threshold = regs[0x74 / 4] & 4 ? 64 : 32, held = fifo.size();
        uint32_t position = data_position, block = regs[0x1c / 4];
        bool flagged = regs[2] & DRRDY;
        while (held + 1 < 64 && (position + 1) % block && (flagged ? held >= threshold : held + 1 < threshold)) {
            held++; position++; clocks += each;
        }
    }
    return last_cycle + clocks * period - fraction;
}
void MmcSd::ready() {
    unsigned threshold = regs[0x74 / 4] & 4 ? 64 : 32;
    bool receive = !(regs[0x74 / 4] & 2), request = false;
    if (regs[0x74 / 4] & 2) {
        regs[2] &= ~DRRDY;
        if (fifo.size() + threshold <= 64) regs[2] |= DXRDY; else regs[2] &= ~DXRDY;
        request = fifo.size() + threshold <= 64 && reply.write && data_position + fifo.size() < reply.data.size();
    } else {
        regs[2] &= ~(DXRDY | DRRDY);
        if (fifo.size() >= threshold || (!reply.data.empty() && data_position == reply.data.size() && !fifo.empty()))
            regs[2] |= DRRDY;
        request = regs[2] & DRRDY;
    }
    if (dma_enabled && !dma_remaining && request) {
        dma_remaining = receive ? std::min(size_t(threshold), fifo.size())
                                : std::min(size_t(threshold), reply.data.size() - data_position - fifo.size());
        dma_request(receive);
    }
    notify();
}
void MmcSd::resume_data() {
    if (!data_active || data_crc || clocks_left) return;
    if (reply.write ? !fifo.empty() : fifo.size() < 64)
        clocks_left = 8 / ((regs[0] & 4) ? 4 : 1);
}
void MmcSd::complete_command() {
    pending = false; fraction = 0;
    uint32_t command = regs[0x30 / 4];
    if ((command & 0x600) && !reply.responds) { regs[2] |= TOUTRS; notify(); return; }
    regs[2] |= RSPDNE;
    if (reply.responds) {
        uint32_t index = reply.long_response || (command & 0x600) == 0x600 ? 63 : (command & 63);
        regs[0x50 / 4] = index;
        if (reply.long_response) for (unsigned i = 0; i < 4; i++) regs[0x38 / 4 + i] = reply.words[i];
        else {
            regs[0x44 / 4] = reply.words[0];
            uint32_t tail = (command & 0x600) == 0x600 ? 255 : response_crc(index, reply.words[0]);
            regs[0x40 / 4] = (regs[0x40 / 4] & ~0x00ff0000u) | (tail << 16);
        }
        if (command & 0x100) regs[2] |= 2; // functional R1b: card is already ready
    }
    if (!reply.data.empty()) {
        if (!(command & 0x2000) || bool(command & 0x800) != reply.write)
            throw std::runtime_error("MMCSD command data direction does not match SD command");
        uint32_t length = regs[0x1c / 4] & 0xfff, blocks = regs[0x20 / 4];
        if (!length || !blocks || uint64_t(length) * blocks != reply.data.size() ||
            (reply.multiple ? length != 512 : blocks != 1))
            throw std::runtime_error("MMCSD block length/count does not match card transfer");
        if (bool(regs[0x74 / 4] & 2) != reply.write)
            throw std::runtime_error("MMCSD FIFO direction does not match SD command");
        if (((regs[0] & 4) ? 4u : 1u) != card.width)
            throw std::runtime_error("MMCSD and card bus widths do not match");
        data_active = true; data_crc = false; data_position = 0;
        regs[0x24 / 4] = blocks; ready(); resume_data();
    }
    notify();
}
void MmcSd::data_clock() {
    if (data_crc) {
        uint32_t block = regs[0x1c / 4];
        card.finish(reply, data_position - block, block); data_crc = false;
        if (data_position == reply.data.size()) {
            data_active = false;
            regs[2] |= 1; // DATDNE follows the final CRC check and functional programming interval.
        } else resume_data();
        if (reply.write) regs[0x48 / 4] = 5;
        notify(); return;
    }
    if (reply.write) { reply.data[data_position++] = fifo.front(); fifo.pop_front(); }
    else fifo.push_back(reply.data[data_position++]);
    if (data_position % regs[0x1c / 4] == 0) {
        if (data_position == reply.data.size()) regs[2] |= 0x1000;
        regs[0x24 / 4]--; data_crc = true;
        if (reply.write) card.state = 7;
        clocks_left = 17 + (reply.write ? 32 : 0); // CRC/end and deterministic functional write busy
    }
    ready(); resume_data();
}
uint32_t MmcSd::read(uint32_t offset, uint32_t size, uint64_t cycle) {
    advance(cycle);
    uint32_t word = offset & ~3u, value;
    if (word > 0x74 || (offset & 3) + size > 4) throw std::runtime_error("unimplemented MMCSD register");
    if (word == 0xc) value = (fifo.empty() ? 0x24 : 0) | (fifo.size() == 64 ? 8 : 0) |
        (!(regs[1] & 0x100) || !clock_running() || (data_active && !clocks_left) ? 2 : 0) | (card.state == 7 ? 1 : 0);
    else if (word == 0x28) {
        if ((offset & 3) || size != 4 - ((regs[0x74 / 4] >> 3) & 3) || (regs[0x74 / 4] & 3) || fifo.size() < size)
            throw std::runtime_error("MMCSD receive FIFO empty or invalid access width/direction");
        value = 0;
        for (unsigned i = 0; i < size; i++) { value |= uint32_t(fifo.front()) << (i * 8); fifo.pop_front(); }
        dma_remaining -= std::min(dma_remaining, size);
        ready(); resume_data(); return value;
    } else if (word == 0x2c) throw std::runtime_error("MMCSD transmit FIFO is write-only");
    else {
        if (word != 8 && word != 0x24 && word != 0x48 && word != 0x50 && word != 0x68 && word != 0x70)
            (void)mask_for(word);
        value = regs[word / 4];
    }
    uint32_t shift = (offset & 3) * 8, mask = size == 4 ? 0xffffffff : ((1u << (size * 8)) - 1) << shift;
    // SPRUH79C 25.2.10.1: status reads clear every addressed flag, including
    // FIFO-ready flags. FIFO contents/readiness persist independently of this event latch.
    if (word == 8) { regs[2] &= ~mask; notify(); }
    return (value & mask) >> shift;
}
void MmcSd::write(uint32_t offset, uint32_t value, uint32_t size, uint64_t cycle) {
    advance(cycle);
    uint32_t word = offset & ~3u, allowed = mask_for(word);
    if (word == 0x2c) {
        if ((offset & 3) || size != 4 - ((regs[0x74 / 4] >> 3) & 3) || (regs[0x74 / 4] & 3) != 2 || fifo.size() + size > 64)
            throw std::runtime_error("MMCSD transmit FIFO full or invalid access width/direction");
        for (unsigned i = 0; i < size; i++) fifo.push_back(uint8_t(value >> (i * 8)));
        dma_remaining -= std::min(dma_remaining, size);
        ready(); resume_data(); return;
    }
    uint32_t shift = (offset & 3) * 8, mask = size == 4 ? 0xffffffff : ((1u << (size * 8)) - 1) << shift;
    if ((offset & 3) + size > 4) throw std::runtime_error("invalid MMCSD access width");
    value = (regs[word / 4] & ~mask) | ((value << shift) & mask);
    if (value & ~allowed) throw std::runtime_error("unsupported MMCSD register bits");
    if (word == 0 && (value & 0x6c0)) throw std::runtime_error("MMCSD endian/edge modes are not implemented");
    if (word == 0x30 && (value & 0x1000)) throw std::runtime_error("MMCSD stream mode is not implemented");
    if (word == 0x30 && (value & 0x10000) && !(value & 0x2000))
        throw std::runtime_error("MMCSD DMA trigger without a data command is not implemented");
    if (word == 0x30 && (offset & 3) < 2 && !(regs[0] & 2) && pending)
        throw std::runtime_error("MMCSD command issued while command engine is busy");
    if (word == 0x30 && data_active && (value & 63) != 12)
        throw std::runtime_error("MMCSD command during active data transfer is not implemented");
    if (word == 0x30 && data_active && data_crc)
        throw std::runtime_error("MMCSD stop during CRC/programming is not implemented");
    if (word == 0x74 && data_active) throw std::runtime_error("MMCSD FIFO reconfiguration during transfer is not implemented");
    regs[word / 4] = value;
    if (word == 0) {
        if (value & 1) { data_active = dma_enabled = false; dma_remaining = 0; fifo.clear(); regs[2] = (regs[2] & ~DRRDY) | DXRDY; if (!pending) clocks_left = 0; }
        if (value & 2) { pending = false; regs[2] &= ~(RSPDNE | TOUTRS); }
    }
    if (word == 0x74 && (value & 1)) { fifo.clear(); dma_enabled = false; dma_remaining = 0; regs[2] = (regs[2] & ~DRRDY) | DXRDY; }
    if (word == 0x30 && (offset & 3) < 2 && !(regs[0] & 2)) {
        if ((value & 63) == 12) { data_active = false; fifo.clear(); }
        if (value & 0x8000) regs[2] = (regs[2] & ~DRRDY) | DXRDY;
        reply = pins_ready() ? card.command(value & 63, regs[0x34 / 4], cycle) : SdReply{};
        if (reply.multiple) card.prepare_blocks(reply, regs[0x20 / 4]);
        data_position = 0;
        if (reply.responds && (((value & 0x600) == 0x400) != reply.long_response || !(value & 0x600)))
            throw std::runtime_error("MMCSD response format does not match card response");
        clocks_left = 48 + ((value & 0x4000) ? 80 : 0);
        no_timeout = (value & 0x600) && !reply.responds && !(regs[0x14 / 4] & 255);
        if (value & 0x600) clocks_left += reply.responds ? (reply.long_response ? 144 : 56) : (regs[0x14 / 4] & 255);
        fraction = 0; pending = true;
        dma_enabled = value & 0x10000; dma_remaining = 0;
        regs[word / 4] &= ~0x10000u; // DMATRIG reads as zero (SPRUH79C Table 25-18).
        if (dma_enabled) ready(); // transmit DMA can prefill before the command response completes
    }
    notify();
}
