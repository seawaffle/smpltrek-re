#ifndef SMPLTREK_EMULATOR_USB_H
#define SMPLTREK_EMULATOR_USB_H
#include <array>
#include <cstdint>
#include <deque>
#include <functional>
#include <vector>

// C6748 USB0: the TI wrapper, the MUSB core in peripheral mode (endpoint 0 and endpoints 1-4 with the
// 4 KiB dynamic FIFO RAM) and a scripted full-speed host on the cable, after SPRUH79C chapter 33.
// Bulk and interrupt endpoints carry data; an endpoint's ISO bit is held, but isochronous traffic,
// high speed, host/OTG operation, remote wake-up, test modes and CPPI DMA traffic are not modelled
// (the DMA set-up registers a driver programs before any transfer hold their values; DMAEN faults).
//
// Interrupts (the wrapper's "PDR interrupt handler", CTRLR.UINT). The core latches endpoint events in
// INTRTX/INTRRX and bus events in INTRUSB whether or not they are enabled in INTRTXE/INTRRXE/INTRUSBE.
//   UINT = 0: the wrapper takes each latched event that is enabled in the core out of the core register
//   and sets its bit in INTSRCR (EP0 and TX 1-4 at bits 0-4, RX 1-4 at bits 9-12, INTRUSB at bits
//   16-23). Software uses INTSRCR/INTMASKEDR, INTCLRR and the mask registers, and never the core
//   registers: a core register read here returns, and discards, the events not enabled in the core.
//   UINT = 1: nothing is handed over. Software reads INTRTX, INTRRX and INTRUSB, each read clearing
//   that register; event 19 is raised when the enabled latched events go from none to some.
// Either way event 19 is raised once for (INTSRCR & INTMSKR) != 0, and again after a write to EOIR
// while something is still pending. SPRUH79C states the register behaviour (33.2.8.13, 33.4.9-16,
// 33.4.23-28) but not the hand-over or what gates it: that part is this model's reading.
//
// The host is timed in guest cycles: 31 a bit (372 MHz / 12 Mbit/s), no bit stuffing. A transaction
// takes effect at the cycle its handshake would end. A NAKed transaction is retried back to back;
// the retries between a NAK and the next register access that could change the answer are counted,
// not run. The host waits for the device's pull-up (SOFTCONN with the clock and PHY up), then
// debounces, resets and starts sending SOFs.
class Usb {
public:
    static constexpr uint64_t BIT = 31, FRAME = 372000;                  // 372 MHz: 12 Mbit/s, 1 ms
    static constexpr uint64_t DEBOUNCE = 100 * FRAME, RESET = 10 * FRAME, RECOVERY = 10 * FRAME, IDLE = 3 * FRAME;
    enum class Handshake : uint8_t { Ack, Nak, Stall, None };
    enum class Port : uint8_t { Detached, Powered, Debounce, Reset, Enabled };
    enum Status : uint8_t { PENDING, DONE, STALLED, TIMED_OUT, DISCONNECTED, FAILED };
    enum Kind : uint8_t { CONTROL, OUT, IN };
    struct Transfer {
        uint32_t id = 0;
        uint8_t kind = CONTROL, endpoint = 0, status = PENDING, stage = 0;
        std::array<uint8_t, 8> setup{};
        std::vector<uint8_t> data;       // OUT: what to send. IN: what arrived.
        uint32_t length = 0, packet = 64; // IN: bytes wanted. Both: the endpoint's maximum packet size.
        size_t offset = 0;
        uint64_t naks = 0, submitted = 0, deadline = 0, completed = 0;
    };
    struct Host {
        Port port = Port::Detached;
        bool vbus = false, sof = true, suspended = false, reset_active = false;
        uint8_t address = 0, configuration = 0;
        uint16_t frame = 0;
        std::array<bool, 5> out_toggle{}, in_toggle{};
        uint64_t port_due = UINT64_MAX, sof_due = UINT64_MAX, idle_due = UINT64_MAX, transfer_due = UINT64_MAX;
        uint64_t free = 0;               // when the bus is next free for a transaction
        bool parked = false, committing = false;
        uint64_t parked_at = 0, period = 0;
        std::deque<Transfer> queue, finished;
        uint32_t next_id = 1;
        uint64_t resets = 0, sofs = 0, naks = 0, stalls = 0, errors = 0, toggle_errors = 0, transfers = 0;
    };
    struct Endpoint {
        uint16_t txmaxp = 0, rxmaxp = 0, txadd = 0, rxadd = 0;
        uint8_t txsz = 0, rxsz = 0, txcsrh = 0, rxcsrh = 0;
        bool tx_stall = false, tx_stalled = false, tx_toggle = false;
        bool rx_stall = false, rx_stalled = false, rx_toggle = false;
        std::array<uint16_t, 2> tx_size{}, rx_size{};
        uint8_t tx_packets = 0, tx_head = 0, rx_packets = 0, rx_head = 0;
        uint16_t tx_fill = 0, rx_read = 0;
    };
private:
    enum class Stage : uint8_t { Idle, Tx, Rx, StatusIn, StatusOut };
    uint32_t control = 0, source = 0, mask = 0, phy_control = 0;
    uint16_t tx_enable = 1, rx_enable = 0, intrtx = 0, intrrx = 0;
    uint8_t faddr = 0, address = 0, power = 0, usb_enable = 0, intrusb = 0, index = 0;
    bool in_service = false, core_line = false, faddr_pending = false;
    // Endpoint 0: one 64-byte FIFO at RAM address 0 for both directions.
    Stage stage = Stage::Idle;
    bool rx_ready = false, tx_ready = false, sent_stall = false, data_end = false, setup_end = false, send_stall = false;
    uint8_t count0 = 0, read0 = 0, fill0 = 0, size0 = 0;
    std::array<Endpoint, 5> endpoints{};
    std::array<uint8_t, 4096> ram{};
    Host host;
    uint32_t mode = 0, scheduler = 0, link_size = 0;
    std::array<uint32_t, 4> rndis_size{}, tx_channel{}, rx_channel{}, rx_queues_a{}, rx_queues_b{};
    std::array<uint32_t, 64> schedule{};
    std::array<uint32_t, 2> link_base{};
    std::array<uint32_t, 16> region_base{}, region_control{};
    uint32_t *setup_register(uint32_t offset, uint32_t &writable, bool &readable);
    uint64_t reset_due = UINT64_MAX, phy_due = UINT64_MAX;
    void update_irq();
    void raise(uint16_t tx, uint16_t rx, uint8_t usb);
    void core_reset();
    uint8_t read_core(uint32_t offset);
    void write_core(uint32_t offset, uint8_t value);
    uint8_t read_endpoint(unsigned n, unsigned reg);
    void write_endpoint(unsigned n, unsigned reg, uint8_t value);
    uint8_t fifo_read(unsigned n);
    void fifo_write(unsigned n, uint8_t value);
    static unsigned slot_size(uint8_t sz) { return 8u << (sz & 15); }
    static unsigned slots(uint8_t sz) { return sz & 16 ? 2 : 1; }
    uint8_t &cell(uint16_t add, uint8_t sz, unsigned slot, unsigned at) { return ram[(add * 8u + slot * slot_size(sz) + at) & 4095]; }
    void tx_commit(unsigned n);
    void rx_pop(unsigned n);
    void status_done();
    // The device's side of a transaction addressed to it.
    bool listening() const;
    Handshake token_setup(const uint8_t *setup);
    Handshake token_out(unsigned n, const uint8_t *data, size_t size, bool data1);
    Handshake token_in(unsigned n, std::vector<uint8_t> &data, bool &data1);
    Handshake in_response(unsigned n, size_t &size) const;
    void bus_reset();
    void bus_activity(uint64_t at);
    // The host.
    void port_update(uint64_t at);
    void port_down(uint64_t at);
    void host_step(uint64_t at);
    void host_attempt(uint64_t at);
    void host_next(uint64_t free);
    void host_wake(uint64_t cycle);
    void host_nak(uint64_t at, uint64_t period);
    void finish(uint8_t status, uint64_t at);
    uint64_t host_due() const;
public:
    bool phy_ready = false;
    uint64_t resets = 0, interrupts = 0;
    uint64_t fifo_overflows = 0, fifo_underflows = 0; // bytes loaded past a FIFO's packet size, or unloaded from an empty one
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
    uint32_t wrapper_control() const { return control; }
    uint8_t function_address() const { return address; }
    bool connected() const;
    const Host &peer() const { return host; }
    // Retries of the waiting transaction that have gone unanswered since it was last tried.
    uint64_t parked_naks(uint64_t cycle) const { return host.parked && cycle > host.parked_at ? (cycle - host.parked_at) / host.period : 0; }
    const Endpoint &endpoint(unsigned n) const { return endpoints.at(n); }
    void attach(bool on, uint64_t cycle);
    void reset_bus(uint64_t cycle);
    void sof(bool on, uint64_t cycle);
    uint32_t submit(Transfer transfer, uint64_t timeout, uint64_t cycle);
    const Transfer *find(uint32_t id) const;
    bool pending(uint32_t id) const;
    void forget(uint32_t id);
    void toggle_reset(unsigned address);
};
#endif
