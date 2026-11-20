#ifndef SMPLTREK_EMULATOR_MMCSD_H
#define SMPLTREK_EMULATOR_MMCSD_H
#include <array>
#include <cstdint>
#include <functional>
#include <deque>
#include "sdcard.h"

// C6748 MMCSD0, initially with an empty socket. SPRUH79C chapter 25.
class MmcSd {
    std::array<uint32_t, 30> regs{};
    uint64_t last_cycle = 0, fraction = 0, clocks_left = 0;
    bool pending = false, no_timeout = false, irq = false;
    bool data_active = false, data_crc = false;
    bool dma_enabled = false;
    uint32_t dma_remaining = 0;
    uint32_t data_position = 0;
    std::deque<uint8_t> fifo;
    SdReply reply;
    void notify();
    void ready();
    void resume_data();
    void complete_command();
    void data_clock();
public:
    SdCard card;
    std::function<bool()> clock_running;
    std::function<bool()> pins_ready;
    std::function<void(bool)> dma_request;
    std::function<void()> interrupt;
    void reset();
    void advance(uint64_t cycle);
    uint32_t read(uint32_t offset, uint32_t size, uint64_t cycle);
    void write(uint32_t offset, uint32_t value, uint32_t size, uint64_t cycle);
    uint64_t next_event() const;
};
#endif
