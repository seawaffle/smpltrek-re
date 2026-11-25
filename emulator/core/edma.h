#ifndef SMPLTREK_EMULATOR_EDMA_H
#define SMPLTREK_EMULATOR_EDMA_H
#include <array>
#include <cstdint>
#include <unordered_map>
#include <functional>

// C6748 CC0 configuration and A/AB-synchronized increment-address transfers.
class Edma {
    std::unordered_map<uint32_t, uint32_t> registers{{0x620, 0x1010}}; // QWMTHRA resets to 0x1010 (SPRUH79C 16.4)
    std::array<std::array<uint32_t, 8>, 128> params{};
    uint32_t manual = 0;
    bool irq_high = false;
    bool work_pending = false;
    uint32_t access_mask(uint32_t offset, uint32_t &global);
    void refresh_interrupt(bool force = false);
    void transfer(unsigned channel);
public:
    std::function<void(uint32_t, uint32_t, uint32_t)> copy;
    std::function<void()> interrupt;
    uint32_t read(uint32_t offset);
    void write(uint32_t offset, uint32_t value);
    void event(unsigned channel);
    void service();
};
#endif
