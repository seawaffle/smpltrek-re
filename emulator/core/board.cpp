#include "board.h"
#include <algorithm>
#include <cstdio>
#include <stdexcept>
#include <string>
#include <unordered_set>

namespace {
struct InvalidateDeadline {
    uint64_t &value;
    ~InvalidateDeadline() { value = 0; }
};
std::runtime_error unknown(uint32_t address) {
    char text[80]; std::snprintf(text, sizeof text, "unimplemented MMIO register 0x%08x", address);
    return std::runtime_error(text);
}
constexpr uint32_t INTC = 0x01800000, CACHE = 0x01840000;
constexpr uint32_t SYSCFG = 0x01c14000;
constexpr uint32_t SYSCFG1 = 0x01e2c000;
constexpr uint32_t DDRC = 0xb0000000;
constexpr uint32_t GPIO = 0x01e26000;
constexpr uint32_t EDMA = 0x01c00000;
constexpr uint32_t MMCSD = 0x01c40000;
constexpr uint32_t I2C0 = 0x01c22000;
constexpr uint32_t MCASP0 = 0x01d00000;
constexpr uint32_t USB0 = 0x01e00000;
constexpr std::array<uint32_t, 2> SPI{0x01c41000, 0x01f0e000};
constexpr std::array<uint32_t, 3> UART{0x01c42000, 0x01d0c000, 0x01d0d000};
constexpr std::array<uint32_t, 2> PSC{0x01c10000, 0x01e27000};
constexpr std::array<uint32_t, 4> TIMER{0x01c20000, 0x01c21000, 0x01f0c000, 0x01f0d000};
// T64P0_TINT12, T64P1_TINT12, T64P2_TINTALL, T64P3_TINTALL (only the 1:2 half of each timer is modelled).
constexpr std::array<unsigned, 4> TIMER_EVENT{4, 40, 25, 86};
bool syscfg(uint32_t off) {
    return off == 0x38 || off == 0x3c || off == 0x40 || off == 0x110 || off == 0x114 || off == 0x118 ||
           (0x120 <= off && off <= 0x18c && !(off & 3));
}
bool timer_register(uint32_t off) {
    return (4 <= off && off <= 0x28 && !(off & 3)) || (0x34 <= off && off <= 0x44 && !(off & 3)) ||
           (0x60 <= off && off < 0x80 && !(off & 3));
}
bool group(uint32_t offset, uint32_t first) { return first <= offset && offset < first + 16 && !(offset & 3); }
bool cache_base(uint32_t offset) {
    static const std::unordered_set<uint32_t> offsets{0x4000, 0x4010, 0x4018, 0x4020, 0x4030, 0x4040, 0x4048};
    return offsets.contains(offset);
}
bool cache_command(uint32_t offset) {
    static const std::unordered_set<uint32_t> offsets{0x5000, 0x5004, 0x5008, 0x5028, 0x5040, 0x5044, 0x5048};
    return offsets.contains(offset);
}
}

