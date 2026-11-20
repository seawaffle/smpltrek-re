#ifndef SMPLTREK_EMULATOR_USB_H
#define SMPLTREK_EMULATOR_USB_H
#include <array>
#include <cstdint>
#include <functional>

// C6748 USB0 wrapper and MUSB control plane with an explicitly disconnected peer.
// Enumeration, FIFO traffic and host/OTG operation are deliberately unsupported. The CPPI 4.1
// DMA set-up registers a peripheral driver programs before any transfer (endpoint modes, channel
// configuration, scheduler, queue-manager RAM and memory regions) hold their values; with no
// host there is no traffic, so no descriptor is ever queued and queue accesses stay unsupported.
class Usb {
    uint32_t control = 0, source = 0, mask = 0, phy_control = 0;
    uint16_t tx_enable = 1, rx_enable = 0;
    uint8_t address = 0, power = 0, usb_enable = 0, index = 0;
    bool in_service = false;
    uint32_t mode = 0, scheduler = 0, link_size = 0;
    std::array<uint32_t, 4> rndis_size{}, tx_channel{}, rx_channel{}, rx_queues_a{}, rx_queues_b{};
    std::array<uint32_t, 64> schedule{};
    std::array<uint32_t, 2> link_base{};
    std::array<uint32_t, 16> region_base{}, region_control{};
    uint32_t *setup_register(uint32_t offset, uint32_t &writable, bool &readable);
    uint64_t reset_due = UINT64_MAX, phy_due = UINT64_MAX;
    void update_irq();
    uint8_t read_core(uint32_t offset) const;
    void write_core(uint32_t offset, uint8_t value);
public:
    bool phy_ready = false;
    uint64_t resets = 0, interrupts = 0;
    std::function<bool()> clock_running;
    std::function<void()> interrupt;
    void advance(uint64_t cycle);
    uint64_t next_event() const;
    void configure_phy(uint32_t value, uint64_t cycle);
    uint32_t phy_value(uint64_t cycle);
    uint32_t read(uint32_t offset, uint32_t size, uint64_t cycle);
    void write(uint32_t offset, uint32_t value, uint32_t size, uint64_t cycle);
    uint32_t soft_connect() const { return (power >> 6) & 1; }
    uint32_t interrupt_mask() const { return mask; }
    uint32_t interrupt_source() const { return source; }
};
#endif
