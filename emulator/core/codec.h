#ifndef SMPLTREK_EMULATOR_CODEC_H
#define SMPLTREK_EMULATOR_CODEC_H
#include <array>
#include <cstdint>
#include <deque>

struct CodecWrite { uint64_t cycle; uint32_t page, reg, value, read; }; // read: a register read over I2C
// AIC3106-compatible control-plane subset. No ADC/DAC/audio processing yet.
class Codec {
    std::array<std::array<uint8_t, 128>, 2> regs{};
    uint8_t page = 0, pointer = 0;
    bool expect_pointer = true;
    uint8_t mask(unsigned bank, unsigned reg) const;
    void reset_registers();
public:
    uint64_t writes = 0, resets = 0;
    static constexpr size_t TRACE = 65536;
    std::deque<CodecWrite> trace;    // the latest TRACE writes and reads, oldest first
    uint64_t logged = 0;             // rows ever added to trace: row i of trace is number logged - size + i
    uint8_t receive(uint64_t cycle);
    void reset();
    void start(bool read) { expect_pointer = !read; }
    bool send(uint8_t value, uint64_t cycle);
    uint32_t current_page() const { return page; }
    uint8_t inspect(unsigned bank, unsigned reg) const;
};
#endif
