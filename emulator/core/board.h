#ifndef SMPLTREK_EMULATOR_BOARD_H
#define SMPLTREK_EMULATOR_BOARD_H
#include <array>
#include <cstdint>
#include <deque>
#include <unordered_map>
#include <vector>
#include "edma.h"
#include "spi.h"
#include "uart.h"
#include "oled.h"
#include "mmcsd.h"
#include "nor.h"
#include "i2c.h"
#include "codec.h"
#include "mcasp.h"
#include "usb.h"

struct BoardAccess {
    uint64_t cycle;
    uint32_t pc, address, value, size, write;
};
// One row of an MMIO capture: a write, or a read (`repeat` counts identical reads folded into it: a poll).
struct CaptureRow {
    uint64_t cycle;
    uint32_t pc, address, value, size, write, repeat;
};
struct ReservedWrite {
    uint64_t cycle, value;
    uint32_t pc, address, size;
};

class Board {
    struct Timer {
        uint64_t last = 0, fraction = 0, deadline = UINT64_MAX;
    };
    std::array<Timer, 4> timers{};
    std::array<uint64_t, 2> psc_deadline{UINT64_MAX, UINT64_MAX};
    uint64_t deadline = 0;
    bool eager_polling = false;
    std::array<uint32_t, 5> gpio_inputs{};
    Edma edma;
    int selected_flash = -1;
    std::array<Spi, 2> spi;
    std::array<Uart, 3> uart;
    bool spi_pins(unsigned index, uint32_t word);
    std::unordered_map<uint32_t, uint32_t> registers;
    std::array<BoardAccess, 1024> log{};
    void record(uint32_t address, uint32_t value, uint32_t size, bool write, uint64_t cycle, uint32_t pc);
    uint32_t read_word(uint32_t address, uint64_t cycle);
    void write_word(uint32_t address, uint32_t value, uint64_t cycle);
    void update_timer(unsigned index, uint64_t cycle);
    void schedule_timer(unsigned index, uint64_t cycle);
    void event(unsigned number);
    void complete_psc(unsigned index);
    void reserved_guard() const;
    uint32_t gpio_levels(unsigned pair) const;
    void gpio_edges(unsigned pair, uint32_t previous);
    struct Driven { uint32_t outputs, levels; };
    Driven gpio_driven(unsigned pair) const;
    void gpio_record(unsigned pair, Driven previous, uint64_t cycle);
    uint64_t midi_character() const;
    uint64_t keys_down = 0;
    bool device(uint32_t address, uint32_t size) const;
public:
    static constexpr uint32_t RESERVED_END = 0x00700000;
    bool reserved_low_writes = false;
    bool reserved_low_reads = false;
    uint64_t reserved_read_count = 0; // every read; the trace keeps the first 4096
    std::vector<ReservedWrite> reserved_reads;
    std::vector<ReservedWrite> reserved_writes;
    uint64_t usb_reserved_count = 0; // every access; the trace keeps the first 4096
    std::vector<ReservedWrite> usb_reserved_reads;
    bool reserved_write(uint32_t address, const uint8_t *data, uint32_t size, uint64_t cycle, uint32_t pc, bool guest);
    bool enabled = false;
    uint64_t accesses = 0;
    // Whole-sequence capture of chosen address ranges, drained by the host (c6_capture_take) so nothing is
    // lost while the drain keeps up; past `limit` rows waiting, new rows are counted in `dropped`.
    struct Capture {
        bool on = false, writes_only = false;
        std::vector<std::pair<uint32_t, uint32_t>> ranges; // [start, end)
        std::deque<CaptureRow> rows;
        uint64_t recorded = 0, dropped = 0, limit = 0;
    } capture;
    uint32_t pending_interrupts = 0;
    void enable(bool gpio_handoff = false);
    void advance(uint64_t cycle);
    // Eager polling is the every-cycle reference, including during CPU waits.
    uint64_t next_event() const { return !enabled ? UINT64_MAX : eager_polling ? 0 : deadline; }
    void set_eager_polling(bool value) { eager_polling = value; deadline = 0; }
    void rescheduled() { deadline = 0; } // A peer changed a device's next event from outside advance().
    bool contains(uint32_t address, uint32_t size) const;
    // Whether any byte of this 4 KiB page belongs to a device, enabled or not.
    bool device_page(uint32_t base) const;
    uint32_t read(uint32_t address, uint32_t size, uint64_t cycle, uint32_t pc, bool trace = true);
    void write(uint32_t address, uint32_t value, uint32_t size, uint64_t cycle, uint32_t pc, bool trace = true);
    BoardAccess access(uint64_t sequence) const;
    void gpio_input(unsigned bank, unsigned pin, bool high);
    void key_input(unsigned key, bool down);
    void uart_receive(unsigned index, uint8_t byte);
    // Optional peer on UART1: the panel MCU's analogue reports. On the unit it sends them all the
    // time, touched or not: 4192-4196 messages a second, one channel 262 times a second (M1 bench
    // D1, D2; M2 P1, P4), 16 channels in the fixed order of ORDER (M2 P1), pads held or not. Not as the
    // unit: messages are evenly spaced here, where the unit sends them in bursts (64.9 to 1455.7 us apart,
    // 238.5 us on average); characters come at the rate the guest programmed (21.4 to 22.0 us on the unit);
    // an untouched pad reads 0 here and 0 to 4 on the unit.
    struct PanelStream {
        static constexpr uint64_t MESSAGE_CYCLES = 88698; // 372 MHz / 4194 messages a second
        static constexpr uint8_t ORDER[16] = {0, 4, 3, 7, 11, 13, 10, 14, 15, 2, 1, 5, 9, 6, 8, 12};
        bool enabled = false;
        uint64_t next = UINT64_MAX, message_start = 0, messages = 0;
        uint32_t position = 0; // place in ORDER * 3 + character
        uint16_t sending = 0;  // the level of the message under way
        std::array<uint16_t, 16> levels{};
    } panel;
    void panel_stream(bool enabled, uint64_t cycle);
    void panel_level(unsigned channel, uint32_t value);
    // Bytes each UART has finished transmitting and the cycle each one's last stop bit ended at, most
    // recent 4096 retained. Observation only: the peer stays silent, unless MIDI OUT is cabled to MIDI IN.
    struct UartSent { std::array<uint8_t, 4096> bytes{}; std::array<uint64_t, 4096> cycles{}; uint64_t count = 0; };
    std::array<UartSent, 3> uart_sent;
    // Optional peer on UART0: a sender on the MIDI IN jack. Queued bytes arrive back to back, one per
    // character time of the format and divisor the guest programmed (119,040 cycles, the 31,250 baud 8N1
    // of MIDI, while it has programmed none), the first starting at the cycle it was queued in an idle
    // line. A real sender keeps its own 31,250 baud whatever the guest programmed, and a mismatch would
    // show as framing errors, which this peer never produces. `loopback` is a cable from MIDI OUT to MIDI
    // IN instead: each byte UART0 finishes transmitting is received at that same cycle (no opto-isolator
    // delay). uart_receive stays the unpaced path.
    struct MidiIn {
        static constexpr uint64_t CHARACTER_CYCLES = 119040; // 372 MHz * 10 bits / 31,250 baud
        static constexpr size_t CAPACITY = 1 << 20;
        std::deque<uint8_t> queue;
        uint64_t next = UINT64_MAX;          // when the byte at the front has fully arrived
        uint64_t delivered = 0, ignored = 0; // ignored: the guest held its receiver in reset
        uint64_t looped = 0;
        bool loopback = false;
    } midi;
    void midi_in(const uint8_t *data, size_t size, uint64_t cycle);
    void midi_loopback(bool on);
    struct MidiState { uint64_t character_cycles, fifo, overruns, line_errors; };
    MidiState midi_state() const { return {midi_character(), uart[0].received(), uart[0].overruns, uart[0].line_status_errors()}; }
    // External pin levels to apply at given cycles, as gpio_input would then: SYNC IN edges on GP7[8].
    struct GpioEdge { uint64_t cycle; uint8_t bank, pin; bool high; };
    std::deque<GpioEdge> gpio_scheduled; // in cycle order; edges of one cycle in the order given
    void gpio_schedule(unsigned bank, unsigned pin, bool high, uint64_t cycle, uint64_t now);
    void gpio_schedule_clear(unsigned bank, unsigned pin);
    // Level changes of watched output pins, most recent 4096 retained: SYNC OUT on GP7[9] to begin with.
    // A pin's first row is the level it drives when it becomes an output. Of the pin mux only GP7[9]'s
    // (PINMUX17 nibble 0 = 8) is checked; any other watched pin counts as driven whenever it is an output.
    struct GpioChange { uint64_t cycle; uint8_t bank, pin; bool high; };
    struct GpioTrace {
        std::array<uint32_t, 5> watch{};
        std::array<GpioChange, 4096> rows{};
        uint64_t count = 0;
    } gpio_trace;
    void gpio_watch(unsigned bank, unsigned pin, bool on, uint64_t cycle);
    std::function<void(uint32_t, uint32_t, uint32_t)> dma_copy;
    Oled oled;
    std::array<Nor, 2> flash;
    I2c i2c;
    Codec codec;
    Mcasp mcasp;
    MmcSd mmcsd;
    Usb usb;
};
#endif
