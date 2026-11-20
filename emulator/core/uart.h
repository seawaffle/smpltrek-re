#ifndef SMPLTREK_EMULATOR_UART_H
#define SMPLTREK_EMULATOR_UART_H
#include <array>
#include <cstdint>
#include <deque>
#include <functional>
#include <optional>

class Uart {
    std::array<uint32_t, 14> regs{};
    std::deque<uint8_t> rx, tx;
    std::optional<uint8_t> shifting;
    uint64_t deadline = UINT64_MAX;
    uint32_t line_errors = 0;
    bool interrupt_high = false, thre_pending = true;
    uint32_t cause() const;
    void refresh();
    void start(uint64_t cycle);
public:
    std::function<bool()> pins_ready;
    std::function<bool()> clock_running;
    std::function<void()> interrupt;
    std::function<void(uint8_t, uint64_t)> transmitted;
    void reset();
    void advance(uint64_t cycle);
    void receive(uint8_t value);
    uint32_t read(uint32_t offset, uint64_t cycle);
    void write(uint32_t offset, uint32_t value, uint64_t cycle);
    uint64_t next_event() const { return deadline; }
    // Cycles one character takes at the programmed divisor and format; 0 before a divisor is set.
    uint64_t character_cycles() const {
        uint32_t divisor = (regs[8] & 255) | ((regs[9] & 255) << 8), lcr = regs[3];
        return uint64_t(1 + 5 + (lcr & 3) + (lcr & 8 ? 1 : 0) + (lcr & 4 ? 2 : 1)) * (regs[13] ? 13 : 16) * divisor * 2;
    }
};
#endif
