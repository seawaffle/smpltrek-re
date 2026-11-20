#ifndef SMPLTREK_EMULATOR_MCASP_H
#define SMPLTREK_EMULATOR_MCASP_H
#include <array>
#include <cstdint>
#include <deque>
#include <functional>
#include <optional>
#include <vector>

struct AudioWord { uint64_t cycle; uint32_t slot, value; };
// Functional external-clock 48 kHz / two 32-bit slots, AXR13 TX and AXR14 RX.
class Mcasp {
    std::array<uint32_t, 192> regs{};
    std::optional<uint32_t> tx, rx;
    uint64_t tx_due = UINT64_MAX, rx_due = UINT64_MAX;
    uint32_t tx_slot = 0, rx_slot = 0;
    bool tx_notified = false, rx_notified = false, irq = false;
    bool tx_failed = false;
    std::vector<uint32_t> input;
    uint64_t input_words = 0, padding_words = 0, nonzero_input_words = 0;
    uint32_t input_position = 0;
    bool input_loop = false;
    void notify();
    void validate(bool receive) const;
    uint32_t status(bool receive) const;
public:
    std::function<bool()> clocks_ready;
    std::function<bool(bool)> pins_ready;
    std::function<void(bool)> dma_request;
    std::function<void()> interrupt;
    uint64_t transmitted = 0, received = 0, underruns = 0, overruns = 0;
    std::deque<AudioWord> output;
    void reset();
    // Raw little-endian slot pairs at the digital ADC boundary; copied before RX starts.
    void load_input(const uint8_t *data, uint32_t size, bool loop);
    void input_stats(uint64_t *fields) const;
    void advance(uint64_t cycle);
    uint32_t read(uint32_t offset, uint32_t size, uint64_t cycle);
    void write(uint32_t offset, uint32_t value, uint32_t size, uint64_t cycle);
    uint64_t next_event() const { return tx_due < rx_due ? tx_due : rx_due; }
};
#endif