void Board::enable(bool gpio_handoff) {
    reserved_low_writes = false; reserved_writes.clear();
    reserved_low_reads = false; reserved_read_count = 0; reserved_reads.clear();
    usb_reserved_count = 0; usb_reserved_reads.clear();
    panel = PanelStream{}; panel.levels[15] = 12000;
    keys_down = 0;
    enabled = true; accesses = 0; pending_interrupts = 0; registers.clear(); timers = {};
    deadline = 0; eager_polling = false;
    psc_deadline.fill(UINT64_MAX);
    edma = Edma{};
    edma.copy = [this](uint32_t src, uint32_t dst, uint32_t size) { dma_copy(src, dst, size); };
    edma.interrupt = [this] { event(8); };
    mmcsd.reset();
    mmcsd.pins_ready = [this] { return (registers[SYSCFG + 0x148] & 0xffffff) == 0x222222; };
    mmcsd.dma_request = [this](bool receive) { edma.event(receive ? 16 : 17); };
    mmcsd.clock_running = [this] { return (registers[PSC[0] + 0x814] & 63) == 3; };
    mmcsd.interrupt = [this] { event(15); };
    codec.reset(); i2c.reset();
    usb = Usb{};
    usb.clock_running = [this] { return (registers[PSC[1] + 0x804] & 63) == 3; };
    usb.interrupt = [this] { event(19); };
    i2c.interrupt = [this] { event(36); };
    i2c.start = [this](uint32_t address, bool read, uint64_t) {
        if (address != 0x18 || (registers[SYSCFG + 0x130] & 0xff00) != 0x2200) return false;
        codec.start(read); return true;
    };
    i2c.send = [this](uint8_t byte, uint64_t cycle) { return codec.send(byte, cycle); };
    i2c.receive = [this](uint64_t cycle) { return codec.receive(cycle); };
    i2c.stop = [](uint64_t) {};
    mcasp.reset();
    mcasp.interrupt = [this] { event(61); };
    mcasp.dma_request = [this](bool receive) { edma.event(receive ? 0 : 1); };
    mcasp.clocks_ready = [this] {
        if (!(codec.inspect(0, 3) & 0x80) || (codec.inspect(0, 8) & 0xc0) != 0xc0) return false;
        // Board profile: inferred 24.576 MHz codec MCLK, stock 48 kHz PLL and 32-bit I2S.
        if ((codec.inspect(0, 3) & 7) != 2 || codec.inspect(0, 4) != 0x20 || codec.inspect(0, 5) ||
            codec.inspect(0, 6) || codec.inspect(0, 2) || (codec.inspect(0, 9) & 0xf0) != 0x30)
            throw std::runtime_error("codec serial clock profile supports only stock 48 kHz 32-bit I2S");
        return true;
    };
    mcasp.pins_ready = [this](bool receive) {
        return (registers[PSC[1] + 0x81c] & 63) == 3 &&
            (registers[SYSCFG + 0x120] & 0xf0f0) == 0x1010 &&
            (registers[SYSCFG + 0x124] & (receive ? 0xf0 : 0xf00)) == (receive ? 0x10 : 0x100);
    };
    oled = Oled{};
    flash = {}; flash[0].configuration = 0x0f; selected_flash = -1;
    for (unsigned index = 0; index < SPI.size(); index++) {
        spi[index].reset();
        spi[index].pins_ready = [this, index](uint32_t word) { return spi_pins(index, word); };
        spi[index].deselect = [this, index](uint64_t cycle) {
            if (index == 0 && selected_flash >= 0) {
                flash[selected_flash].deselect(cycle); selected_flash = -1;
            }
        };
        spi[index].dma_request = [this, index](bool receive) { edma.event((index ? 18 : 14) + (receive ? 0 : 1)); };
        spi[index].exchange = [this, index](uint32_t word, uint64_t cycle) -> uint32_t {
            if (index == 0) {
                if ((spi[0].control(0x50 + ((word >> 24) & 3) * 4) & 31) != 8)
                    throw std::runtime_error("SPI NOR profile requires 8-bit transfers");
                uint32_t cs = (~(word >> 16)) & 3;
                if (cs == 3) throw std::runtime_error("multiple SPI NOR chip selects asserted");
                int target = cs == 1 ? 0 : cs == 2 ? 1 : -1;
                if (selected_flash >= 0 && selected_flash != target) flash[selected_flash].deselect(cycle);
                selected_flash = target;
                return target < 0 ? 255 : flash[target].exchange(uint8_t(word), cycle);
            }
            if ((word >> 16) & 1) return 255; // CS0 inactive.
            if ((spi[index].control(0x50 + ((word >> 24) & 3) * 4) & 31) != 8)
                throw std::runtime_error("OLED profile requires 8-bit SPI transfers");
            uint32_t dc = 1u << 11;
            if ((registers[GPIO + 0x38] & dc) || ((registers[SYSCFG + 0x134] >> 16) & 15) != 8)
                return 255; // No configured D/C output: the device does not receive a valid command/data level.
            oled.send(uint8_t(word), registers[GPIO + 0x3c] & dc, cycle);
            return 255; // write-only display; no SOMI connection is modeled.
        };
    }
    for (unsigned index = 0; index < UART.size(); index++) {
        uart[index].reset();
        uart[index].clock_running = [this, index] {
            uint32_t module = index ? PSC[1] + 0x800 + (11 + index) * 4 : PSC[0] + 0x824;
            return (registers[module] & 63) == 3;
        };
        uart[index].pins_ready = [this, index] {
            return index == 0 ? (registers[SYSCFG + 0x12c] & 0xff0000) == 0x220000
                             : index == 1 && (registers[SYSCFG + 0x130] & 0xff000000) == 0x22000000;
        };
        uart[index].interrupt = [this, index] { constexpr unsigned events[] = {38, 46, 61}; event(events[index]); };
        uart_sent[index].count = 0;
        uart[index].transmitted = [this, index](uint8_t byte, uint64_t cycle) { // disconnected, silent peer profile
            auto &sent = uart_sent[index]; size_t at = sent.count++ % sent.bytes.size();
            sent.bytes[at] = byte; sent.cycles[at] = cycle;
            if (index == 0 && midi.loopback) { uart[0].receive(byte) ? midi.looped++ : midi.ignored++; }
        };
    }
    midi = MidiIn{};
    gpio_scheduled.clear();
    gpio_trace = GpioTrace{}; gpio_trace.watch[3] = 1u << (16 + 9);
    gpio_inputs = {0, 0xd4010000, 0x05b50001, 0, 0};
    for (unsigned pair = 0; pair < 5; pair++) registers[GPIO + 0x10 + pair * 0x28] = 0xffffffff;
    // Bootloader handoff keeps GP4[11] (power hold) asserted.
    registers[GPIO + 0x60] &= ~(1u << 11); registers[GPIO + 0x64] = 1u << 11;
    for (unsigned index = 0; index < PSC.size(); index++) {
        uint32_t base = PSC[index], count = index ? 32 : 16;
        registers[base + 0x200] = registers[base + 0x204] = 1;
        registers[base + 0x300] = registers[base + 0x304] = 1;
        for (unsigned module = 0; module < count; module++) {
            // Default enabled interconnect/DSP/RAM plus DDR inherited from the loader.
            bool on = index ? module >= 24 || module == 6 || (gpio_handoff && module == 3) : module == 11 || module == 12 || module == 15;
            registers[base + 0xa00 + module * 4] = (on ? 3 : 0) | (index == 0 && module == 15 ? 0x100 : 0);
            registers[base + 0x800 + module * 4] = 0xb00 | (on ? 0x1403 : 0);
        }
    }
    registers[INTC + 0x104] = 0x07060504;
    registers[INTC + 0x108] = 0x0b0a0908;
    registers[INTC + 0x10c] = 0x0f0e0d0c;
    for (uint32_t i = 0; i < 4; i++) {
        registers[INTC + 0x80 + i * 4] = 0xffffffff;
        registers[INTC + 0xc0 + i * 4] = 0xffffffff;
    }
    // Handoff profile: the cache state the stock bootloader leaves, read on the unit (M1 bench B1):
    // L2 all SRAM (bits 16 and 24 are read-only identity), L1P and L1D fully cache, and these MAR bits.
    registers[CACHE] = 0x01010000; registers[CACHE + 0x20] = 4; registers[CACHE + 0x40] = 3;
    for (unsigned index : {17, 128, 192, 193, 194, 195, 199}) registers[CACHE + 0x8000 + index * 4] = 1;
    registers[SYSCFG + 0x38] = 0x83e70b13;
    registers[SYSCFG + 0x3c] = 0x95a4f1e0;
    registers[SYSCFG1 + 0xc] = 0xffffffff;
    registers[SYSCFG1 + 0x10] = 0xc3ffffff;
}
void Board::reserved_guard() const {
    auto value = [this](uint32_t address) { auto found = registers.find(address); return found == registers.end() ? 0u : found->second; };
    for (unsigned i = 0; i < 4; i++) if (value(INTC + 0xc0 + i * 4) != 0xffffffff)
        throw std::runtime_error("reserved-low write policy requires all exception events masked");
    // Conservatively reject event combiners and directly routed memory-system errors,
    // even if IER currently disables them. Later CPU IER writes then cannot expose an
    // unresolved event. This is a continuation policy, not a silicon bus-error model.
    for (unsigned i = 0; i < 12; i++) {
        uint32_t event = value(INTC + 0x104 + (i / 4) * 4) >> ((i % 4) * 8) & 127;
        if (event <= 3 || event >= 119)
            throw std::runtime_error("reserved-low write policy cannot expose unresolved interrupt routing");
    }
}
bool Board::reserved_write(uint32_t address, const uint8_t *data, uint32_t size, uint64_t cycle, uint32_t pc, bool guest) {
    if (!reserved_low_writes || address >= RESERVED_END) return false;
    if (!guest || pc == 0xfffffff0 || !size || size > 8 || uint64_t(address) + size > RESERVED_END)
        throw std::runtime_error("reserved-low policy supports CPU stores only, wholly below L2 ROM");
    reserved_guard();
    if (reserved_writes.size() >= 4096) throw std::runtime_error("reserved-low write trace capacity exceeded");
    uint64_t value = 0;
    for (unsigned i = 0; i < size; i++) value |= uint64_t(data[i]) << (i * 8);
    reserved_writes.push_back({cycle, value, pc, address, size});
    return true;
}
bool Board::contains(uint32_t address, uint32_t size) const {
    if (!enabled || !size || size > 4 || uint64_t(address) + size > 0x100000000ull) return false;
    return device(address, size);
}
bool Board::device_page(uint32_t base) const {
    for (uint32_t offset = 0; offset < 4096; offset++) if (device(base + offset, 1)) return true;
    return false;
}
bool Board::device(uint32_t address, uint32_t size) const {
    if ((address >= INTC && uint64_t(address) + size <= INTC + 0x200) ||
        (address >= CACHE && uint64_t(address) + size <= CACHE + 0x8400) ||
        (address >= SYSCFG && uint64_t(address) + size <= SYSCFG + 0x190) ||
        (address >= SYSCFG1 && uint64_t(address) + size <= SYSCFG1 + 0x1c) ||
        (address >= DDRC && uint64_t(address) + size <= uint64_t(DDRC) + 0x1000) ||
        (address >= EDMA && uint64_t(address) + size <= EDMA + 0x8000) ||
        (address >= MMCSD && uint64_t(address) + size <= MMCSD + 0x78) ||
        (address >= I2C0 && uint64_t(address) + size <= I2C0 + 0x60) ||
        (address >= USB0 && uint64_t(address) + size <= USB0 + 0x10000) ||
        (address >= MCASP0 && uint64_t(address) + size <= MCASP0 + 0x300) ||
        (address >= MCASP0 + 0x2000 && uint64_t(address) + size <= MCASP0 + 0x2004) ||
        (address >= GPIO && uint64_t(address) + size <= GPIO + 0xd8)) return true;
    for (auto base : TIMER) if (address >= base && uint64_t(address) + size <= base + 0x80) return true;
    for (auto base : PSC) if (address >= base && uint64_t(address) + size <= base + 0x1000) return true;
    for (auto base : SPI) if (address >= base && uint64_t(address) + size <= base + 0x80) return true;
    for (auto base : UART) if (address >= base && uint64_t(address) + size <= base + 0x38) return true;
    return false;
}
void Board::uart_receive(unsigned index, uint8_t byte) {
    if (!enabled || index >= UART.size()) throw std::runtime_error("invalid UART index");
    if (index == 1 && panel.enabled) throw std::runtime_error("UART1 input comes from the panel stream while it is on");
    uart[index].receive(byte);
    deadline = 0;
}
uint64_t Board::midi_character() const {
    uint64_t programmed = uart[0].character_cycles();
    return programmed ? programmed : MidiIn::CHARACTER_CYCLES;
}
void Board::midi_in(const uint8_t *data, size_t size, uint64_t cycle) {
    if (!enabled) throw std::runtime_error("MIDI IN needs the board");
    if (midi.loopback) throw std::runtime_error("MIDI IN is cabled to MIDI OUT while the loopback is on");
    if (size > MidiIn::CAPACITY - midi.queue.size()) throw std::runtime_error("MIDI IN queue is full (1 MiB)");
    if (!size) return;
    if (midi.queue.empty()) midi.next = cycle + midi_character();
    midi.queue.insert(midi.queue.end(), data, data + size);
    deadline = 0;
}
void Board::midi_loopback(bool on) {
    if (!enabled) throw std::runtime_error("the MIDI loopback needs the board");
    if (on && !midi.queue.empty()) throw std::runtime_error("MIDI IN still has queued bytes to deliver");
    midi.loopback = on;
}
void Board::gpio_schedule(unsigned bank, unsigned pin, bool high, uint64_t cycle, uint64_t now) {
    if (!enabled || bank > 8 || pin > 15) throw std::runtime_error("invalid GPIO input");
    if (cycle < now) throw std::runtime_error("GPIO edge is scheduled in the past");
    if (gpio_scheduled.size() >= 65536) throw std::runtime_error("too many scheduled GPIO edges (65536)");
    auto after = std::upper_bound(gpio_scheduled.begin(), gpio_scheduled.end(), cycle,
                                  [](uint64_t at, const GpioEdge &edge) { return at < edge.cycle; });
    gpio_scheduled.insert(after, GpioEdge{cycle, uint8_t(bank), uint8_t(pin), high});
    deadline = 0;
}
void Board::gpio_schedule_clear(unsigned bank, unsigned pin) {
    if (!enabled || bank > 8 || pin > 15) throw std::runtime_error("invalid GPIO input");
    std::erase_if(gpio_scheduled, [=](const GpioEdge &edge) { return edge.bank == bank && edge.pin == pin; });
    deadline = 0;
}
Board::Driven Board::gpio_driven(unsigned pair) const {
    auto value = [this](uint32_t address) { auto it = registers.find(address); return it == registers.end() ? 0u : it->second; };
    uint32_t base = GPIO + 0x10 + pair * 0x28, outputs = ~value(base);
    if (pair == 4) outputs &= 0xffff;
    if (pair == 3 && (value(SYSCFG + 0x164) & 15) != 8) outputs &= ~(1u << (16 + 9)); // GP7[9] is not on its pin
    return {outputs, value(base + 4) & outputs};
}
void Board::gpio_record(unsigned pair, Driven previous, uint64_t cycle) {
    Driven now = gpio_driven(pair);
    uint32_t changed = gpio_trace.watch[pair] & now.outputs & (~previous.outputs | (now.levels ^ previous.levels));
    for (unsigned bit = 0; changed; bit++, changed >>= 1) if (changed & 1)
        gpio_trace.rows[gpio_trace.count++ % gpio_trace.rows.size()] =
            GpioChange{cycle, uint8_t(pair * 2 + bit / 16), uint8_t(bit % 16), (now.levels >> bit & 1) != 0};
}
void Board::gpio_watch(unsigned bank, unsigned pin, bool on, uint64_t cycle) {
    if (!enabled || bank > 8 || pin > 15) throw std::runtime_error("invalid GPIO pin");
    uint32_t mask = 1u << ((bank % 2) * 16 + pin), &watch = gpio_trace.watch[bank / 2];
    if (!on) { watch &= ~mask; return; }
    if (watch & mask) return;
    Driven before = gpio_driven(bank / 2); before.outputs &= ~mask; // a pin already driving starts with its level
    watch |= mask; gpio_record(bank / 2, before, cycle);
}
void Board::panel_stream(bool on, uint64_t cycle) {
    if (!enabled) throw std::runtime_error("the panel stream needs the board");
    if (on == panel.enabled) return;
    panel.enabled = on; panel.position = 0;
    panel.next = panel.message_start = on ? cycle + PanelStream::MESSAGE_CYCLES : UINT64_MAX;
    deadline = 0;
}
void Board::panel_level(unsigned channel, uint32_t value) {
    if (!enabled || channel > 15 || value > 16383) throw std::runtime_error("invalid panel channel or level");
    panel.levels[channel] = uint16_t(value);
}
bool Board::spi_pins(unsigned index, uint32_t word) {
    uint32_t selected = (~(word >> 16)) & (index ? 1 : 3);
    uint32_t required = (index ? 0x600 : 0xe00) | selected;
    if ((spi[index].control(0x14) & required) != required) return false;
    if (index == 0) return (registers[SYSCFG + 0x12c] & 0xffff) == 0x1111 && (registers[SYSCFG + 0x130] & 255) == 0x11;
    return (registers[SYSCFG + 0x134] & 0xf00ff0) == 0x100110;
}
void Board::gpio_input(unsigned bank, unsigned pin, bool high) {
    if (!enabled || bank > 8 || pin > 15) throw std::runtime_error("invalid GPIO input");
    deadline = 0;
    uint32_t mask = 1u << ((bank % 2) * 16 + pin), &inputs = gpio_inputs[bank / 2];
    uint32_t previous = gpio_levels(bank / 2);
    if (high) inputs |= mask; else inputs &= ~mask;
    gpio_edges(bank / 2, previous);
}
uint32_t Board::gpio_levels(unsigned pair) const {
    auto value = [this](uint32_t address) { auto it = registers.find(address); return it == registers.end() ? 0u : it->second; };
    uint32_t base = GPIO + 0x10 + pair * 0x28, inputs = gpio_inputs[pair];
    if (keys_down && pair == 1) {
        // Rows GP2[0..5], columns GP3[1..6,9,11]. Ideal switches, no contact bounce/ghosting.
        uint32_t rows = value(base + 4) & ~value(base) & 63;
        uint32_t columns = 0, row_mux = value(SYSCFG + 0x138);
        for (unsigned row = 0; row < 6; row++) if ((rows & (1u << row)) && ((row_mux >> ((7 - row) * 4)) & 15) == 8)
            columns |= uint32_t(keys_down >> (row * 8)) & (row ? 255u : 239u); // Key 4 is a separate pin.
        for (unsigned column = 0; column < 8; column++) if (columns & (1u << column)) {
            unsigned pin = column < 6 ? column + 1 : column == 6 ? 9 : 11;
            // SPRS590G 3.6: PINMUX selects output drivers, not peripheral input paths.
            // In particular stock leaves column 6 (GP3[9]) at its tri-state reset mux.
            inputs |= 1u << (16 + pin);
        }
    }
    if (pair == 2 && (keys_down & 16))
        inputs &= ~(1u << 26); // Key 4: GP5[10], active low, independent of selected row.
    return (inputs & value(base)) | (value(base + 4) & ~value(base));
}
void Board::gpio_edges(unsigned pair, uint32_t previous) {
    uint32_t base = GPIO + 0x10 + pair * 0x28, levels = gpio_levels(pair);
    uint32_t changed = (levels ^ previous) & registers[base];
    uint32_t edges = changed & ((levels & registers[base + 0x14]) | (~levels & registers[base + 0x1c]));
    for (unsigned half = 0; half < (pair == 4 ? 1u : 2u); half++) {
        unsigned bank = pair * 2 + half;
        uint32_t mask = edges & (0xffffu << (half * 16));
        bool pending = registers[base + 0x24] & (0xffffu << (half * 16));
        registers[base + 0x24] |= mask;
        if (mask && !pending && (registers[GPIO + 8] & (1u << bank))) {
            constexpr unsigned events[] = {65, 41, 49, 52, 54, 59, 62, 72, 75};
            event(events[bank]);
        }
    }
}
void Board::key_input(unsigned key, bool down) {
    if (!enabled || key >= 48) throw std::runtime_error("key index must be 0..47");
    uint32_t previous1 = gpio_levels(1), previous2 = gpio_levels(2);
    if (down) keys_down |= uint64_t(1) << key; else keys_down &= ~(uint64_t(1) << key);
    gpio_edges(1, previous1); gpio_edges(2, previous2); deadline = 0;
}
void Board::complete_psc(unsigned index) {
    uint32_t base = PSC[index], count = index ? 32 : 16, domains = registers[base + 0x128];
    for (unsigned module = 0; module < count; module++) {
        unsigned domain = module == count - 1 ? 1 : 0;
        if (!(domains & (1u << domain))) continue;
        uint32_t next = registers[base + 0xa00 + module * 4] & 7;
        registers[base + 0x800 + module * 4] = 0xb00 | next |
            (next == 1 || next == 3 ? 0x1000 : 0) | (next == 2 || next == 3 ? 0x400 : 0);
    }
    registers[base + 0x128] = 0; psc_deadline[index] = UINT64_MAX;
}
void Board::event(unsigned number) {
    if (number >= 128) throw std::runtime_error("invalid DSP event");
    registers[INTC + (number / 32) * 4] |= 1u << (number % 32);
    for (unsigned interrupt = 4; interrupt < 16; interrupt++) {
        uint32_t mux = registers[INTC + 0x104 + ((interrupt - 4) / 4) * 4];
        if (((mux >> (((interrupt - 4) % 4) * 8)) & 127) == number) pending_interrupts |= 1u << interrupt;
    }
}
void Board::schedule_timer(unsigned index, uint64_t cycle) {
    auto base = TIMER[index]; auto &timer = timers[index];
    uint32_t mode = registers[base + 0x20] >> 6 & 3;
    uint32_t global = registers[base + 0x24];
    uint32_t period = registers[base + 0x18];
    uint64_t numerator = index < 2 ? 2 : 1, denominator = index < 2 ? 31 : 2;
    if (!(global >> 2 & 3)) { // 64-bit general-purpose timer: TIM34:TIM12 counts to PRD34:PRD12.
        uint64_t period64 = uint64_t(registers[base + 0x1c]) << 32 | period;
        uint64_t counter = uint64_t(registers[base + 0x14]) << 32 | registers[base + 0x10];
        uint64_t needed = counter < period64 ? period64 - counter : period64 == UINT64_MAX ? UINT64_MAX : period64 + 1;
        if (!mode || (global & 3) != 3 || !period64 || needed > (uint64_t(1) << 56)) {
            timer.deadline = UINT64_MAX; return; // a match further off than any run (2^56 ticks) is not scheduled
        }
        timer.deadline = cycle + (needed * denominator - timer.fraction + numerator - 1) / numerator;
        return;
    }
    if (!mode || !(global & 1) || !period) { timer.deadline = UINT64_MAX; return; }
    if ((global >> 2 & 3) != 1) throw std::runtime_error("timer modes other than 64-bit general-purpose and dual 32-bit unchained are not implemented");
    uint64_t counter = registers[base + 0x10];
    uint64_t needed = counter < period ? period - counter : uint64_t(period) + 1;
    timer.deadline = cycle + (needed * denominator - timer.fraction + numerator - 1) / numerator;
}
void Board::update_timer(unsigned index, uint64_t cycle) {
    auto base = TIMER[index]; auto &timer = timers[index];
    if (cycle < timer.last) { timer.last = cycle; timer.fraction = 0; }
    uint32_t mode = registers[base + 0x20] >> 6 & 3;
    uint32_t period = registers[base + 0x18];
    uint64_t numerator = index < 2 ? 2 : 1, denominator = index < 2 ? 31 : 2;
    if (!(registers[base + 0x24] >> 2 & 3)) { // 64-bit general-purpose timer
        uint64_t period64 = uint64_t(registers[base + 0x1c]) << 32 | period;
        if (!mode || (registers[base + 0x24] & 3) != 3 || !period64) { timer.last = cycle; return; }
        if (mode == 3) throw std::runtime_error("timer continuous reload is not implemented");
        uint64_t elapsed = (cycle - timer.last) * numerator + timer.fraction;
        uint64_t ticks = elapsed / denominator; timer.fraction = elapsed % denominator; timer.last = cycle;
        uint64_t old = uint64_t(registers[base + 0x14]) << 32 | registers[base + 0x10];
        uint64_t total = old + ticks; // no wrap: a run is far shorter than 2^64 ticks, and a counter at its period restarts
        bool one_shot = false;
        if (ticks && (old < period64 ? total >= period64 : total - period64 > period64)) {
            registers[base + 0x44] |= 2;
            if (!(registers[base + 0x24] & 0x10) || (registers[base + 0x44] & 1)) event(TIMER_EVENT[index]);
            if (mode == 1) { registers[base + 0x20] &= ~0xc0u; total = period64; one_shot = true; }
        }
        if (!one_shot && period64 != UINT64_MAX) total %= period64 + 1;
        registers[base + 0x10] = uint32_t(total); registers[base + 0x14] = uint32_t(total >> 32);
        schedule_timer(index, cycle);
        return;
    }
    if (!mode || !(registers[base + 0x24] & 1) || !period) { timer.last = cycle; return; }
    uint64_t elapsed = (cycle - timer.last) * numerator + timer.fraction;
    uint64_t ticks = elapsed / denominator; timer.fraction = elapsed % denominator; timer.last = cycle;
    uint64_t old = registers[base + 0x10], total = old + ticks;
    if (ticks && (old < period ? total >= period : total >= uint64_t(period) * 2 + 1)) {
        registers[base + 0x44] |= 2;
        if (!(registers[base + 0x24] & 0x10) || (registers[base + 0x44] & 1)) event(TIMER_EVENT[index]);
        if (mode == 1) { registers[base + 0x20] &= ~0xc0u; total = period; }
        else if (mode == 3) throw std::runtime_error("timer continuous reload is not implemented");
    }
    registers[base + 0x10] = mode == 1 ? uint32_t(total) : uint32_t(total % (uint64_t(period) + 1));
    schedule_timer(index, cycle);
}
void Board::advance(uint64_t cycle) {
    if (!enabled || (!eager_polling && cycle < deadline)) return;
    for (unsigned i = 0; i < timers.size(); i++) if (cycle >= timers[i].deadline) update_timer(i, cycle);
    for (unsigned i = 0; i < PSC.size(); i++) if (cycle >= psc_deadline[i]) {
        // Preserve the MMC engine's stopped-clock accounting through the transition edge.
        if (cycle) mmcsd.advance(cycle - 1);
        complete_psc(i);
    }
    for (auto &controller : spi) controller.advance(cycle);
    while (cycle >= panel.next) {
        unsigned channel = PanelStream::ORDER[panel.position / 3], part = panel.position % 3;
        if (!part) panel.sending = panel.levels[channel];
        uart[1].receive(uint8_t(part == 0 ? 0xb0 | channel : part == 1 ? panel.sending & 0x7f : panel.sending >> 7));
        if (part == 2) { panel.messages++; panel.next = panel.message_start += PanelStream::MESSAGE_CYCLES; }
        else panel.next += std::min<uint64_t>(std::max<uint64_t>(uart[1].character_cycles(), 1), PanelStream::MESSAGE_CYCLES / 3);
        panel.position = (panel.position + 1) % 48;
    }
    while (!gpio_scheduled.empty() && cycle >= gpio_scheduled.front().cycle) {
        GpioEdge edge = gpio_scheduled.front(); gpio_scheduled.pop_front();
        gpio_input(edge.bank, edge.pin, edge.high);
    }
    while (cycle >= midi.next) {
        uint8_t byte = midi.queue.front(); midi.queue.pop_front();
        uart[0].receive(byte) ? midi.delivered++ : midi.ignored++;
        midi.next = midi.queue.empty() ? UINT64_MAX : midi.next + midi_character();
    }
    for (auto &controller : uart) controller.advance(cycle);
    mmcsd.advance(cycle);
    i2c.advance(cycle);
    mcasp.advance(cycle);
    usb.advance(cycle);
    edma.service();
    deadline = UINT64_MAX;
    for (const auto &timer : timers) deadline = std::min(deadline, timer.deadline);
    for (auto at : psc_deadline) deadline = std::min(deadline, at);
    for (const auto &controller : spi) deadline = std::min(deadline, controller.next_event());
    for (const auto &controller : uart) deadline = std::min(deadline, controller.next_event());
    deadline = std::min({deadline, panel.next, midi.next});
    if (!gpio_scheduled.empty()) deadline = std::min(deadline, gpio_scheduled.front().cycle);
    deadline = std::min({deadline, mmcsd.next_event(), i2c.next_event(), mcasp.next_event(), usb.next_event()});
}
void Board::record(uint32_t address, uint32_t value, uint32_t size, bool write, uint64_t cycle, uint32_t pc) {
    log[accesses++ % log.size()] = BoardAccess{cycle, pc, address, value, size, uint32_t(write)};
    if (!capture.on || (!write && capture.writes_only)) return;
    bool wanted = false;
    for (auto [start, end] : capture.ranges) if (address >= start && address < end) { wanted = true; break; }
    if (!wanted) return;
    if (!write && !capture.rows.empty()) {
        auto &last = capture.rows.back();
        if (!last.write && last.pc == pc && last.address == address && last.value == value && last.size == size) {
            last.repeat++; return;
        }
    }
    if (capture.rows.size() >= capture.limit) { capture.dropped++; return; }
    capture.rows.push_back({cycle, pc, address, value, size, uint32_t(write), 1});
    capture.recorded++;
}
uint32_t Board::read_word(uint32_t address, uint64_t cycle) {
    advance(cycle);
    // SYS/BIOS Cache_wait performs a dummy write/read of EMIFB_CFG to drain DDR writes.
    // RAM is coherent, so the barrier is already complete. These two registers are read-only.
    if (address == DDRC) return 0x40311b1f;
    if (address == DDRC + 4) return 0x40000004; // asynchronous clocks; inherited PHY ready.
    if (address >= DDRC && address < DDRC + 0x1000) throw unknown(address);
    if (address == SYSCFG1 + 0xc || address == SYSCFG1 + 0x10) return registers[address];
    if (address >= SYSCFG1 && address < SYSCFG1 + 0x1c) throw unknown(address);
    for (unsigned index = 0; index < UART.size(); index++) if (address >= UART[index] && address < UART[index] + 0x38) {
        // The stock driver disables PWREMU before enabling the module's functional clock.
        // Keep the configuration plane accessible; serial shifting is clock-gated.
        return uart[index].read(address - UART[index], cycle);
    }
    if (address >= EDMA && address < EDMA + 0x8000) {
        if ((registers[PSC[0] + 0x800] & 63) != 3) throw std::runtime_error("EDMA CC0 module is not enabled in PSC0");
        return edma.read(address - EDMA);
    }
    if (address >= GPIO && address < GPIO + 0xd8) {
        if ((registers[PSC[1] + 0x80c] & 63) != 3) throw std::runtime_error("GPIO module is not enabled in PSC1");
        uint32_t off = address - GPIO;
        if (off == 8) return registers[address];
        if (off < 0x10 || off & 3) throw unknown(address);
        unsigned pair = (off - 0x10) / 0x28, reg = (off - 0x10) % 0x28;
        uint32_t base = GPIO + 0x10 + pair * 0x28;
        if (reg == 8 || reg == 12) return registers[base + 4];
        if (reg == 0x10) return gpio_levels(pair);
        if (reg == 0x18 || reg == 0x20) return registers[base + reg - 4];
        return registers[address];
    }
    for (unsigned index = 0; index < PSC.size(); index++) if (address >= PSC[index] && address < PSC[index] + 0x1000) {
        uint32_t off = address - PSC[index], count = index ? 32 : 16;
        if (off == 0x120 || off == 0x128 || off == 0x200 || off == 0x204 || off == 0x300 || off == 0x304 ||
            (off >= 0x800 && off < 0x800 + count * 4 && !(off & 3)) ||
            (off >= 0xa00 && off < 0xa00 + count * 4 && !(off & 3))) return registers[address];
        throw unknown(address);
    }
    if (address >= SYSCFG && address < SYSCFG + 0x190) {
        if (address == SYSCFG + 0x184) return usb.phy_value(cycle);
        if (syscfg(address - SYSCFG)) return registers[address];
        throw unknown(address);
    }
    for (unsigned i = 0; i < TIMER.size(); i++) if (address >= TIMER[i] && address < TIMER[i] + 0x80) {
        if (!timer_register(address - TIMER[i])) throw unknown(address);
        update_timer(i, cycle); return registers[address];
    }
    uint32_t off = address - INTC;
    if (off < 0x200) {
        // After a discarded low store the event flags read as before: on the unit EVTFLAG0-3, EFR and IERR
        // were unchanged by STW, STH and STB at 0x0, 0x10 and 0x200 (bench M2, LOWW).
        if (group(off, 0) || group(off, 0x80) || group(off, 0xc0) || (0x104 <= off && off <= 0x10c && !(off & 3)))
            return registers[address];
        if (group(off, 0x20) || group(off, 0x40)) return 0;
        if (group(off, 0xa0)) return registers[INTC + off - 0xa0] & ~registers[INTC + off - 0x20];
        if (group(off, 0xe0)) return registers[INTC + off - 0xe0] & ~registers[INTC + off - 0x20];
        throw unknown(address);
    }
    off = address - CACHE;
    if (off == 0 || off == 0x20 || off == 0x24 || off == 0x40 || off == 0x44 || cache_base(off)) return registers[address];
    if (cache_base(off - 4) || cache_command(off)) return 0; // coherent memory: maintenance completes immediately
    if (0x8000 <= off && off < 0x8400 && !(off & 3)) return registers[address];
    throw unknown(address);
}
void Board::write_word(uint32_t address, uint32_t value, uint64_t cycle) {
    advance(cycle);
    if (address == DDRC || address == DDRC + 4) return;
    if (address >= DDRC && address < DDRC + 0x1000) throw unknown(address);
    if (address == SYSCFG1 + 0xc || address == SYSCFG1 + 0x10) { registers[address] = value; return; }
    if (address >= SYSCFG1 && address < SYSCFG1 + 0x1c) throw unknown(address);
    for (unsigned index = 0; index < UART.size(); index++) if (address >= UART[index] && address < UART[index] + 0x38) {
        uart[index].write(address - UART[index], value, cycle); return;
    }
    if (address >= EDMA && address < EDMA + 0x8000) {
        if ((registers[PSC[0] + 0x800] & 63) != 3) throw std::runtime_error("EDMA CC0 module is not enabled in PSC0");
        edma.write(address - EDMA, value); return;
    }
    if (address >= GPIO && address < GPIO + 0xd8) {
        if ((registers[PSC[1] + 0x80c] & 63) != 3) throw std::runtime_error("GPIO module is not enabled in PSC1");
        uint32_t off = address - GPIO;
        if (off == 8) { registers[address] = value & 0x1ff; return; }
        if (off < 0x10 || off & 3) throw unknown(address);
        unsigned pair = (off - 0x10) / 0x28, reg = (off - 0x10) % 0x28;
        uint32_t base = GPIO + 0x10 + pair * 0x28;
        uint32_t previous = gpio_levels(pair);
        Driven driven = gpio_driven(pair);
        if (pair == 4) value &= 0xffff;
        if (reg == 0x10) throw std::runtime_error("GPIO IN_DATA is read-only");
        if (reg == 8 || reg == 0x14 || reg == 0x1c) registers[base + (reg == 8 ? 4 : reg)] |= value;
        else if (reg == 12 || reg == 0x18 || reg == 0x20) registers[base + (reg == 12 ? 4 : reg - 4)] &= ~value;
        else if (reg == 0x24) registers[address] &= ~value;
        else registers[address] = value;
        gpio_edges(pair, previous);
        gpio_record(pair, driven, cycle);
        return;
    }
    for (unsigned index = 0; index < PSC.size(); index++) if (address >= PSC[index] && address < PSC[index] + 0x1000) {
        uint32_t base = PSC[index], off = address - base, count = index ? 32 : 16;
        if (off >= 0xa00 && off < 0xa00 + count * 4 && !(off & 3)) {
            if ((value & 7) > 3) throw std::runtime_error("PSC automatic sleep/wake is not implemented");
            registers[address] = value & (index ? 0x80000007 : 0x80000707); return;
        }
        if (off == 0x120) {
            registers[base + 0x128] |= value & 3;
            // Functional transition latency, not a measurement of the physical PSC.
            if (value & 3) psc_deadline[index] = cycle + 16;
            return;
        }
        if (off == 0x300 || off == 0x304) {
            if (!(value & 1)) throw std::runtime_error("PSC power-domain shutdown is not implemented");
            registers[address] = value; return;
        }
        throw unknown(address);
    }
    if (address >= SYSCFG && address < SYSCFG + 0x190) {
        auto off = address - SYSCFG;
        if (!syscfg(off)) throw unknown(address);
        if (off == 0x38 || off == 0x3c) { registers[address] = value; return; }
        if (registers[SYSCFG + 0x38] != 0x83e70b13 || registers[SYSCFG + 0x3c] != 0x95a4f1e0) return;
        if (off == 0x184) { usb.configure_phy(value, cycle); registers[address] = value & 0xffff; return; }
        uint32_t previous1 = 0, previous2 = 0;
        bool matrix_mux = keys_down && (off == 0x138 || off == 0x13c || off == 0x140 || off == 0x14c);
        if (matrix_mux) { previous1 = gpio_levels(1); previous2 = gpio_levels(2); }
        Driven driven = gpio_driven(3);
        if (off == 0x178) registers[SYSCFG + 0x174] &= ~value;
        else if (off == 0x174) registers[address] |= value;
        else registers[address] = value;
        if (matrix_mux) { gpio_edges(1, previous1); gpio_edges(2, previous2); }
        if (off == 0x164) gpio_record(3, driven, cycle);
        return;
    }
    for (unsigned i = 0; i < TIMER.size(); i++) if (address >= TIMER[i] && address < TIMER[i] + 0x80) {
        auto off = address - TIMER[i];
        if (!timer_register(off)) throw unknown(address);
        update_timer(i, cycle);
        if (off == 0x44) registers[address] = (value & 0x50005u) | (registers[address] & ~(value & 0xa000au) & 0xa000au);
        else registers[address] = value;
        if (off == 0x24 && !(value & 1)) { registers[TIMER[i] + 0x10] = 0; timers[i].fraction = 0; }
        if (off == 0x24 && !(value & 2)) registers[TIMER[i] + 0x14] = 0; // TIM34 held in reset
        schedule_timer(i, cycle); return;
    }
    uint32_t off = address - INTC;
    if (off < 0x200) {
        if (group(off, 0x20)) {
            for (unsigned bit = 0; bit < 32; bit++) if (value & (1u << bit)) event(((off - 0x20) / 4) * 32 + bit);
            return;
        }
        if (group(off, 0x40)) { registers[INTC + off - 0x40] &= ~value; return; }
        if (group(off, 0x80) || group(off, 0xc0) || (0x104 <= off && off <= 0x10c && !(off & 3))) {
            uint32_t previous = registers[address];
            registers[address] = off >= 0x104 ? value & 0x7f7f7f7f : value;
            if (!reserved_writes.empty()) {
                try { reserved_guard(); }
                catch (...) { registers[address] = previous; throw; }
            }
            return;
        }
        throw unknown(address);
    }
    off = address - CACHE;
    if (off == 0 || off == 0x20 || off == 0x40) { registers[address] = (value & 7) | (off ? 0 : 0x01010000); return; }
    if (off == 0x24 || off == 0x44) { registers[address] = (value & 1) | ((registers[address] & 1) << 16); return; }
    if (cache_base(off)) { registers[address] = value & ~3u; return; }
    if (cache_base(off - 4) || cache_command(off)) return;
    if (0x8000 <= off && off < 0x8400 && !(off & 3)) { registers[address] = value & 9; return; }
    throw unknown(address);
}
uint32_t Board::read(uint32_t address, uint32_t size, uint64_t cycle, uint32_t pc, bool trace) {
    if (!contains(address, size) || (address & 3) + size > 4) throw unknown(address);
    InvalidateDeadline changed{deadline};
    deadline = 0; // reads can consume FIFOs, acknowledge flags, or generate DMA requests
    if (address == USB0 + 0x80c || address == USB0 + 0x84c) {
        // Not documented registers (StarterWare reads them as Stellaris status words). The unit read 0 at
        // both with no exception or event flag: M1 bench I5, USB0 clocked, PHY ready, no host attached.
        if (!trace || pc == 0xfffffff0 || size != 4)
            throw std::runtime_error("USB reserved words are measured for aligned 32-bit CPU reads only");
        advance(cycle);
        if (!usb.clock_running() || !usb.phy_ready)
            throw std::runtime_error("USB reserved words are measured only with USB0 clocked and its PHY ready");
        usb_reserved_count++;
        if (usb_reserved_reads.size() < 4096) usb_reserved_reads.push_back({cycle, 0, pc, address, size});
        record(address, 0, size, false, cycle, pc);
        return 0;
    }
    if (address >= USB0 && address < USB0 + 0x10000) {
        uint32_t value = usb.read(address - USB0, size, cycle);
        if (trace) record(address, value, size, false, cycle, pc);
        return value;
    }
    if (address >= MCASP0 && address < MCASP0 + 0x2004) {
        uint32_t value = mcasp.read(address - MCASP0, size, cycle);
        if (trace) record(address, value, size, false, cycle, pc);
        return value;
    }
    if (address >= I2C0 && address < I2C0 + 0x60) {
        uint32_t value = i2c.read(address - I2C0, size, cycle);
        if (trace) record(address, value, size, false, cycle, pc);
        return value;
    }
    if (address >= MMCSD && address < MMCSD + 0x78) {
        uint32_t value = mmcsd.read(address - MMCSD, size, cycle);
        if (trace) record(address, value, size, false, cycle, pc);
        return value;
    }
    for (unsigned index = 0; index < SPI.size(); index++) if (address >= SPI[index] && address < SPI[index] + 0x80) {
        uint32_t module = index ? PSC[1] + 0x828 : PSC[0] + 0x810;
        if ((registers[module] & 63) != 3) throw std::runtime_error("SPI module is not enabled in PSC");
        uint32_t value = spi[index].read(address - SPI[index], size, cycle);
        if (trace) record(address, value, size, false, cycle, pc);
        return value;
    }
    uint32_t value = read_word(address & ~3u, cycle) >> ((address & 3) * 8);
    if (size < 4) value &= (1u << (size * 8)) - 1;
    if (trace) record(address, value, size, false, cycle, pc);
    return value;
}
void Board::write(uint32_t address, uint32_t value, uint32_t size, uint64_t cycle, uint32_t pc, bool trace) {
    if (!contains(address, size) || (address & 3) + size > 4) throw unknown(address);
    InvalidateDeadline changed{deadline};
    deadline = 0;
    if (address == USB0 + 0x808 || address == USB0 + 0x848) {
        // The matching interrupt-disable words: a store of 0 changed nothing on the unit (M1 bench I5).
        if (!trace || pc == 0xfffffff0 || size != 4 || value)
            throw std::runtime_error("USB reserved words are measured for aligned 32-bit CPU stores of 0 only");
        advance(cycle);
        if (!usb.clock_running() || !usb.phy_ready)
            throw std::runtime_error("USB reserved words are measured only with USB0 clocked and its PHY ready");
        record(address, value, size, true, cycle, pc);
        usb_reserved_count++;
        if (usb_reserved_reads.size() < 4096) usb_reserved_reads.push_back({cycle, 0, pc, address, size});
        return;
    }
    if (trace) record(address, value, size, true, cycle, pc);
    if (address >= USB0 && address < USB0 + 0x10000) { usb.write(address - USB0, value, size, cycle); return; }
    if (address >= MCASP0 && address < MCASP0 + 0x2004) {
        mcasp.write(address - MCASP0, value, size, cycle); return;
    }
    if (address >= I2C0 && address < I2C0 + 0x60) {
        i2c.write(address - I2C0, value, size, cycle); return;
    }
    if (address >= MMCSD && address < MMCSD + 0x78) {
        mmcsd.write(address - MMCSD, value, size, cycle); return;
    }
    for (auto base : UART) if (address >= base && address < base + 0x38) {
        uint32_t offset = address - base;
        if ((offset & ~3u) == 0x30 && size < 4) {
            uint32_t shift = (offset & 3) * 8, mask = ((1u << (size * 8)) - 1) << shift;
            value = (read_word(address & ~3u, cycle) & ~mask) | ((value << shift) & mask);
        } else if (offset & 3) return;
        // THR and RBR share an address. Never read RBR to synthesize a byte write.
        write_word(address & ~3u, value, cycle); return;
    }
    for (unsigned index = 0; index < SPI.size(); index++) if (address >= SPI[index] && address < SPI[index] + 0x80) {
        uint32_t module = index ? PSC[1] + 0x828 : PSC[0] + 0x810;
        if ((registers[module] & 63) != 3) throw std::runtime_error("SPI module is not enabled in PSC");
        spi[index].write(address - SPI[index], value, size, cycle);
        return;
    }
    if (size == 4) write_word(address, value, cycle);
    else {
        uint32_t shift = (address & 3) * 8, mask = ((1u << (size * 8)) - 1) << shift;
        write_word(address & ~3u, (read_word(address & ~3u, cycle) & ~mask) | ((value << shift) & mask), cycle);
    }
}
BoardAccess Board::access(uint64_t sequence) const {
    if (sequence >= accesses || sequence + log.size() < accesses) throw std::runtime_error("MMIO trace entry expired");
    return log[sequence % log.size()];
}
