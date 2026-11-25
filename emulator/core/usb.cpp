#include "usb.h"
#include <algorithm>
#include <cstdio>
#include <stdexcept>

namespace {
constexpr uint32_t IRQ_BITS = 0x01ff1e1f;
// Packet lengths in bit times: sync and PID, the fields, EOP; then the gap before the next packet.
constexpr uint64_t TOKEN = 35, HANDSHAKE = 19, GAP = 4;
constexpr uint64_t data_bits(size_t size) { return 35 + 8 * uint64_t(size); }
std::runtime_error unsupported(uint32_t offset) {
    char text[96]; std::snprintf(text, sizeof text, "unimplemented USB0 access at 0x%08x", 0x01e00000 + offset);
    return std::runtime_error(text);
}
}
void Usb::update_irq() {
    bool core = (intrtx & tx_enable) || (intrrx & rx_enable) || (intrusb & usb_enable);
    if (!(control & 8)) {
        source |= (intrtx & tx_enable) | uint32_t(intrrx & rx_enable) << 8 | uint32_t(intrusb & usb_enable) << 16;
        intrtx &= ~tx_enable; intrrx &= ~rx_enable; intrusb &= ~usb_enable;
        core = false;
    }
    if (!clock_running()) return;
    bool fire = core && !core_line;
    core_line = core;
    if (!in_service && (source & mask)) in_service = fire = true;
    if (fire) { interrupts++; interrupt(); }
}
void Usb::raise(uint16_t tx, uint16_t rx, uint8_t usb) {
    intrtx |= tx; intrrx |= rx; intrusb |= usb;
    update_irq();
}
void Usb::core_reset() {
    control = source = mask = 0;
    // SPRUH79C reset values: INTRTXE 0x1F, INTRRXE 0x1E, INTRUSBE 0x06 (33.4.25, 33.4.26, 33.4.28).
    tx_enable = 0x1f; rx_enable = 0x1e; intrtx = intrrx = 0;
    faddr = address = intrusb = index = 0; usb_enable = 0x06; power = POWER_RESET;
    in_service = core_line = faddr_pending = false;
    stage = Stage::Idle;
    rx_ready = tx_ready = sent_stall = data_end = setup_end = send_stall = false;
    count0 = read0 = fill0 = size0 = 0;
    endpoints = {};
    mode = scheduler = link_size = 0;
    rndis_size = tx_channel = rx_channel = rx_queues_a = rx_queues_b = {};
    schedule = {}; link_base = {}; region_base = region_control = {};
}
// Reset signalling on the bus (SPRUH79C 33.2.7.1): address and index to 0, FIFOs flushed, the
// control/status registers cleared, a reset interrupt. Packet sizes and FIFO placement are kept.
// The speed is negotiated here: a chirp if HSENAB is set.
void Usb::bus_reset() {
    faddr = address = index = 0; faddr_pending = false;
    host.high_speed = power & 0x20;
    if (host.high_speed) host.high_speed_resets++;
    stage = Stage::Idle;
    rx_ready = tx_ready = sent_stall = data_end = setup_end = send_stall = false;
    count0 = read0 = fill0 = size0 = 0;
    for (auto &e : endpoints) {
        Endpoint kept; kept.txmaxp = e.txmaxp; kept.rxmaxp = e.rxmaxp; kept.txadd = e.txadd; kept.rxadd = e.rxadd;
        kept.txsz = e.txsz; kept.rxsz = e.rxsz;
        e = kept;
    }
    raise(0, 0, 4);
}
bool Usb::connected() const { return host.vbus && clock_running() && phy_ready && (power & 0x40); }
bool Usb::listening() const { return host.port == Port::Enabled && connected() && host.address == address; }
void Usb::status_done() {
    stage = Stage::Idle; data_end = false;
    if (faddr_pending) { address = faddr; faddr_pending = false; }
    raise(1, 0, 0);
}
Usb::Handshake Usb::token_setup(const uint8_t *setup) {
    if (!listening()) return Handshake::None;
    if (stage != Stage::Idle && !data_end) setup_end = true;
    if (faddr_pending) { address = faddr; faddr_pending = false; }
    tx_ready = send_stall = data_end = false; fill0 = 0;
    std::copy(setup, setup + 8, ram.begin());
    count0 = 8; read0 = 0; rx_ready = true;
    stage = !(setup[6] | setup[7]) ? Stage::StatusIn : setup[0] & 0x80 ? Stage::Tx : Stage::Rx;
    raise(1, 0, 0);
    return Handshake::Ack;
}
Usb::Handshake Usb::in_response(unsigned n, size_t &size) const {
    size = 0;
    if (!listening() || n > 4) return Handshake::None;
    if (n) {
        const auto &e = endpoints[n];
        if (e.tx_stall) return Handshake::Stall;
        if (!e.tx_packets) return Handshake::Nak;
        size = e.tx_size[e.tx_head % slots(e.txsz)];
        return Handshake::Ack;
    }
    if (rx_ready) return Handshake::Nak;
    switch (stage) {
    case Stage::Tx:
        if (send_stall) return Handshake::Stall;
        if (!tx_ready) return Handshake::Nak;
        size = size0; return Handshake::Ack;
    case Stage::StatusIn: return send_stall ? Handshake::Stall : data_end ? Handshake::Ack : Handshake::Nak;
    case Stage::Rx: return Handshake::Ack;
    case Stage::StatusOut: return Handshake::Stall;
    default: return Handshake::Nak;
    }
}
Usb::Handshake Usb::token_in(unsigned n, std::vector<uint8_t> &data, bool &data1) {
    size_t size = 0;
    Handshake answer = in_response(n, size);
    data.clear(); data1 = true;
    if (answer == Handshake::None || answer == Handshake::Nak) return answer;
    if (n) {
        auto &e = endpoints[n];
        if (answer == Handshake::Stall) {
            e.tx_stalled = true; e.tx_packets = 0; e.tx_fill = 0;
            raise(uint16_t(1u << n), 0, 0);
            return answer;
        }
        unsigned slot = e.tx_head % slots(e.txsz);
        for (unsigned i = 0; i < size; i++) data.push_back(cell(e.txadd, e.txsz, slot, i));
        data1 = e.tx_toggle; e.tx_toggle = !e.tx_toggle;
        tx_depart(n);
        return answer;
    }
    if (answer == Handshake::Stall) {
        send_stall = tx_ready = data_end = false; sent_stall = true; stage = Stage::Idle;
        raise(1, 0, 0);
        return answer;
    }
    switch (stage) {
    case Stage::Tx:
        data.assign(ram.begin(), ram.begin() + size0);
        tx_ready = false;
        if (data_end) stage = Stage::StatusOut;
        raise(1, 0, 0);
        break;
    case Stage::StatusIn: status_done(); break;
    default: // The status stage of a write request before DATAEND: the transfer ends early.
        setup_end = true; stage = Stage::Idle;
        raise(1, 0, 0);
        break;
    }
    return answer;
}
Usb::Handshake Usb::token_out(unsigned n, const uint8_t *data, size_t size, bool data1) {
    if (!listening() || n > 4) return Handshake::None;
    if (n) {
        auto &e = endpoints[n];
        if (e.rx_stall) { e.rx_stalled = true; raise(0, uint16_t(1u << n), 0); return Handshake::Stall; }
        if (size > e.rxmaxp || size > slot_size(e.rxsz)) return Handshake::None; // not a packet this endpoint can take
        if (e.rx_packets >= slots(e.rxsz)) return Handshake::Nak;
        if (data1 != e.rx_toggle) { host.toggle_errors++; return Handshake::Ack; } // taken for a repeat: acknowledged, dropped
        unsigned slot = (e.rx_head + e.rx_packets) % slots(e.rxsz);
        for (unsigned i = 0; i < size; i++) cell(e.rxadd, e.rxsz, slot, i) = data[i];
        e.rx_size[slot] = uint16_t(size); e.rx_toggle = !e.rx_toggle;
        if (!e.rx_packets++) { e.rx_read = 0; raise(0, uint16_t(1u << n), 0); }
        return Handshake::Ack;
    }
    if (rx_ready) return Handshake::Nak;
    auto stall = [&] {
        send_stall = tx_ready = data_end = false; sent_stall = true; stage = Stage::Idle;
        raise(1, 0, 0);
        return Handshake::Stall;
    };
    switch (stage) {
    case Stage::Rx:
        if (send_stall || size > 64) return stall();
        std::copy(data, data + size, ram.begin());
        count0 = uint8_t(size); read0 = 0; rx_ready = true;
        raise(1, 0, 0);
        return Handshake::Ack;
    case Stage::StatusOut:
        if (size) return stall();
        status_done();
        return Handshake::Ack;
    case Stage::Tx: // The status stage of a read request before DATAEND: the transfer ends early.
        setup_end = true; tx_ready = false; fill0 = 0; stage = Stage::Idle;
        raise(1, 0, 0);
        return Handshake::Ack;
    case Stage::StatusIn: return stall();
    default: return Handshake::Nak;
    }
}
// An isochronous OUT packet: 0 stored, 1 lost to a full FIFO, 2 not taken at all.
unsigned Usb::iso_out(unsigned n, const uint8_t *data, size_t size) {
    if (!listening()) return 2;
    auto &e = endpoints[n];
    if (!(e.rxcsrh & 0x40) || size > e.rxmaxp || size > slot_size(e.rxsz)) return 2;
    if (e.rx_packets >= slots(e.rxsz)) {
        if (!e.rx_overrun) iso_overruns++;
        e.rx_overrun = true;
        return 1;
    }
    unsigned slot = (e.rx_head + e.rx_packets) % slots(e.rxsz);
    for (unsigned i = 0; i < size; i++) cell(e.rxadd, e.rxsz, slot, i) = data[i];
    e.rx_size[slot] = uint16_t(size);
    if (!e.rx_packets++) { e.rx_read = 0; raise(0, uint16_t(1u << n), 0); }
    return 0;
}
// An isochronous IN token: false if the device does not answer. `loaded` says a packet from the FIFO
// follows (its size in `size`), otherwise a zero-length one does.
bool Usb::iso_in_token(unsigned n, size_t &size, bool &loaded) {
    size = 0; loaded = false;
    if (!listening()) return false;
    auto &e = endpoints[n];
    if (!(e.txcsrh & 0x40)) return false;
    if (e.tx_packets > e.tx_held) { size = e.tx_size[e.tx_head % slots(e.txsz)]; loaded = true; return true; }
    if (!e.tx_packets) {
        if (!e.tx_underrun) iso_underruns++;
        e.tx_underrun = true;
    }
    return true;
}
// The end of the data packet that followed: the packet leaves the FIFO (unless it was flushed meanwhile).
// With both halves of a double-buffered FIFO loaded and neither held by ISOUPDATE, both leave in this one
// data packet: a babble at the host. That is a reading of unit session 6 (Enaga, 2026-11-23), not of the
// manual; see the README. Returns the number of packets that left.
unsigned Usb::iso_in_data(unsigned n, std::vector<uint8_t> &data) {
    auto &e = endpoints[n];
    data.clear();
    unsigned ready = e.tx_packets - e.tx_held, count = ready >= 2 ? 2 : e.tx_packets ? 1 : 0;
    if (count == 2) iso_double_sends++;
    for (unsigned k = 0; k < count; k++) {
        unsigned slot = e.tx_head % slots(e.txsz);
        for (unsigned i = 0; i < e.tx_size[slot]; i++) data.push_back(cell(e.txadd, e.txsz, slot, i));
        tx_depart(n);
    }
    return count;
}
// A packet leaves endpoint n's FIFO. TXPKTRDY reads 1 only while the FIFO has no room for another packet,
// and the endpoint interrupts only when it goes from 1 to 0 (SPRUH79C 33.2.7.1.2.1.2, TXCSR bit 0): when
// a double-buffered FIFO had both packets, not when the only one leaves (FIFONOTEMPTY then just drops).
void Usb::tx_depart(unsigned n) {
    auto &e = endpoints[n];
    if (!e.tx_packets) return;
    bool full = e.tx_packets >= slots(e.txsz);
    e.tx_head = uint8_t((e.tx_head + 1) % slots(e.txsz)); e.tx_packets--;
    e.tx_held = std::min(e.tx_held, e.tx_packets);
    if (full) raise(uint16_t(1u << n), 0, 0);
}
void Usb::tx_commit(unsigned n) {
    auto &e = endpoints[n];
    unsigned capacity = slots(e.txsz);
    if (e.tx_packets >= capacity) return;
    e.tx_size[(e.tx_head + e.tx_packets) % capacity] = e.tx_fill;
    e.tx_packets++; e.tx_fill = 0;
    if ((e.txcsrh & 0x40) && (power & 0x80)) e.tx_held++; // ISOUPDATE: not before the next SOF
    if (e.tx_packets < capacity) raise(uint16_t(1u << n), 0, 0); // double buffering: room for the next packet at once
}
void Usb::rx_pop(unsigned n) {
    auto &e = endpoints[n];
    if (!e.rx_packets) return;
    e.rx_head = uint8_t((e.rx_head + 1) % slots(e.rxsz)); e.rx_packets--; e.rx_read = 0;
    if (e.rx_packets) raise(0, uint16_t(1u << n), 0);
}
uint8_t Usb::fifo_read(unsigned n) {
    if (!n) {
        if (rx_ready && read0 < count0) return ram[read0++];
        fifo_underflows++; return 0;
    }
    auto &e = endpoints[n];
    if (!e.rx_packets || e.rx_read >= e.rx_size[e.rx_head % slots(e.rxsz)]) { fifo_underflows++; return 0; }
    uint8_t value = cell(e.rxadd, e.rxsz, e.rx_head % slots(e.rxsz), e.rx_read++);
    if ((e.rxcsrh & 0x80) && e.rx_read == e.rxmaxp) rx_pop(n);
    return value;
}
void Usb::fifo_write(unsigned n, uint8_t value) {
    if (!n) {
        if (fill0 < 64) ram[fill0++] = value; else fifo_overflows++;
        return;
    }
    auto &e = endpoints[n];
    unsigned capacity = slots(e.txsz);
    if (e.tx_packets >= capacity || e.tx_fill >= slot_size(e.txsz)) { fifo_overflows++; return; }
    cell(e.txadd, e.txsz, (e.tx_head + e.tx_packets) % capacity, e.tx_fill++) = value;
    if ((e.txcsrh & 0x80) && e.txmaxp && e.tx_fill == e.txmaxp) tx_commit(n);
}
uint8_t Usb::read_endpoint(unsigned n, unsigned reg) {
    if (!n) {
        switch (reg) {
        case 2: return uint8_t(rx_ready | tx_ready << 1 | sent_stall << 2 | data_end << 3 | setup_end << 4);
        case 8: return rx_ready ? uint8_t(count0 - read0) : 0;
        case 15: return 0x06; // CONFIGDATA: dynamic FIFO sizing, soft connect, little endian, 8-bit UTMI.
        default: return 0;
        }
    }
    const auto &e = endpoints[n];
    unsigned left = e.rx_packets ? e.rx_size[e.rx_head % slots(e.rxsz)] - e.rx_read : 0;
    switch (reg) {
    case 0: return uint8_t(e.txmaxp);
    case 1: return uint8_t(e.txmaxp >> 8);
    case 2: return uint8_t((e.tx_packets >= slots(e.txsz)) | (e.tx_packets ? 2 : 0) | e.tx_underrun << 2 | e.tx_stall << 4 | e.tx_stalled << 5);
    case 3: return e.txcsrh;
    case 4: return uint8_t(e.rxmaxp);
    case 5: return uint8_t(e.rxmaxp >> 8);
    case 6: return uint8_t((e.rx_packets ? 1 : 0) | (e.rx_packets >= slots(e.rxsz) ? 2 : 0) | e.rx_overrun << 2 | e.rx_stall << 5 | e.rx_stalled << 6);
    case 7: return e.rxcsrh;
    case 8: return uint8_t(left);
    case 9: return uint8_t(left >> 8);
    case 10: case 11: case 12: case 13: return 0; // Host-mode type and interval registers.
    default: throw unsupported(0x500 + n * 16 + reg);
    }
}
void Usb::write_endpoint(unsigned n, unsigned reg, uint8_t value) {
    if (reg >= 10 && reg <= 13) { // Host-mode type and interval registers.
        if (value) throw unsupported(0x500 + n * 16 + reg);
        return;
    }
    if (!n) {
        if (reg == 2) {
            if (value & 0x80) setup_end = false;
            if (value & 0x40) { rx_ready = false; count0 = read0 = 0; }
            if (value & 0x20) send_stall = true;
            if (value & 0x08) data_end = true;
            if (!(value & 0x04)) sent_stall = false;
            if ((value & 0x02) && !tx_ready) { tx_ready = true; size0 = fill0; fill0 = 0; } // written back while set: no second packet
            if (stage == Stage::Rx && data_end && !rx_ready) stage = Stage::StatusIn;
        } else if (reg == 3) {
            if ((value & 1) && (tx_ready || rx_ready)) { tx_ready = rx_ready = false; count0 = read0 = fill0 = 0; }
        } else if (reg == 8 || reg == 9 || reg >= 14 || value) throw unsupported(0x500 + reg);
        return;
    }
    auto &e = endpoints[n];
    switch (reg) {
    case 0: e.txmaxp = (e.txmaxp & 0x700) | value; return;
    case 1: e.txmaxp = uint16_t((e.txmaxp & 0xff) | (value & 7) << 8); return;
    case 2:
        if (value & 0x40) e.tx_toggle = false;
        e.tx_stall = value & 0x10;
        if (!(value & 0x20)) e.tx_stalled = false;
        if (!(value & 0x04)) e.tx_underrun = false;
        if (value & 0x08) {
            if (e.tx_packets) { e.tx_head = uint8_t((e.tx_head + 1) % slots(e.txsz)); e.tx_packets--; }
            e.tx_fill = 0; e.tx_held = std::min(e.tx_held, e.tx_packets);
        } else if (value & 1) tx_commit(n);
        return;
    case 3:
        if (value & 0x10) throw std::runtime_error("USB0 endpoint DMA requests are unsupported");
        e.txcsrh = value & 0xec; return;
    case 4: e.rxmaxp = (e.rxmaxp & 0x700) | value; return;
    case 5: e.rxmaxp = uint16_t((e.rxmaxp & 0xff) | (value & 7) << 8); return;
    case 6:
        if (value & 0x80) e.rx_toggle = false;
        e.rx_stall = value & 0x20;
        if (!(value & 0x40)) e.rx_stalled = false;
        if (!(value & 0x04)) e.rx_overrun = false;
        if ((value & 0x10) || !(value & 1)) rx_pop(n);
        return;
    case 7:
        if (value & 0x20) throw std::runtime_error("USB0 endpoint DMA requests are unsupported");
        e.rxcsrh = value & 0xd8; return;
    default: throw unsupported(0x500 + n * 16 + reg);
    }
}
void Usb::bus_activity(uint64_t at) {
    if (host.suspended) { host.suspended = false; raise(0, 0, 2); }
    if (!host.sof) host.idle_due = at + IDLE;
}
void Usb::port_down(uint64_t at) {
    if (!host.queue.empty() && host.queue.front().stage) finish(DISCONNECTED, at);
    host.port = Port::Powered;
    host.port_due = host.sof_due = host.idle_due = host.transfer_due = host.iso_due = UINT64_MAX;
    host.parked = host.committing = host.reset_active = host.suspended = host.iso_sending = host.high_speed = false;
    host.address = host.configuration = 0;
    for (unsigned n = 1; n < 5; n++) { host.iso_out[n].out.clear(); host.iso_in[n].frames = 0; } // the streams end with the port
}
void Usb::port_update(uint64_t at) {
    bool up = connected();
    if (host.port >= Port::Debounce && !up) port_down(at);
    if (host.port == Port::Powered && up) { host.port = Port::Debounce; host.port_due = at + DEBOUNCE; }
}
uint64_t Usb::host_due() const {
    uint64_t timeout = host.queue.empty() ? UINT64_MAX : host.queue.front().deadline;
    return std::min({host.port_due, host.sof_due, host.idle_due, host.transfer_due, host.iso_due, timeout});
}
// Schedules this frame's next isochronous transaction, from `slot` on, on a bus free from `free`: an OUT
// packet's end, or an IN token's end.
void Usb::iso_next(uint64_t free, unsigned slot) {
    host.iso_sending = false;
    for (; slot < 8; slot++) {
        unsigned n = slot / 2 + 1;
        if (slot & 1 ? host.iso_in[n].frames == 0 : host.iso_out[n].out.empty()) continue;
        host.iso_slot = uint8_t(slot);
        host.iso_due = free + (slot & 1 ? GAP + TOKEN : GAP + TOKEN + GAP + data_bits(host.iso_out[n].out.front().size())) * BIT;
        return;
    }
    host.iso_due = UINT64_MAX;
}
void Usb::iso_step(uint64_t at) {
    unsigned slot = host.iso_slot, n = slot / 2 + 1;
    if (!(slot & 1)) {
        auto &stream = host.iso_out[n];
        std::vector<uint8_t> payload = std::move(stream.out.front());
        stream.out.pop_front(); stream.done++;
        switch (iso_out(n, payload.data(), payload.size())) {
        case 0: stream.packets++; stream.bytes += payload.size(); break;
        case 1: stream.missed++; break;
        default: stream.errors++; break;
        }
        iso_next(at, slot + 1);
        return;
    }
    auto &stream = host.iso_in[n];
    auto record = [&](uint8_t status, std::vector<uint8_t> data) {
        stream.in.push_back({host.frame, status, at, std::move(data)});
        if (stream.in.size() > 65536) { stream.in.pop_front(); stream.dropped++; }
    };
    if (!host.iso_sending) {
        stream.frames--; stream.done++;
        if (!iso_in_token(n, host.iso_size, host.iso_loaded)) {
            stream.errors++; record(2, {});
            iso_next(at + (GAP + HANDSHAKE) * BIT, slot + 1); // the host waits out the turn-around
            return;
        }
        host.iso_sending = true;
        host.iso_due = at + (GAP + data_bits(host.iso_size)) * BIT;
        return;
    }
    std::vector<uint8_t> data;
    unsigned sent = host.iso_loaded ? iso_in_data(n, data) : 0;
    if (sent > 1 || data.size() > stream.packet) { stream.errors++; record(2, {}); } // babble
    else if (data.empty()) { stream.missed++; record(1, {}); }
    else {
        stream.packets++; stream.bytes += data.size();
        if (data.size() < stream.short_below) stream.shorts++;
        record(0, std::move(data));
    }
    iso_next(at, slot + 1);
}
void Usb::finish(uint8_t status, uint64_t at) {
    Transfer done = std::move(host.queue.front());
    host.queue.pop_front();
    done.status = status; done.completed = at;
    host.transfers++;
    host.finished.push_back(std::move(done));
    if (host.finished.size() > 256) host.finished.pop_front();
    host.parked = host.committing = false; host.transfer_due = UINT64_MAX;
    host.free = std::max(host.free, at + GAP * BIT);
    if (!host.queue.empty() && host.port == Port::Enabled) host_next(host.free);
}
// Schedules the front transfer's next transaction on a bus that is free from `free`: the cycle its
// handshake would end at if the device answers with one (data from the device takes longer).
void Usb::host_next(uint64_t free) {
    const Transfer &t = host.queue.front();
    host.free = free; host.parked = host.committing = false;
    bool in = t.kind == IN || (t.kind == CONTROL && t.stage == 2 && (t.setup[0] & 0x80)) ||
        (t.kind == CONTROL && t.stage == 3 && !((t.setup[0] & 0x80) && (t.setup[6] | t.setup[7])));
    size_t size = t.kind == CONTROL && t.stage <= 1 ? 8 : t.kind == CONTROL && t.stage == 3 ? 0 :
        std::min<size_t>(t.packet, t.data.size() - t.offset);
    host.transfer_due = free + (in ? TOKEN + GAP + HANDSHAKE : TOKEN + GAP + data_bits(size) + GAP + HANDSHAKE) * BIT;
}
void Usb::host_nak(uint64_t at, uint64_t period) {
    host.queue.front().naks++; host.naks++;
    host.parked = true; host.parked_at = at; host.period = period;
    host.committing = false; host.transfer_due = UINT64_MAX;
}
void Usb::host_wake(uint64_t cycle) {
    if (!host.parked) return;
    uint64_t retries = cycle < host.parked_at ? 1 : (cycle - host.parked_at) / host.period + 1;
    host.queue.front().naks += retries - 1; host.naks += retries - 1;
    host.parked = false;
    host.transfer_due = host.parked_at + retries * host.period;
}
// Transfer stages: 0 not started, 1 SETUP (control) or data (bulk), 2 control data, 3 control status.
void Usb::host_attempt(uint64_t at) {
    if (host.queue.empty() || host.port != Port::Enabled) return;
    Transfer &t = host.queue.front();
    if (!t.stage) t.stage = 1;
    bus_activity(at);
    unsigned n = t.kind == CONTROL ? 0 : t.endpoint & 15;
    bool control = t.kind == CONTROL, reads = t.setup[0] & 0x80;
    uint32_t wanted = control ? uint32_t(t.setup[6] | t.setup[7] << 8) : t.length;
    bool in = t.kind == IN || (control && t.stage == 2 && reads) || (control && t.stage == 3 && !(reads && wanted));
    if (in) {
        if (!host.committing) {
            size_t size = 0;
            Handshake answer = in_response(n, size);
            if (answer == Handshake::Nak) { host_nak(at, (TOKEN + GAP + HANDSHAKE + GAP) * BIT); return; }
            if (answer == Handshake::Ack) { // Data follows the token; the host's ACK ends the transaction.
                host.committing = true;
                host.transfer_due = at + (data_bits(size) + GAP) * BIT;
                return;
            }
        }
        host.committing = false;
        std::vector<uint8_t> packet; bool data1 = true;
        switch (token_in(n, packet, data1)) {
        case Handshake::Nak: host_nak(at, (TOKEN + GAP + HANDSHAKE + GAP) * BIT); return;
        case Handshake::Stall: host.stalls++; finish(STALLED, at); return;
        case Handshake::None: host.errors++; finish(FAILED, at); return;
        default: break;
        }
        if (control && t.stage == 3) {
            if (!packet.empty()) { host.errors++; finish(FAILED, at); return; }
        } else {
            if (!control) {
                if (data1 != host.in_toggle[n]) { host.toggle_errors++; host_next(at + GAP * BIT); return; } // taken for a repeat
                host.in_toggle[n] = !host.in_toggle[n];
            }
            if (t.data.size() + packet.size() > wanted || packet.size() > t.packet) { host.errors++; finish(FAILED, at); return; } // babble
            t.data.insert(t.data.end(), packet.begin(), packet.end());
            if (packet.size() == t.packet && t.data.size() < wanted) { host_next(at + GAP * BIT); return; }
            if (control) { t.stage = 3; host_next(at + GAP * BIT); return; }
        }
    } else {
        size_t size = control && t.stage == 3 ? 0 : std::min<size_t>(t.packet, t.data.size() - t.offset);
        Handshake answer = control && t.stage == 1 ? token_setup(t.setup.data()) :
            token_out(n, t.data.data() + t.offset, size, control ? true : host.out_toggle[n]);
        switch (answer) {
        case Handshake::Nak: host_nak(at, (TOKEN + GAP + data_bits(size) + GAP + HANDSHAKE + GAP) * BIT); return;
        case Handshake::Stall: host.stalls++; finish(STALLED, at); return;
        case Handshake::None: host.errors++; finish(FAILED, at); return;
        default: break;
        }
        if (control && t.stage == 1) { t.stage = wanted ? 2 : 3; host_next(at + GAP * BIT); return; }
        if (control && t.stage == 2) {
            t.offset += size;
            if (t.offset >= t.data.size()) t.stage = 3;
            host_next(at + GAP * BIT);
            return;
        }
        if (!control) {
            host.out_toggle[n] = !host.out_toggle[n];
            t.offset += size;
            if (t.offset < t.data.size()) { host_next(at + GAP * BIT); return; }
        }
    }
    if (control && !t.setup[0] && t.setup[1] == 5) { host.address = t.setup[2] & 127; host.free = at + 2 * FRAME; }
    if (control && !t.setup[0] && t.setup[1] == 9) {
        host.configuration = t.setup[2];
        host.out_toggle = {}; host.in_toggle = {};
    }
    if (control && t.setup[0] == 2 && t.setup[1] == 1 && !(t.setup[2] | t.setup[3])) toggle_reset(t.setup[4]);
    finish(DONE, at);
}
void Usb::host_step(uint64_t at) {
    if (at >= host.port_due) {
        host.port_due = UINT64_MAX;
        if (host.port == Port::Debounce) {
            host.port = Port::Reset; host.reset_active = true; host.port_due = at + RESET;
            bus_reset();
        } else if (host.port == Port::Reset) {
            host.port = Port::Enabled; host.reset_active = host.suspended = false; host.resets++;
            host.address = host.configuration = 0;
            host.out_toggle = {}; host.in_toggle = {};
            host.sof_due = host.sof ? at + FRAME : UINT64_MAX;
            host.idle_due = host.sof ? UINT64_MAX : at + IDLE;
            if (!host.queue.empty()) host_next(at + RECOVERY); else host.free = at + RECOVERY;
        }
        return;
    }
    if (!host.queue.empty() && at >= host.queue.front().deadline) {
        if (host.parked) {
            uint64_t retries = (at - host.parked_at) / host.period;
            host.queue.front().naks += retries; host.naks += retries;
        }
        finish(TIMED_OUT, at);
        return;
    }
    if (at >= host.sof_due) {
        host.sof_due += FRAME; host.frame = (host.frame + 1) & 2047; host.sofs++;
        bus_activity(at);
        for (auto &e : endpoints) e.tx_held = 0;
        raise(0, 0, 8);
        if (host.iso_due != UINT64_MAX) host.iso_skipped++; else iso_next(at, 0);
        return;
    }
    if (at >= host.iso_due) { iso_step(at); return; }
    if (at >= host.idle_due) {
        host.idle_due = UINT64_MAX; host.suspended = true;
        raise(0, 0, 1);
        return;
    }
    host.transfer_due = UINT64_MAX;
    host_attempt(at);
}
void Usb::attach(bool on, uint64_t cycle) {
    advance(cycle);
    if (on == host.vbus) return;
    if (on) { host.vbus = true; host.port = Port::Powered; port_update(cycle); return; }
    if (host.port >= Port::Debounce) port_down(cycle);
    host.vbus = false; host.port = Port::Detached;
    if (clock_running() && phy_ready) raise(0, 0, 0x20); // The session ends.
}
void Usb::reset_bus(uint64_t cycle) {
    advance(cycle);
    if (host.port != Port::Enabled) throw std::runtime_error("a USB bus reset needs an enabled port");
    port_down(cycle);
    host.port = Port::Reset; host.reset_active = true; host.port_due = cycle + RESET;
    bus_reset();
}
void Usb::sof(bool on, uint64_t cycle) {
    advance(cycle);
    host.sof = on;
    if (host.port != Port::Enabled) return;
    host.sof_due = on ? cycle + FRAME : UINT64_MAX;
    host.idle_due = on ? UINT64_MAX : cycle + IDLE;
}
uint32_t Usb::submit(Transfer transfer, uint64_t timeout, uint64_t cycle) {
    advance(cycle);
    unsigned n = transfer.endpoint & 15;
    if (transfer.kind > IN || (transfer.kind == CONTROL ? n != 0 : n < 1 || n > 4))
        throw std::runtime_error("USB transfers go to endpoint 0 (control) or endpoints 1 to 4");
    if (!transfer.packet || transfer.packet > 64) throw std::runtime_error("full-speed bulk, interrupt and control packets are 1 to 64 bytes");
    if (transfer.kind == CONTROL) {
        bool reads = transfer.setup[0] & 0x80;
        uint32_t wanted = uint32_t(transfer.setup[6] | transfer.setup[7] << 8);
        if (reads ? !transfer.data.empty() : transfer.data.size() != wanted)
            throw std::runtime_error("a control transfer's data must match wLength");
    }
    if (!timeout || timeout > (uint64_t(1) << 40) || host.queue.size() >= 1024) throw std::runtime_error("invalid USB transfer timeout or queue full");
    if (n && (transfer.kind == OUT ? endpoints[n].rxcsrh : endpoints[n].txcsrh) & 0x40)
        throw std::runtime_error("this USB endpoint is isochronous: use the isochronous streams");
    transfer.id = host.next_id++; transfer.status = PENDING; transfer.stage = 0; transfer.offset = 0; transfer.naks = 0;
    transfer.submitted = cycle; transfer.deadline = cycle + timeout; transfer.completed = 0;
    if (transfer.kind != OUT && !(transfer.kind == CONTROL && !(transfer.setup[0] & 0x80))) transfer.data.clear();
    host.queue.push_back(std::move(transfer));
    if (host.queue.size() == 1 && host.port == Port::Enabled) host_next(std::max(host.free, cycle));
    return host.queue.back().id;
}
const Usb::Transfer *Usb::find(uint32_t id) const {
    for (const auto &t : host.queue) if (t.id == id) return &t;
    for (const auto &t : host.finished) if (t.id == id) return &t;
    return nullptr;
}
bool Usb::pending(uint32_t id) const {
    for (const auto &t : host.queue) if (t.id == id) return true;
    return false;
}
void Usb::forget(uint32_t id) {
    std::erase_if(host.finished, [id](const Transfer &t) { return t.id == id; });
}
void Usb::toggle_reset(unsigned endpoint_address) {
    unsigned n = endpoint_address & 15;
    if (n < 1 || n > 4) return;
    (endpoint_address & 0x80 ? host.in_toggle : host.out_toggle)[n] = false;
}
void Usb::iso_queue(unsigned n, std::vector<uint8_t> payload, uint64_t cycle) {
    advance(cycle);
    if (n < 1 || n > 4) throw std::runtime_error("isochronous streams go to endpoints 1 to 4");
    if (payload.size() > 1023) throw std::runtime_error("a full-speed isochronous packet is at most 1023 bytes");
    if (host.port != Port::Enabled) throw std::runtime_error("an isochronous stream needs an enabled port");
    if (host.iso_out[n].out.size() >= 65536) throw std::runtime_error("too many isochronous packets queued");
    host.iso_out[n].out.push_back(std::move(payload));
}
void Usb::iso_request(unsigned n, uint32_t frames, uint32_t packet, uint32_t short_below, uint64_t cycle) {
    advance(cycle);
    if (n < 1 || n > 4) throw std::runtime_error("isochronous streams go to endpoints 1 to 4");
    if (!packet || packet > 1023 || short_below > 1023) throw std::runtime_error("a full-speed isochronous packet is at most 1023 bytes");
    if (host.port != Port::Enabled) throw std::runtime_error("an isochronous stream needs an enabled port");
    auto &stream = host.iso_in[n];
    if (frames > (1u << 24) - stream.frames) throw std::runtime_error("too many isochronous frames asked for");
    stream.frames += frames; stream.packet = uint16_t(packet); stream.short_below = uint16_t(short_below);
}
void Usb::iso_stop(unsigned address, uint64_t cycle) {
    advance(cycle);
    unsigned n = address & 15;
    if (n < 1 || n > 4) throw std::runtime_error("isochronous streams go to endpoints 1 to 4");
    if (address & 0x80) host.iso_in[n].frames = 0; else host.iso_out[n].out.clear();
}
bool Usb::iso_take(unsigned n, IsoPacket &packet) {
    auto &stream = host.iso_in.at(n);
    if (stream.in.empty()) return false;
    packet = std::move(stream.in.front()); stream.in.pop_front();
    return true;
}
const Usb::IsoStream &Usb::iso(unsigned address) const {
    unsigned n = address & 15;
    if (n < 1 || n > 4) throw std::runtime_error("isochronous streams go to endpoints 1 to 4");
    return address & 0x80 ? host.iso_in[n] : host.iso_out[n];
}
uint64_t Usb::iso_errors() const {
    uint64_t total = host.iso_skipped;
    for (unsigned n = 1; n < 5; n++) total += host.iso_out[n].errors + host.iso_in[n].errors;
    return total;
}
uint64_t Usb::iso_missed() const {
    uint64_t total = 0;
    for (unsigned n = 1; n < 5; n++) total += host.iso_out[n].missed + host.iso_in[n].missed;
    return total;
}
void Usb::advance(uint64_t cycle) {
    if (cycle >= reset_due) {
        uint64_t at = reset_due;
        core_reset(); reset_due = UINT64_MAX;
        port_update(at);
    }
    if (cycle >= phy_due) {
        uint64_t at = phy_due;
        phy_ready = true; phy_due = UINT64_MAX;
        port_update(at);
    }
    for (uint64_t due = host_due(); cycle >= due; due = host_due()) host_step(due);
    update_irq();
}
uint64_t Usb::next_event() const { return std::min({reset_due, phy_due, host_due()}); }
void Usb::configure_phy(uint32_t value, uint64_t cycle) {
    advance(cycle);
    uint32_t previous = phy_control;
    value &= 0xffff; // CLKGood and VBUSSense are read-only PHY status.
    if (!(value & 0x8600) && (value & 15) &&
        ((value & 15) != 2 || !(value & 0x800) || (value & 0x6000)))
        throw std::runtime_error("USB0 PHY profile requires internal 24 MHz reference and no OTG override");
    phy_control = value;
    if ((phy_control & 0x8600) || !(phy_control & 15)) {
        phy_ready = false; phy_due = UINT64_MAX; port_update(cycle); return;
    }
    if ((previous & 0x80f) != (phy_control & 0x80f)) phy_ready = false;
    // Functional settling interval, not a measured PLL lock time.
    if (!phy_ready && phy_due == UINT64_MAX) phy_due = cycle + 64;
    port_update(cycle);
}
uint32_t Usb::phy_value(uint64_t cycle) {
    advance(cycle);
    // VBUSSense needs the PHY's VBUS comparators (USB0VBDTCTEN).
    return phy_control | (phy_ready ? 1u << 17 : 0) | (host.vbus && (phy_control & 0x10) ? 1u << 16 : 0);
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
uint8_t Usb::read_core(uint32_t offset) {
    if (offset >= 0x410 && offset < 0x420) return read_endpoint(index, offset - 0x410);
    if (offset >= 0x500 && offset < 0x550) return read_endpoint((offset - 0x500) >> 4, offset & 15);
    uint8_t value;
    switch (offset) {
    case 0x400: return faddr;
    case 0x401: return uint8_t(power | host.high_speed << 4 | host.reset_active << 3 | host.suspended << 1);
    // The interrupt registers clear on read, a byte at a time here.
    case 0x402: value = uint8_t(intrtx); intrtx &= 0xff00; return value;
    case 0x403: value = uint8_t(intrtx >> 8); intrtx &= 0x00ff; return value;
    case 0x404: value = uint8_t(intrrx); intrrx &= 0xff00; return value;
    case 0x405: value = uint8_t(intrrx >> 8); intrrx &= 0x00ff; return value;
    case 0x406: return uint8_t(tx_enable);
    case 0x407: return uint8_t(tx_enable >> 8);
    case 0x408: return uint8_t(rx_enable);
    case 0x409: return uint8_t(rx_enable >> 8);
    case 0x40a: value = intrusb; intrusb = 0; return value;
    case 0x40b: return usb_enable;
    case 0x40c: return host.port == Port::Enabled ? uint8_t(host.frame) : 0; // The last SOF's frame number.
    case 0x40d: return host.port == Port::Enabled ? uint8_t(host.frame >> 8) : 0;
    case 0x40e: return index;
    case 0x40f: return 0; // Test mode disabled.
    // B device; with VBUS, above VBusValid and in a session the controller started.
    case 0x460: return !phy_ready ? 0 : host.vbus ? 0x99 : 0x80;
    case 0x462: return index ? endpoints[index].txsz : 0;
    case 0x463: return index ? endpoints[index].rxsz : 0;
    case 0x464: return index ? uint8_t(endpoints[index].txadd) : 0;
    case 0x465: return index ? uint8_t(endpoints[index].txadd >> 8) : 0;
    case 0x466: return index ? uint8_t(endpoints[index].rxadd) : 0;
    case 0x467: return index ? uint8_t(endpoints[index].rxadd >> 8) : 0;
    default: throw unsupported(offset);
    }
}
void Usb::write_core(uint32_t offset, uint8_t value) {
    if (offset >= 0x410 && offset < 0x420) { write_endpoint(index, offset - 0x410, value); return; }
    if (offset >= 0x500 && offset < 0x550) { write_endpoint((offset - 0x500) >> 4, offset & 15, value); return; }
    if (offset >= 0x462 && offset < 0x468) { // Dynamic FIFO placement, endpoints 1 to 4. A change empties that FIFO.
        if (!index) { if (value) throw unsupported(offset); return; }
        auto &e = endpoints[index];
        if (offset == 0x462 || offset == 0x464 || offset == 0x465) { e.tx_packets = e.tx_head = e.tx_held = 0; e.tx_fill = 0; }
        else { e.rx_packets = e.rx_head = 0; e.rx_read = 0; }
        switch (offset) {
        case 0x462: e.txsz = value & 0x1f; return;
        case 0x463: e.rxsz = value & 0x1f; return;
        case 0x464: e.txadd = (e.txadd & 0x1f00) | value; return;
        case 0x465: e.txadd = uint16_t((e.txadd & 0xff) | (value & 0x1f) << 8); return;
        case 0x466: e.rxadd = (e.rxadd & 0x1f00) | value; return;
        default: e.rxadd = uint16_t((e.rxadd & 0xff) | (value & 0x1f) << 8); return;
        }
    }
    switch (offset) {
    case 0x400: // Written during a control transfer, the address is used from the end of its status stage.
        faddr = value & 127;
        if (stage == Stage::Idle) address = faddr; else faddr_pending = true;
        return;
    case 0x401:
        if (value & 0x04) throw std::runtime_error("USB0 resume signalling is unsupported");
        power = value & 0xe1; return; // RESET and SUSPENDM are read-only in peripheral mode.
    case 0x402: case 0x403: case 0x404: case 0x405: case 0x40a: return; // Read-only interrupt status.
    case 0x406: tx_enable = value & 31; return;
    case 0x407: return; // Endpoints above 4 are not implemented in this device.
    case 0x408: rx_enable = value & 30; return;
    case 0x409: return;
    case 0x40b: usb_enable = value; return;
    case 0x40c: case 0x40d: return; // FRAME is read-only.
    case 0x40e:
        if (value > 4) throw unsupported(offset);
        index = value; return;
    case 0x40f: if (!value) return; break;
    case 0x460:
        if ((value & 2) || ((value & 1) && !host.vbus)) throw std::runtime_error("USB0 host request/session initiation is unsupported");
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
    if (offset >= 0x420 && offset < 0x434) { // FIFOn: each access unloads as many bytes as it is wide.
        if (offset & 3) throw unsupported(offset);
        uint32_t value = 0;
        for (unsigned i = 0; i < size; i++) value |= uint32_t(fifo_read((offset - 0x420) / 4)) << (i * 8);
        host_wake(cycle);
        return value;
    }
    if (offset >= 0x400 && offset < 0x1000) {
        uint32_t value = 0;
        for (unsigned i = 0; i < size; i++) value |= uint32_t(read_core(offset + i)) << (i * 8);
        update_irq();
        return value;
    }
    if (size != 4 || (offset & 3)) throw unsupported(offset);
    switch (offset) {
    case 0: return 0x4ea10800;
    case 4: return control;
    case 8: return 0; // DRVVBUS low: a peripheral does not source VBUS.
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
    if (offset >= 0x420 && offset < 0x434) { // FIFOn: each access loads as many bytes as it is wide.
        if (offset & 3) throw unsupported(offset);
        for (unsigned i = 0; i < size; i++) fifo_write((offset - 0x420) / 4, uint8_t(value >> (i * 8)));
        host_wake(cycle);
        return;
    }
    if (offset >= 0x400 && offset < 0x1000) {
        for (unsigned i = 0; i < size; i++) write_core(offset + i, uint8_t(value >> (i * 8)));
        update_irq();
        port_update(cycle);
        host_wake(cycle);
        return;
    }
    if (size != 4 || (offset & 3)) throw unsupported(offset);
    switch (offset) {
    case 4:
        if (value & 0x10) throw std::runtime_error("USB0 RNDIS mode is unsupported");
        if ((value & 1) && !clock_running()) throw std::runtime_error("USB0 soft reset requires its PSC clock");
        control = value & 0xb;
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
        in_service = core_line = false; break;
    default: throw unsupported(offset);
    }
    update_irq();
}
