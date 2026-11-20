#include "uart.h"
#include <stdexcept>

void Uart::reset() {
    regs.fill(0); rx.clear(); tx.clear(); shifting.reset(); deadline = UINT64_MAX;
    line_errors = 0; interrupt_high = false; thre_pending = true;
}
uint32_t Uart::cause() const {
    static constexpr unsigned thresholds[] = {1, 4, 8, 14};
    if ((regs[1] & 4) && line_errors) return 6;
    unsigned trigger = regs[2] & 1 ? thresholds[regs[2] >> 6 & 3] : 1;
    if ((regs[1] & 1) && rx.size() >= trigger) return 4;
    if ((regs[1] & 2) && tx.empty() && thre_pending) return 2;
    return 1;
}
void Uart::refresh() {
    bool high = cause() != 1;
    if (high && !interrupt_high) interrupt();
    interrupt_high = high;
}
void Uart::start(uint64_t cycle) {
    if (shifting || tx.empty() || !clock_running() || !(regs[0x30 / 4] & 0x4000) || (!(regs[4] & 0x10) && !pins_ready())) return;
    uint32_t divisor = (regs[8] & 255) | ((regs[9] & 255) << 8);
    if (!divisor) return;
    uint32_t lcr = regs[3], bits = 1 + 5 + (lcr & 3) + (lcr & 8 ? 1 : 0) + (lcr & 4 ? 2 : 1);
    if (lcr & 0xe0) throw std::runtime_error("UART break/stick parity/DLAB mode is not implemented");
    if (regs[13] > 1) throw std::runtime_error("UART MDR mode is not implemented");
    shifting = tx.front(); tx.pop_front(); thre_pending = tx.empty();
    deadline = cycle + uint64_t(bits) * (regs[13] ? 13 : 16) * divisor * 2;
    refresh();
}
void Uart::advance(uint64_t cycle) {
    start(cycle);
    while (shifting && cycle >= deadline) {
        uint8_t byte = *shifting; uint64_t completed = deadline;
        shifting.reset(); deadline = UINT64_MAX;
        if (regs[4] & 0x10) receive(byte); else transmitted(byte, completed);
        start(completed);
    }
    refresh();
}
void Uart::receive(uint8_t value) {
    if (!(regs[12] & 0x2000)) return;
    if (rx.size() >= (regs[2] & 1 ? 16u : 1u)) line_errors |= 2;
    else rx.push_back(value);
    refresh();
}
uint32_t Uart::read(uint32_t offset, uint64_t cycle) {
    advance(cycle);
    switch (offset) {
    case 0: {
        uint32_t value = rx.empty() ? 0 : rx.front();
        if (!rx.empty()) rx.pop_front();
        refresh(); return value;
    }
    case 8: {
        uint32_t value = cause();
        if (value == 2) { thre_pending = false; refresh(); }
        return value | (regs[2] & 1 ? 0xc0 : 0);
    }
    case 0x14: {
        uint32_t value = line_errors | (!rx.empty() ? 1 : 0) | (tx.empty() ? 0x20 : 0) | (tx.empty() && !shifting ? 0x40 : 0);
        line_errors = 0; refresh(); return value;
    }
    case 0x18: return 0; // no modem peer attached
    case 4: case 0xc: case 0x10: case 0x1c: case 0x20: case 0x24: case 0x30: case 0x34: return regs[offset / 4];
    default: throw std::runtime_error("unimplemented UART register");
    }
}
void Uart::write(uint32_t offset, uint32_t value, uint64_t cycle) {
    advance(cycle);
    switch (offset) {
    case 0:
        if (!(regs[12] & 0x4000)) return;
        if (tx.size() >= (regs[2] & 1 ? 16u : 1u)) throw std::runtime_error("UART transmit FIFO overflow");
        tx.push_back(uint8_t(value)); thre_pending = false; break;
    case 4:
        if ((value & 2) && !(regs[1] & 2)) thre_pending = true;
        regs[1] = value & 15; break;
    case 8:
        if (value & 2) rx.clear();
        if (value & 4) { tx.clear(); thre_pending = true; }
        regs[2] = value & 0xc9; break;
    case 0x30:
        if (!(value & 0x2000)) { rx.clear(); line_errors = 0; }
        if (!(value & 0x4000)) { tx.clear(); shifting.reset(); deadline = UINT64_MAX; thre_pending = true; }
        regs[12] = value & 0x6001; break;
    case 0xc: case 0x10: case 0x1c: case 0x20: case 0x24: case 0x34: regs[offset / 4] = value & 255; break;
    default: throw std::runtime_error("unimplemented UART register write");
    }
    start(cycle); refresh();
}
