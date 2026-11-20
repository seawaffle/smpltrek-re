#ifndef SMPLTREK_EMULATOR_BOARD_H
#define SMPLTREK_EMULATOR_BOARD_H
#include <array>
#include <cstdint>
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
    uint32_t pending_interrupts = 0;
    void enable(bool gpio_handoff = false);
    void advance(uint64_t cycle);
    // Eager polling is the every-cycle reference, including during CPU waits.
    uint64_t next_event() const { return !enabled ? UINT64_MAX : eager_polling ? 0 : deadline; }
    void set_eager_polling(bool value) { eager_polling = value; deadline = 0; }
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
    // Bytes each UART has finished transmitting, most recent 4096 retained. Observation
    // only: the peer stays silent.
    struct UartSent { std::array<uint8_t, 4096> bytes{}; uint64_t count = 0; };
    std::array<UartSent, 3> uart_sent;
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
