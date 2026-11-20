#include "mcasp.h"
#include <stdexcept>
#include <utility>

namespace {
bool control(uint32_t offset) {
    return offset == 0x10 || offset == 0x14 || offset == 0x44 || offset == 0x48 || offset == 0x4c || offset == 0x50 ||
        (offset >= 0x60 && offset <= 0x8c && !(offset & 3)) ||
        (offset >= 0xa0 && offset <= 0xcc && !(offset & 3)) ||
        (offset >= 0x180 && offset < 0x1c0 && !(offset & 3));
}
constexpr uint64_t SLOT_CYCLES = 3875, FRAME_CYCLES = 7750;
}
void Mcasp::reset() {
    regs = {}; tx.reset(); rx.reset(); tx_due = rx_due = UINT64_MAX;
    tx_slot = rx_slot = 0; tx_notified = rx_notified = irq = tx_failed = false;
    transmitted = received = underruns = overruns = 0; output.clear();
    input.clear(); input_position = 0; input_loop = false;
    input_words = padding_words = nonzero_input_words = 0;
}
void Mcasp::load_input(const uint8_t *data, uint32_t size, bool loop) {
    if (received) throw std::runtime_error("audio input must be configured before the first received slot");
    if (!data || !size || size % 8 || size > 64 * 1024 * 1024)
        throw std::runtime_error("audio input requires complete 32-bit slot pairs, up to 64 MiB");
    std::vector<uint32_t> words(size / 4);
    for (uint32_t i = 0; i < words.size(); i++)
        for (unsigned byte = 0; byte < 4; byte++) words[i] |= uint32_t(data[i * 4 + byte]) << (byte * 8);
    input = std::move(words); input_position = 0; input_loop = loop;
    input_words = padding_words = nonzero_input_words = 0;
}
void Mcasp::input_stats(uint64_t *fields) const {
    fields[0] = input.size(); fields[1] = input_position; fields[2] = input_loop;
    fields[3] = input_words; fields[4] = padding_words; fields[5] = nonzero_input_words;
}
uint32_t Mcasp::status(bool receive) const {
    uint32_t value = regs[(receive ? 0x80 : 0xc0) / 4] & ~0x108u;
    if (value & 0x87) value |= 0x100;
    return value | (regs[(receive ? 0x84 : 0xc4) / 4] & 1) * 8;
}
void Mcasp::notify() {
    bool transmit_ready = regs[0xc0 / 4] & 32, receive_ready = regs[0x80 / 4] & 32;
    if (transmit_ready && !tx_notified) { tx_notified = true; dma_request(false); }
    if (receive_ready && !rx_notified) { rx_notified = true; dma_request(true); }
    // DMA error and start-of-frame use different bit positions in STAT and INTCTL.
    auto pending = [](uint32_t flags) { return (flags & 0x37) | ((flags & 0x80) >> 4) | ((flags & 0x40) << 1); };
    bool active_irq = (pending(status(false)) & regs[0xbc / 4]) || (pending(status(true)) & regs[0x7c / 4]);
    if (active_irq && !irq) interrupt();
    irq = active_irq;
}
void Mcasp::validate(bool receive) const {
    uint32_t side = receive ? 0x60 : 0xa0;
    if (regs[(side + 4) / 4] != 0xffffffff || regs[(side + 8) / 4] != 0x180f0 ||
        regs[(side + 12) / 4] != 0x110 || regs[(side + 24) / 4] != 3 ||
        regs[0xb0 / 4] != 0x80 || regs[0xb4 / 4] || regs[0x70 / 4] || regs[0x74 / 4])
        throw std::runtime_error("McASP supports only synchronous external-clock two-slot 32-bit I2S format");
    if (regs[0x10 / 4] & 0x14006000 || (regs[0x14 / 4] & 0x14006000) != 0x2000)
        throw std::runtime_error("McASP I2S pin function/direction is not configured");
    for (unsigned serializer = 0; serializer < 16; serializer++) {
        uint32_t expected = serializer == 13 ? 1 : serializer == 14 ? 2 : 0;
        if ((regs[0x180 / 4 + serializer] & 3) != expected)
            throw std::runtime_error("McASP profile requires AXR13 transmit and AXR14 receive");
    }
}
void Mcasp::advance(uint64_t cycle) {
    uint32_t global = regs[0x44 / 4];
    if (!(global & 0x1e1e)) { tx_due = rx_due = UINT64_MAX; return; }
    bool clock = clocks_ready();
    bool tx_run = (global & 0x1e00) == 0x1e00 && clock && pins_ready(false);
    bool rx_run = (global & 0x1e) == 0x1e && clock && pins_ready(true);
    if (!tx_run) tx_due = UINT64_MAX;
    else if (tx_due == UINT64_MAX) { validate(false); tx_slot = 0; tx_due = (cycle / FRAME_CYCLES + 1) * FRAME_CYCLES + SLOT_CYCLES; }
    if (!rx_run) rx_due = UINT64_MAX;
    else if (rx_due == UINT64_MAX) { validate(true); rx_slot = 0; rx_due = (cycle / FRAME_CYCLES + 1) * FRAME_CYCLES + SLOT_CYCLES; }
    while (tx_due <= cycle) {
        if (!tx) { underruns++; regs[0xc0 / 4] |= 1; tx_failed = true; }
        uint32_t value = tx_failed ? 0 : *tx;
        output.push_back({tx_due, tx_slot, value});
        if (output.size() > 65536) output.pop_front();
        transmitted++; tx.reset(); tx_notified = false;
        regs[0xc4 / 4] = tx_slot;
        regs[0xc0 / 4] |= 32 | (tx_slot ? 16 : 64);
        tx_slot ^= 1; tx_due += SLOT_CYCLES;
    }
    while (rx_due <= cycle) {
        if (rx) { overruns++; regs[0x80 / 4] |= 1; }
        uint32_t value = 0;
        if (input_position < input.size()) {
            value = input[input_position++]; input_words++;
            if (input_loop && input_position == input.size()) input_position = 0;
        } else padding_words++;
        if (value) nonzero_input_words++;
        rx = value; received++; rx_notified = false;
        regs[0x84 / 4] = rx_slot;
        regs[0x80 / 4] |= 32 | (rx_slot ? 16 : 64);
        rx_slot ^= 1; rx_due += SLOT_CYCLES;
    }
    notify();
}
uint32_t Mcasp::read(uint32_t offset, uint32_t size, uint64_t cycle) {
    if (size != 4 || offset & 3) throw std::runtime_error("McASP requires aligned 32-bit register accesses");
    advance(cycle);
    if (offset == 0x2000 || offset == 0x2b8) {
        if (!rx) throw std::runtime_error("McASP receive buffer is empty");
        uint32_t value = *rx; rx.reset(); regs[0x80 / 4] &= ~32u; rx_notified = false; notify(); return value;
    }
    if (!control(offset)) throw std::runtime_error("unimplemented McASP register read");
    if (offset == 0x44 || offset == 0x60 || offset == 0xa0) return regs[0x44 / 4];
    if (offset == 0x80 || offset == 0xc0) return status(offset == 0x80);
    if (offset == 0x1b4) return regs[offset / 4] | ((regs[0xc0 / 4] & 32) ? 16 : 0);
    if (offset == 0x1b8) return regs[offset / 4] | (rx ? 32 : 0);
    return regs[offset / 4];
}
void Mcasp::write(uint32_t offset, uint32_t value, uint32_t size, uint64_t cycle) {
    if (size != 4 || offset & 3) throw std::runtime_error("McASP requires aligned 32-bit register accesses");
    advance(cycle);
    if (offset == 0x2000 || offset == 0x234) {
        if (!(regs[0x44 / 4] & 0x400)) throw std::runtime_error("McASP transmit serializer is held in reset");
        if (tx) { regs[0xc0 / 4] |= 0x80; notify(); return; }
        tx = value; regs[0xc0 / 4] &= ~32u; tx_notified = false; notify(); return;
    }
    if (!control(offset)) throw std::runtime_error("unimplemented McASP register write");
    if ((offset == 0x48 || offset == 0x4c || offset == 0x50 || offset == 0x8c || offset == 0xcc) && value)
        throw std::runtime_error("McASP mute, loopback, DIT or event control mode is not implemented");
    if (offset == 0x80 || offset == 0xc0) { regs[offset / 4] &= ~(value & 0xf7); notify(); return; }
    if (offset == 0x84 || offset == 0xc4) throw std::runtime_error("McASP slot register is read-only");
    if (offset == 0x44 || offset == 0x60 || offset == 0xa0) {
        uint32_t mask = offset == 0x60 ? 31 : offset == 0xa0 ? 0x1f00 : 0x1f1f;
        uint32_t old = regs[0x44 / 4], next = (old & ~mask) | (value & mask);
        // External clocks are required to synchronize reset release. Preserve requested clears.
        if (!clocks_ready()) next &= old;
        regs[0x44 / 4] = next;
        if (!(next & 0x400)) { tx.reset(); regs[0xc0 / 4] = 0; tx_notified = tx_failed = false; }
        else if (!(old & 0x400)) { regs[0xc0 / 4] |= 32; tx_notified = false; }
        if (!(next & 4)) { rx.reset(); regs[0x80 / 4] = 0; rx_notified = false; }
    } else regs[offset / 4] = value;
    advance(cycle);
}
