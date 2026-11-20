#ifndef SMPLTREK_EMULATOR_OLED_H
#define SMPLTREK_EMULATOR_OLED_H
#include <array>
#include <cstdint>
#include <stdexcept>

// Protocol profile for the documented stock B3/81/A0/AF initialization and raw frame stream.
// Controller identity and additional command dialects remain unverified.
class Oled {
    uint32_t waiting = 0;
public:
    std::array<uint8_t, 8192> ram{};
    uint64_t bytes = 0;
    uint64_t first_frame_cycle = 0;
    uint32_t on = 0, contrast = 0x7f, remap = 0, clock = 0, cursor = 0;
    void send(uint8_t value, bool data, uint64_t cycle) {
        if (data) {
            ram[cursor++ % ram.size()] = value;
            if (++bytes == ram.size()) first_frame_cycle = cycle;
            return;
        }
        if (waiting) {
            if (waiting == 0x81) contrast = value;
            else if (waiting == 0xa0) remap = value;
            else if (waiting == 0xb3) clock = value;
            waiting = 0; return;
        }
        if (value == 0x81 || value == 0xa0 || value == 0xb3) waiting = value;
        else if (value == 0xae || value == 0xaf) on = value & 1;
        else throw std::runtime_error("unimplemented OLED command " + std::to_string(value));
    }
};
#endif
