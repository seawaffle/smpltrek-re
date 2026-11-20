#include "spi.h"
#include <stdexcept>

void Spi::reset() {
    regs.fill(0); regs[0x4c / 4] = 255;
    shifting.reset(); queued.reset(); received.clear(); deadline = UINT64_MAX; errors = 0;
    tx_notified = rx_notified = false;
}
void Spi::notify_dma() {
    if (!(regs[0x08 / 4] & 0x10000)) { tx_notified = rx_notified = false; return; }
    if (!queued && !tx_notified) { tx_notified = true; dma_request(false); }
    if (!received.empty() && !rx_notified) { rx_notified = true; dma_request(true); }
}
void Spi::start(uint64_t cycle) {
    if (!shifting || deadline != UINT64_MAX) return;
    uint32_t gcr = regs[1], word = *shifting;
    if (!(regs[0] & 1) || (gcr & 0x01000103) != 0x01000003 ||
        (!(gcr & 0x10000) && !pins_ready(word))) return;
    uint32_t format = regs[0x50 / 4 + ((word >> 24) & 3)], bits = format & 31;
    if (bits < 2 || bits > 16) throw std::runtime_error("SPI character length must be 2..16");
    if (format & 0x007c0000) throw std::runtime_error("SPI parity/wait/LSB-first modes are not implemented");
    deadline = cycle + uint64_t(bits) * (((format >> 8) & 255) + 1) * 2;
}
void Spi::advance(uint64_t cycle) {
    start(cycle);
    while (shifting && deadline <= cycle) {
        uint64_t completed = deadline;
        uint32_t word = *shifting, bits = regs[0x50 / 4 + ((word >> 24) & 3)] & 31;
        uint32_t reply = regs[1] & 0x10000 ? word : exchange(word, completed);
        reply &= (1u << bits) - 1;
        if (received.size() == 2) { received.back() = reply; errors |= 0x40; }
        else received.push_back(reply);
        if (!(word & 0x10000000)) deselect(completed);
        shifting = queued; queued.reset(); deadline = UINT64_MAX;
        start(completed);
        notify_dma();
    }
}
uint32_t Spi::read(uint32_t offset, uint32_t size, uint64_t cycle) {
    advance(cycle);
    uint32_t word = offset & ~3u, value = 0;
    if (word > 0x64 || word == 0x60 || (offset & 3) + size > 4) throw std::runtime_error("unimplemented SPI register");
    if (word == 0x40 || word == 0x44) {
        value = (received.empty() ? 0x80000000 : received.front()) | (queued ? 0x20000000 : 0) | (errors & 0x40 ? 0x40000000 : 0);
        if (word == 0x40 && (offset & 3) < 2 && !received.empty()) { received.pop_front(); rx_notified = false; notify_dma(); }
    } else if (word == 0x10) value = errors | (!queued ? 0x200 : 0) | (!received.empty() ? 0x100 : 0);
    else if (word == 0x64) throw std::runtime_error("SPI interrupt vector is not implemented");
    else if (word == 0x24 || word == 0x28) value = regs[0x20 / 4];
    else value = regs[word / 4];
    value >>= (offset & 3) * 8;
    return size == 4 ? value : value & ((1u << (size * 8)) - 1);
}
void Spi::write(uint32_t offset, uint32_t value, uint32_t size, uint64_t cycle) {
    advance(cycle);
    uint32_t word = offset & ~3u;
    if (word > 0x5c || word == 0x40 || word == 0x44 || (offset & 3) + size > 4) throw std::runtime_error("unimplemented SPI register write");
    uint32_t shift = (offset & 3) * 8, mask = size == 4 ? 0xffffffff : ((1u << (size * 8)) - 1) << shift;
    value = (regs[word / 4] & ~mask) | ((value << shift) & mask);
    if (word == 0) {
        if (!(value & 1)) { deselect(cycle); reset(); }
        else regs[0] = 1;
        return;
    }
    if (word == 0x10) {
        errors &= ~value;
        if (value & 0x100 && !received.empty()) received.pop_front();
        return;
    }
    if (word == 0x24) regs[0x20 / 4] |= value;
    else if (word == 0x28) regs[0x20 / 4] &= ~value;
    else regs[word / 4] = value;
    if ((word == 0x38 || word == 0x3c) && (offset & 3) < 2) {
        if (!(regs[1] & 0x01000000)) return;
        uint32_t data = word == 0x38 ? (regs[0x3c / 4] & 0xffff0000) | (value & 0xffff) : value;
        if (!shifting) shifting = data;
        else if (!queued) queued = data;
        else throw std::runtime_error("SPI transmit buffer overflow");
        tx_notified = false;
    }
    if (word == 0x3c && !(value & 0x10000000) && !shifting) deselect(cycle);
    start(cycle);
    notify_dma();
}
