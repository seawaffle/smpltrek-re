#ifndef SMPLTREK_EMULATOR_I2C_H
#define SMPLTREK_EMULATOR_I2C_H
#include <array>
#include <cstdint>
#include <functional>
#include <optional>

// C6748 I2C master, 7-bit address, 8-bit nonrepeat transfers (SPRUH79C chapter 21).
class I2c {
    std::array<uint32_t, 16> regs{};
    enum Phase { Idle, Address, Transmit, Receive, Stop } phase = Idle;
    uint64_t deadline2 = UINT64_MAX;
    uint32_t remaining = 0, notified = 0;
    bool active = false, receiver = false;
    std::optional<uint8_t> tx;
    uint8_t shifting = 0;
    void notify();
    void schedule(Phase next, uint64_t cycle2, unsigned clocks);
    void next_data(uint64_t cycle2);
    void finish(uint64_t cycle2);
    void reset_logic();
public:
    std::function<bool(uint32_t, bool, uint64_t)> start;
    std::function<bool(uint8_t, uint64_t)> send;
    std::function<uint8_t(uint64_t)> receive;
    std::function<void(uint64_t)> stop;
    std::function<void()> interrupt;
    uint64_t starts = 0, stops = 0, bytes_sent = 0, bytes_received = 0, nacks = 0;
    void reset();
    void advance(uint64_t cycle);
    uint32_t read(uint32_t offset, uint32_t size, uint64_t cycle);
    void write(uint32_t offset, uint32_t value, uint32_t size, uint64_t cycle);
    uint64_t next_event() const { return deadline2 == UINT64_MAX ? UINT64_MAX : (deadline2 + 1) / 2; }
};
#endif
