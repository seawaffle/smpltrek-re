#include "usb.h"
#include <algorithm>
#include <cstdio>
#include <stdexcept>

namespace {
constexpr uint32_t IRQ_BITS = 0x01ff1e1f;
std::runtime_error unsupported(uint32_t offset) {
    char text[96]; std::snprintf(text, sizeof text, "unimplemented USB0 access at 0x%08x", 0x01e00000 + offset);
    return std::runtime_error(text);
}
}
void Usb::update_irq() {
    if (!in_service && (source & mask) && clock_running()) {
        in_service = true; interrupts++; interrupt();
    }
}
void Usb::advance(uint64_t cycle) {
    if (cycle >= reset_due) {
        control = source = mask = 0;
        tx_enable = 1; rx_enable = address = power = usb_enable = index = 0;
        in_service = false; reset_due = UINT64_MAX;
        mode = scheduler = link_size = 0;
        rndis_size = tx_channel = rx_channel = rx_queues_a = rx_queues_b = {};
        schedule = {}; link_base = {}; region_base = region_control = {};
    }
    if (cycle >= phy_due) { phy_ready = true; phy_due = UINT64_MAX; }
    update_irq();
}
uint64_t Usb::next_event() const { return std::min(reset_due, phy_due); }
void Usb::configure_phy(uint32_t value, uint64_t cycle) {
    advance(cycle);
    uint32_t previous = phy_control;
    value &= 0xffff; // CLKGood and VBUSSense are read-only PHY status.
    if (!(value & 0x8600) && (value & 15) &&
        ((value & 15) != 2 || !(value & 0x800) || (value & 0x6000)))
        throw std::runtime_error("USB0 disconnected PHY profile requires internal 24 MHz reference and no OTG override");
    phy_control = value;
    if ((phy_control & 0x8600) || !(phy_control & 15)) {
        phy_ready = false; phy_due = UINT64_MAX; return;
    }
    if ((previous & 0x80f) != (phy_control & 0x80f)) phy_ready = false;
    // Functional settling interval, not a measured PLL lock time.
    if (!phy_ready && phy_due == UINT64_MAX) phy_due = cycle + 64;
}
uint32_t Usb::phy_value(uint64_t cycle) {
    advance(cycle);
    return phy_control | (phy_ready ? 1u << 17 : 0);
}
// Set-up registers that only hold what the driver programs (SPRUH79C 33.4.5, 33.4.17-20,
// 33.4.69-74, 33.4.81-83, 33.4.86-87). `writable` is the mask of documented fields. Registers
// with write-only fields are not readable here: the manual gives no read value for them.
uint32_t *Usb::setup_register(uint32_t offset, uint32_t &writable, bool &readable) {
    readable = true;
    if (offset == 0x10) { writable = 0x33333333; return &mode; }
    if (offset >= 0x50 && offset < 0x60) { writable = 0x1ffff; return &rndis_size[(offset - 0x50) / 4]; }
    if (offset >= 0x1800 && offset < 0x1880) {
        uint32_t channel = (offset - 0x1800) / 0x20;
        readable = false;
        switch (offset & 0x1f) {
        case 0x00: writable = 0xc0003fff; return &tx_channel[channel];
        case 0x08: writable = 0xc1ffffff; return &rx_channel[channel];
        case 0x0c: writable = 0x3fff3fff; return &rx_queues_a[channel];
        case 0x10: writable = 0x3fff3fff; return &rx_queues_b[channel];
        default: return nullptr;
        }
    }
    if (offset == 0x2000) { writable = 0x800000ff; return &scheduler; }
    if (offset >= 0x2800 && offset < 0x2900) { readable = false; writable = 0x8f8f8f8f; return &schedule[(offset - 0x2800) / 4]; }
    if (offset == 0x4080 || offset == 0x4088) { writable = 0xffffffff; return &link_base[(offset - 0x4080) / 8]; }
    if (offset == 0x4084) { writable = 0x3fff; return &link_size; }
    if (offset >= 0x5000 && offset < 0x5100 && (offset & 0xf) < 8) {
        uint32_t region = (offset - 0x5000) / 16;
        if (offset & 4) { writable = 0x3fff0f07; return &region_control[region]; }
        writable = 0xffffffff; return &region_base[region];
    }
    return nullptr;
}
uint8_t Usb::read_core(uint32_t offset) const {
    switch (offset) {
    case 0x400: return address;
    case 0x401: return power;
    case 0x402: case 0x403: case 0x404: case 0x405: return 0; // No host endpoint traffic.
    case 0x406: return uint8_t(tx_enable);
    case 0x407: return uint8_t(tx_enable >> 8);
    case 0x408: return uint8_t(rx_enable);
    case 0x409: return uint8_t(rx_enable >> 8);
    case 0x40a: return 0; // No cable, reset, resume, suspend or SOF from a host.
    case 0x40b: return usb_enable;
    case 0x40c: case 0x40d: return 0; // Frame counter requires bus SOFs.
    case 0x40e: return index;
    case 0x40f: return 0; // Test mode disabled.
    case 0x460: return phy_ready ? 0x80 : 0; // ID floating/B-device, VBUS below session end, no session.
    default: throw unsupported(offset);
    }
}
void Usb::write_core(uint32_t offset, uint8_t value) {
    switch (offset) {
    case 0x400: address = value & 127; return;
    case 0x401:
        if (value & 0x0e) throw std::runtime_error("USB0 resume, reset signalling and suspend are unsupported");
        power = value & 0xe1; return;
    case 0x406: tx_enable = value & 31; return;
    case 0x407: return; // Endpoints above 4 are not implemented in this device.
    case 0x408: rx_enable = value & 30; return;
    case 0x409: return;
    case 0x40b: usb_enable = value; return;
    case 0x40e:
        if (value > 4) throw unsupported(offset);
        index = value; return;
    case 0x40f: if (!value) return; break;
    case 0x460:
        if (value & 3) throw std::runtime_error("USB0 host request/session initiation is unsupported");
        return; // Remaining DEVCTL fields are read-only.
    default: break;
    }
    throw unsupported(offset);
}
uint32_t Usb::read(uint32_t offset, uint32_t size, uint64_t cycle) {
    advance(cycle);
    if (uint32_t writable = 0; size == 4 && !(offset & 3))
        if (bool readable = false; const uint32_t *held = setup_register(offset, writable, readable)) {
            if (!readable) throw unsupported(offset);
            return *held;
        }
    if (offset >= 0x400 && offset < 0x1000) {
        uint32_t value = 0;
        for (unsigned i = 0; i < size; i++) value |= uint32_t(read_core(offset + i)) << (i * 8);
        return value;
    }
    if (size != 4 || (offset & 3)) throw unsupported(offset);
    switch (offset) {
    case 0: return 0x4ea10800;
    case 4: return control;
    case 8: return 0; // DRVVBUS low in the disconnected peripheral profile.
    case 0x20: case 0x24: case 0x28: return source;
    case 0x2c: case 0x30: case 0x34: return mask;
    case 0x38: return source & mask;
    case 0x3c: return 0;
    default: throw unsupported(offset);
    }
}
void Usb::write(uint32_t offset, uint32_t value, uint32_t size, uint64_t cycle) {
    advance(cycle);
    if (uint32_t writable = 0; size == 4 && !(offset & 3))
        if (bool readable = false; uint32_t *held = setup_register(offset, writable, readable)) {
            // A channel teardown needs the DMA to return a teardown descriptor: no traffic model.
            if (offset >= 0x1800 && offset < 0x1880 && (offset & 0x17) == 0 && (value & 0x40000000))
                throw std::runtime_error("USB0 CPPI channel teardown is unsupported");
            *held = value & writable;
            return;
        }
    if (offset >= 0x400 && offset < 0x1000) {
        for (unsigned i = 0; i < size; i++) write_core(offset + i, uint8_t(value >> (i * 8)));
        return;
    }
    if (size != 4 || (offset & 3)) throw unsupported(offset);
    switch (offset) {
    case 4:
        if (value & 0x18) throw std::runtime_error("USB0 RNDIS and non-PDR interrupt mode are unsupported");
        if ((value & 1) && !clock_running()) throw std::runtime_error("USB0 soft reset requires its PSC clock");
        control = value & 3;
        if (value & 1) {
            reset_due = cycle + 16; resets++;
        }
        break;
    case 0x24: source |= value & IRQ_BITS; break;
    case 0x28: source &= ~value; break;
    case 0x30: mask |= value & IRQ_BITS; break;
    case 0x34: mask &= ~value; break;
    case 0x3c:
        if (value & 255) throw unsupported(offset);
        in_service = false; break;
    default: throw unsupported(offset);
    }
    update_irq();
}
