#include "i2c.h"
#include <stdexcept>

namespace {
constexpr uint32_t AL = 1, NACK = 2, ARDY = 4, RRDY = 8, XRDY = 16, SCD = 32;
constexpr uint32_t BB = 0x1000, XSMT = 0x400, IRS = 0x20, STP = 0x800, MST = 0x400, STT = 0x2000;
uint32_t register_mask(uint32_t offset) {
    switch (offset) {
    case 0: case 0x1c: return 0x3ff;
    case 4: return 127;
    case 8: return 0x7fff;
    case 0xc: case 0x10: case 0x14: return 65535;
    case 0x18: case 0x20: case 0x30: return 255;
    case 0x24: return 0xefff;
    case 0x28: return 7;
    case 0x2c: return 3;
    case 0x34: case 0x38: return 0xffffffff;
    case 0x3c: return 3;
    default: throw std::runtime_error("unimplemented I2C register");
    }
}
}
void I2c::reset_logic() {
    regs[2] = XSMT | XRDY; phase = Idle; deadline2 = UINT64_MAX;
    remaining = notified = 0; active = false; tx.reset();
}
void I2c::reset() {
    regs.fill(0); regs[0x2c / 4] = 1; regs[0x34 / 4] = 0x4415; regs[0x38 / 4] = 6;
    starts = stops = bytes_sent = bytes_received = nacks = 0;
    reset_logic();
}
void I2c::notify() {
    uint32_t enabled = regs[0x24 / 4] & IRS ? regs[2] & regs[1] & 127 : 0;
    if (enabled & ~notified) interrupt();
    notified = enabled;
}
void I2c::schedule(Phase next, uint64_t cycle2, unsigned clocks) {
    uint32_t psc = regs[0x30 / 4], d = psc < 2 ? 7 - psc : 5;
    // 24 MHz input; one oscillator cycle is 31 half-DSP cycles at 372 MHz.
    uint64_t period2 = uint64_t(psc + 1) * (regs[3] + regs[4] + 2 * d) * 31;
    phase = next; deadline2 = cycle2 + clocks * period2;
}
void I2c::finish(uint64_t cycle2) {
    active = false;
    if (regs[0x24 / 4] & STP) schedule(Stop, cycle2, 1);
    else { regs[2] |= ARDY; phase = Idle; deadline2 = UINT64_MAX; }
}
void I2c::next_data(uint64_t cycle2) {
    if (!active) return;
    if (!remaining) { finish(cycle2); return; }
    if (receiver) {
        if (!(regs[2] & RRDY)) schedule(Receive, cycle2, 9);
    } else if (tx) {
        shifting = *tx; tx.reset(); regs[2] |= XRDY | XSMT;
        schedule(Transmit, cycle2, 9);
    } else { phase = Idle; deadline2 = UINT64_MAX; regs[2] &= ~XSMT; }
    notify();
}
void I2c::advance(uint64_t cycle) {
    while (deadline2 <= cycle * 2) {
        uint64_t at = deadline2, completed = (at + 1) / 2;
        auto previous = phase; phase = Idle; deadline2 = UINT64_MAX;
        if (previous == Address) {
            regs[0x24 / 4] &= ~STT;
            if (!start(regs[0x1c / 4] & 127, receiver, completed)) {
                regs[2] |= NACK | ARDY; nacks++; finish(at);
            } else next_data(at);
        } else if (previous == Transmit) {
            bytes_sent++;
            if (!send(shifting, completed)) { regs[2] |= NACK | ARDY; nacks++; finish(at); }
            else { remaining--; next_data(at); }
        } else if (previous == Receive) {
            regs[0x18 / 4] = receive(completed); regs[2] |= RRDY; bytes_received++;
            if (!--remaining) { regs[2] |= 0x2000; finish(at); } // final receive byte is NACKed
        } else if (previous == Stop) {
            stop(completed); stops++; regs[2] = (regs[2] & ~BB) | SCD;
            regs[0x24 / 4] &= ~(STT | STP | MST);
        }
        notify();
    }
}
uint32_t I2c::read(uint32_t offset, uint32_t size, uint64_t cycle) {
    advance(cycle);
    uint32_t word = offset & ~3u; (void)register_mask(word);
    uint32_t value = regs[word / 4];
    bool low = (offset & 3) == 0;
    if (word == 0x28) {
        uint32_t pending = regs[2] & regs[1] & 127; value = 0;
        for (unsigned bit = 0; bit < 7; bit++) if (pending & (1u << bit)) {
            value = bit + 1;
            if (low) regs[2] &= ~(1u << bit);
            if (low && (pending & ~(1u << bit))) interrupt();
            break;
        }
    }
    if (word == 0x18 && low) {
        regs[2] &= ~(RRDY | 0x800);
        if (active && receiver && phase == Idle) next_data(cycle * 2);
    }
    notify();
    value >>= (offset & 3) * 8;
    return size == 4 ? value : value & ((1u << (size * 8)) - 1);
}
void I2c::write(uint32_t offset, uint32_t value, uint32_t size, uint64_t cycle) {
    advance(cycle);
    uint32_t word = offset & ~3u, allowed = register_mask(word);
    uint32_t shift = (offset & 3) * 8, mask = size == 4 ? 0xffffffff : ((1u << (size * 8)) - 1) << shift;
    uint32_t incoming = (value << shift) & mask;
    value = (regs[word / 4] & ~mask) | incoming;
    if (word == 8) { regs[2] &= ~(incoming & (AL | NACK | ARDY | RRDY | XRDY | SCD | 0x3000 | 0x4000)); notify(); return; }
    if (word == 0x18 || word == 0x28 || word == 0x34 || word == 0x38)
        throw std::runtime_error("I2C register is read-only");
    value &= allowed;
    if (word == 0x24 && (value & 0x81df)) throw std::runtime_error("I2C non-8-bit, loopback, repeat, 10-bit, START-byte, free-data or early-NACK mode is not implemented");
    if (word == 0x2c && (value & 2)) throw std::runtime_error("I2C IGNACK mode is not implemented");
    if (word == 0x3c && value) throw std::runtime_error("I2C DMA is not implemented");
    if ((word == 0xc || word == 0x10 || word == 0x30) && (regs[0x24 / 4] & IRS)) return; // latched only in reset
    if (word == 0x20 && !(offset & 3)) {
        if (tx) throw std::runtime_error("I2C transmit register overflow");
        tx = uint8_t(value); regs[2] = (regs[2] & ~XRDY) | XSMT;
    }
    regs[word / 4] = value;
    if (word == 0x24) {
        if (!(value & IRS)) { reset_logic(); return; }
        if (value & STT) {
            if (!(value & MST)) throw std::runtime_error("I2C slave mode is not implemented");
            if (phase != Idle) throw std::runtime_error("I2C START while a byte is shifting is not implemented");
            remaining = regs[0x14 / 4] ? regs[0x14 / 4] : 65536;
            receiver = !(value & 0x200); active = true; starts++;
            regs[2] = (regs[2] & ~(ARDY | NACK | SCD)) | BB;
            schedule(Address, cycle * 2, 9);
        } else if ((value & STP) && (regs[2] & BB) && !active && phase == Idle) schedule(Stop, cycle * 2, 1);
    }
    if (word == 0x20 && active && !receiver && phase == Idle) next_data(cycle * 2);
    notify();
}
