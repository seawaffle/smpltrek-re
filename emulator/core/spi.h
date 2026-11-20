#ifndef SMPLTREK_EMULATOR_SPI_H
#define SMPLTREK_EMULATOR_SPI_H
#include <array>
#include <cstdint>
#include <deque>
#include <functional>
#include <optional>

class Spi {
    std::array<uint32_t, 26> regs{};
    std::optional<uint32_t> shifting, queued;
    std::deque<uint32_t> received;
    uint64_t deadline = UINT64_MAX;
    uint32_t errors = 0;
    bool tx_notified = false, rx_notified = false;
    void start(uint64_t cycle);
    void notify_dma();
public:
    // Set by Board; no host app callbacks are involved in guest transfers.
    std::function<bool(uint32_t)> pins_ready;
    std::function<uint32_t(uint32_t, uint64_t)> exchange;
    std::function<void(uint64_t)> deselect;
    std::function<void(bool)> dma_request;
    void reset();
    void advance(uint64_t cycle);
    uint32_t read(uint32_t offset, uint32_t size, uint64_t cycle);
    void write(uint32_t offset, uint32_t value, uint32_t size, uint64_t cycle);
    uint32_t control(uint32_t offset) const { return regs[offset / 4]; }
    uint64_t next_event() const { return deadline; }
};
#endif
