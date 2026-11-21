#ifndef SMPLTREK_EMULATOR_CORE_H
#define SMPLTREK_EMULATOR_CORE_H
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Fixed-width C ABI. Python supplies decoded packets only on cache misses. */
enum c6_status { C6_BUDGET = 0, C6_DECODE = 1, C6_RETURNED = 2, C6_FAULT = 3, C6_BREAKPOINT = 4 };
enum c6_permission { C6_READ = 1, C6_WRITE = 2, C6_EXECUTE = 4 };
enum c6_operand_kind { C6_IMMEDIATE = 0, C6_REGISTER = 1, C6_MEMORY = 2, C6_PAIR = 3 };
enum c6_memory_flag { C6_SCALED = 1, C6_PRE = 2, C6_POST = 4, C6_MINUS = 8 };
enum c6_opcode {
    C6_UNSUPPORTED, C6_NOP, C6_MVK, C6_MVKH, C6_MV, C6_MVC, C6_MVD, C6_ZERO,
    C6_ADD, C6_ADDK, C6_SUB, C6_AND, C6_OR, C6_XOR, C6_ANDN, C6_SHL, C6_SHR, C6_SHRU,
    C6_CMPEQ, C6_CMPGT, C6_CMPLT, C6_CMPGTU, C6_CMPLTU, C6_SET, C6_CLR, C6_EXT, C6_EXTU,
    C6_LDW, C6_LDH, C6_LDHU, C6_LDB, C6_LDBU, C6_LDDW, C6_LDNW, C6_LDNDW,
    C6_STW, C6_STH, C6_STB, C6_STDW, C6_STNW, C6_STNDW,
    C6_B, C6_BNOP, C6_CALLP, C6_ADDKPC,
    C6_ADDAB, C6_ADDAH, C6_ADDAW, C6_ADDAD, C6_SUBAB, C6_SUBAH, C6_SUBAW,
    C6_MPY, C6_MPYU, C6_MPYSU, C6_MPYUS, C6_MPY32, C6_MPY32U, C6_MPY32SU, C6_MPY32US,
    C6_MPYLI, C6_ROTL, C6_LMBD, C6_NORM, C6_ABS, C6_SUBC,
    C6_PACK2, C6_PACKHL2, C6_PACKLH2, C6_PACKL4, C6_SSHL, C6_NOT, C6_NEG,
    C6_SPLOOP, C6_SPLOOPD, C6_SPLOOPW, C6_SPKERNEL, C6_SPKERNELR, C6_SPMASK, C6_SPMASKR,
    C6_DINT, C6_RINT, C6_SUBU, C6_ADDU, C6_SAT, C6_ADDSUB, C6_MPYHI, C6_SHR2,
    C6_ADDSP, C6_SUBSP, C6_MPYSP, C6_INTSP, C6_INTSPU, C6_SPTRUNC, C6_SPINT,
    C6_CMPEQSP, C6_CMPGTSP, C6_CMPLTSP, C6_ABSSP, C6_RCPSP, C6_RSQRSP,
    C6_SPDP, C6_MPYSP2DP, C6_MPYSPDP, C6_MPYDP, C6_ADDDP, C6_SUBDP,
    C6_INTDP, C6_INTDPU, C6_DPTRUNC, C6_DPINT, C6_DPSP, C6_CMPEQDP, C6_CMPGTDP,
    C6_CMPLTDP, C6_ABSDP, C6_RCPDP, C6_BDEC, C6_BPOS, C6_DMV, C6_SWE, C6_MAXU4, C6_MINU4,
    C6_MPYLH, C6_MPYLHU, C6_DOTP2, C6_MPY2, C6_DPACK2,
    C6_MPYH, C6_MPYHU, C6_MPYHUS, C6_MPYHSU, C6_MPYHL, C6_MPYHLU, C6_MPYHULS, C6_MPYHSLU, C6_MPYLUHS, C6_MPYLSHU,
    C6_SMPY, C6_SMPYH, C6_SMPYHL, C6_SMPYLH, C6_SMPY2, C6_SADD, C6_SSUB,
    C6_ADD2, C6_SUB2, C6_ADD4, C6_SUB4, C6_SADD2, C6_SSUB2, C6_SADDU4, C6_SADDUS2, C6_SADDSU2,
    C6_ABS2, C6_AVG2, C6_AVGU4, C6_MAX2, C6_MIN2, C6_BITR, C6_SWAP4, C6_SHLMB, C6_SHRMB,
    C6_MPYU4, C6_MPYSU4, C6_MPYUS4, C6_DPACKX2,
    C6_CMPEQ2, C6_CMPEQ4, C6_CMPGT2, C6_CMPGTU4, C6_XPND2, C6_XPND4, C6_BITC4, C6_PACKH2, C6_PACKH4,
    C6_UNPKHU4, C6_UNPKLU4, C6_SPACK2, C6_SPACKU4, C6_SHRU2, C6_SUBABS4, C6_ADDSUB2, C6_SADDSUB, C6_SADDSUB2,
    C6_DOTPN2, C6_DOTPNRSU2, C6_DOTPRSU2, C6_DOTPSU4, C6_DOTPU4, C6_MPY2IR, C6_MPYHIR, C6_MPYLIR, C6_SMPY32,
    C6_RPACK2, C6_SSHVL, C6_SSHVR, C6_CMPY, C6_CMPYR, C6_CMPYR1, C6_DDOTP4, C6_DDOTPH2, C6_DDOTPH2R,
    C6_DDOTPL2, C6_DDOTPL2R, C6_DEAL, C6_SHFL, C6_SHFL3, C6_GMPY, C6_GMPY4, C6_XORMPY, C6_MPYI, C6_MPYID,
    C6_RSQRDP, C6_IDLE, C6_SWENR
};

typedef struct c6_operand {
    uint32_t kind;
    int32_t reg;              /* register, base, or pair high register */
    int64_t value;            /* immediate or memory displacement */
    int32_t aux;              /* displacement register or pair low; -1 when unused */
    uint32_t flags;
} c6_operand;
typedef struct c6_instruction {
    uint32_t address;
    uint32_t opcode;
    int32_t predicate;        /* -1 means unconditional */
    uint32_t invert;
    uint32_t count;
    uint32_t reserved;
    c6_operand operands[4];
} c6_instruction;
typedef struct c6_state {
    uint64_t cycles;
    uint64_t packets;
    uint32_t pc;
    uint32_t status;
    uint32_t idle_cycles;
    uint32_t pending_writes;
    uint32_t pending_branches;
    uint32_t fault_address;
    uint32_t registers[96];
} c6_state;

uint32_t c6_abi_version(void);
uint32_t c6_decode_address(void *machine);
void *c6_create(void);
void c6_destroy(void *machine);
const char *c6_error(void *machine);
int c6_map(void *machine, uint32_t address, uint64_t size, uint32_t permissions);
int c6_alias(void *machine, uint32_t address, uint32_t target, uint64_t size);
int c6_read(void *machine, uint32_t address, void *data, uint32_t size);
int c6_write(void *machine, uint32_t address, const void *data, uint32_t size);
int c6_reset(void *machine, uint32_t pc, uint32_t return_address, uint32_t stop_on_return);
int c6_set_register(void *machine, uint32_t reg, uint32_t value);
int c6_get_state(void *machine, c6_state *state);
int c6_install(void *machine, uint32_t pc, uint32_t next_pc, uint32_t protected_load,
               uint32_t dependency_start, uint32_t dependency_size,
               const c6_instruction *instructions, uint32_t count);
int c6_run(void *machine, uint64_t cycle_budget);
int c6_breakpoint(void *machine, uint32_t address, uint32_t enabled);
int c6_enable_board(void *machine);
/* profile 0 = stock SYSTEM, 1 = bare-metal GPIO-enabled bootloader handoff. */
int c6_enable_board_profile(void *machine, uint32_t profile);
/* Diagnostic reference path: poll every device each cycle instead of caching its next event. */
int c6_board_eager_polling(void *machine, uint32_t enabled);
/* Explicit diagnostic continuation: CPU stores below L2 ROM are logged and discarded.
   No RAM/read/fetch mapping; unresolved exception/routing/status observations fault. */
int c6_reserved_low_writes(void *machine, uint32_t enabled);
/* fields[2]: enabled, complete trace length (maximum 4096, overflow faults). */
int c6_reserved_low_stats(void *machine, uint64_t *fields);
/* fields[5]: cycle, instruction PC, address, size, little-endian value. */
int c6_reserved_low_write(void *machine, uint32_t index, uint64_t *fields);
/* Opt-in, select before execution: a CPU read below L2 ROM returns the 64-bit data of the previous RAM
   load, byte lanes picked by address bits 2:0 (the inference of M1 bench I1/I4), and is logged. */
int c6_reserved_low_reads(void *machine, uint32_t enabled);
/* fields[3]: enabled, reads counted, trace rows kept (the first 4096). */
int c6_reserved_low_read_stats(void *machine, uint64_t *fields);
/* fields[5]: cycle, instruction PC, address, size, value returned. */
int c6_reserved_low_read(void *machine, uint32_t index, uint64_t *fields);
/* fields[3]: CPU stores dropped at the empty EMIFA chip select 0 (0x40000000-0x5fffffff), the last one's address and PC. */
int c6_emifa_stores(void *machine, uint64_t *fields);
/* fields[6]: soft resets, PHY ready, soft connect, wrapper IRQ mask/source, event 19 count. */
int c6_usb_stats(void *machine, uint64_t *fields);
/* The scripted full-speed host on USB0's cable (usb.h). Attaching raises VBUS; the host resets the bus
   once the device's pull-up shows, then sends SOFs unless c6_usb_sof turned them off (an idle bus
   suspends the device after 3 ms). c6_usb_bus_reset resets an enabled port again. */
int c6_usb_attach(void *machine, uint32_t attached);
int c6_usb_bus_reset(void *machine);
int c6_usb_sof(void *machine, uint32_t enabled);
/* Queues a transfer; the host runs them one at a time as the guest runs. kind: 0 control (setup[8];
   `data` and `size` for a write request's data stage, wLength bytes come back for a read request),
   1 OUT (`data`), 2 IN (up to `length` bytes, ended by a short packet). `endpoint` is 1 to 4 for OUT
   and IN. `max_packet` is the endpoint's packet size, 1 to 64. `timeout` is in guest cycles from now. */
int c6_usb_submit(void *machine, uint32_t kind, uint32_t endpoint, const uint8_t *setup, const uint8_t *data, uint32_t size,
                  uint32_t length, uint32_t max_packet, uint64_t timeout, uint32_t *id);
/* fields[7]: status (0 pending, 1 done, 2 stalled, 3 timed out, 4 disconnected or reset, 5 no answer
   or a protocol error), NAKs, cycle submitted, cycle finished, data size, bytes copied, OUT bytes
   acknowledged. A finished transfer is forgotten once read. */
int c6_usb_transfer(void *machine, uint32_t id, uint64_t *fields, uint8_t *data, uint32_t capacity);
/* c6_run until the transfer has left the queue (checked every 1024 cycles) or the budget is spent. */
int c6_usb_run(void *machine, uint32_t id, uint64_t budget);
/* The host forgets an endpoint's data toggle (address with bit 7 for IN), as after SET_INTERFACE. It does
   so itself after SET_CONFIGURATION (all) and CLEAR_FEATURE(ENDPOINT_HALT) (one). */
int c6_usb_toggle_reset(void *machine, uint32_t endpoint);
/* fields[20]: port (0 detached, 1 waiting for the pull-up, 2 debounce, 3 reset, 4 enabled), VBUS, the
   address the host uses, configuration, the address the device answers to, bus resets, SOF on, SOFs sent,
   frame, suspended, NAKs, STALLs, errors, data-toggle errors, transfers finished, transfers queued, FIFO
   bytes overflowed, FIFO bytes underflowed, CTRLR, pull-up present. */
int c6_usb_host_stats(void *machine, uint64_t *fields);
/* Endpoint 1 to 4. fields[12]: TXMAXP, RXMAXP, TXFIFOSZ, RXFIFOSZ, TXFIFOADDR, RXFIFOADDR, packets waiting
   to go, packets waiting to be unloaded, IN stalled, OUT stalled, TXCSR high byte, RXCSR high byte. */
int c6_usb_endpoint(void *machine, uint32_t number, uint64_t *fields);
/* USB0 reserved offsets 0x80c/0x84c read 0 and CPU word stores of 0 to 0x808/0x848 are ignored, as on
   the unit with no host attached (M1 bench I5, 2026-11-16). Other accesses to them are unsupported.
   fields[2]: accesses counted, trace rows kept (the first 4096). */
int c6_usb_reserved_status_stats(void *machine, uint64_t *fields);
/* fields[5]: cycle, instruction PC, address, size, value. */
int c6_usb_reserved_status_read(void *machine, uint32_t index, uint64_t *fields);
int c6_gpio_input(void *machine, uint32_t bank, uint32_t pin, uint32_t high);
/* External ideal key switches, row/column wiring from the board profile; key 4 is GP5[10]. */
int c6_key_input(void *machine, uint32_t key, uint32_t down);
uint64_t c6_interrupt_count(void *machine);
uint64_t c6_loop_interrupt_count(void *machine); // Of those, taken after draining an SPLOOP (ITSR.SPLX set).
/* Exact fast-forward of provably repeating guest state (default on). Whole periods are
   skipped only after CPU state recurs with no net RAM change, MMIO, TSCL read or interrupt;
   cycle and packet counts advance as if every period had executed. A device event is never
   skipped: it runs at its own cycle, early only when the loop provably cannot observe it
   before then. Disabled while guest profiling or eager board polling is active. */
int c6_fast_forward(void *machine, uint32_t enabled);
/* Experimental compiled blocks (default off); see block.h. `heat` counts block entry
   candidates. c6_block_source writes host C++ for the straight run of packets at pc and
   fields[3]: source length (0 if not compilable), static ticks, continuation pc or 0.
   c6_block_install takes the compiled function for the source the same state produces. */
// The lean path for common instructions (on by default). Off, every instruction takes the general path.
int c6_micro(void *machine, uint32_t enabled);
int c6_blocks(void *machine, uint32_t enabled, uint32_t heat);
int c6_block_hot(void *machine, uint32_t *pcs, uint64_t *counts, uint32_t capacity, uint32_t *count);
int c6_block_source(void *machine, uint32_t pc, char *buffer, uint32_t capacity, uint32_t *fields);
int c6_block_install(void *machine, uint32_t pc, void *function);
/* fields[5]: enabled, installed blocks, entries, cycles advanced in blocks, refused entries. */
int c6_block_stats(void *machine, uint64_t *fields);
/* fields[9]: enabled, skips, skipped cycles, skipped packets, snapshots, abandoned snapshots,
   proofs, device events run ahead, of which held back for the CPU. */
int c6_fast_forward_stats(void *machine, uint64_t *fields);
/* Optional guest-work profiling. 1..1,000,000 starts a fresh sampling window; 0
   freezes it. CPU reset clears it. Sampling is deterministically jittered; period
   1 records every packet. Software-loop samples use the original SPLOOP PC. */
int c6_guest_profile(void *machine, uint32_t sample_period);
/* fields[16]: enabled, period, cycles, packets, interrupts, issue/wait/loop/IRQ-entry
   cycles, overlapping drain cycles, loop packets, wait advances/coalesced ticks,
   samples, dropped samples, PC rows. Also snapshots rows for guest_profile_pc. */
int c6_guest_profile_stats(void *machine, uint64_t *fields);
/* fields[3]: original PC, kind (0 ordinary/drain, 1 software loop), samples.
   Requires a fresh stats snapshot after execution; rows sorted by count then PC. */
int c6_guest_profile_pc(void *machine, uint32_t index, uint64_t *fields);
int c6_uart_receive(void *machine, uint32_t index, uint32_t byte);
/* Optional panel MCU peer on UART1: sends every analogue channel in turn, all the time, as the unit's
 * MCU does (rate measured on the bench; order, spacing and idle levels assumed). While it is on,
 * c6_uart_receive refuses UART1 and levels are set with c6_panel_level (channel 0..15, value 0..16383;
 * channel 15 is the battery, 12000 to begin with). Stats fields: enabled, messages sent, 16 levels. */
int c6_panel_stream(void *machine, uint32_t enabled);
int c6_panel_level(void *machine, uint32_t channel, uint32_t value);
int c6_panel_stream_stats(void *machine, uint64_t *fields);
/* Bytes the guest finished transmitting on a UART, oldest first from sequence `since`
   (the most recent 4096 are retained). fields[2]: total bytes sent, bytes copied. */
int c6_uart_sent(void *machine, uint32_t index, uint64_t since, uint8_t *data, uint32_t capacity, uint64_t *fields);
/* The cycle each of those bytes finished at (the end of its last stop bit), from the same sequence.
   fields[2]: total bytes sent, cycles copied. */
int c6_uart_sent_cycles(void *machine, uint32_t index, uint64_t since, uint64_t *cycles, uint32_t capacity, uint64_t *fields);
/* Optional sender on the MIDI IN jack (UART0 RXD): queued bytes arrive back to back, one per character
 * time of the divisor and format the guest programmed (119,040 cycles, MIDI's 31,250 baud 8N1, while it
 * has programmed none), the first starting now if the line is idle. c6_uart_receive remains the unpaced
 * path. With the loopback on, MIDI OUT is cabled to MIDI IN instead: every byte UART0 transmits is
 * received at the cycle it finishes, and c6_midi_in is refused.
 * Stats fields[10]: bytes queued, delivered, ignored (receiver in reset), looped back, loopback on,
 * cycle the next queued byte arrives at (0 if none), character cycles, bytes waiting in the receive
 * FIFO, overruns since the board was enabled or the UART reset, pending LSR error bits (OE 2, PE 4,
 * FE 8, BI 16; reading LSR clears them). */
int c6_midi_in(void *machine, const uint8_t *data, uint32_t size);
int c6_midi_loopback(void *machine, uint32_t enabled);
int c6_midi_stats(void *machine, uint64_t *fields);
/* An external pin level applied at a guest cycle (not in the past), as c6_gpio_input would then; edges of
 * one cycle apply in the order given. c6_gpio_schedule_clear drops a pin's edges not yet applied and
 * leaves its level where it is. */
int c6_gpio_schedule(void *machine, uint32_t bank, uint32_t pin, uint32_t high, uint64_t cycle);
int c6_gpio_schedule_clear(void *machine, uint32_t bank, uint32_t pin);
/* Level changes of watched output pins (GP7[9] from the start), oldest first from sequence `since`, the
 * most recent 4096 retained. rows: cycle, bank << 16 | pin << 8 | level, per change. A pin's first row is
 * the level it drives on becoming an output (or on being watched while one).
 * fields[3]: total changes, rows copied, scheduled input edges not yet applied. */
int c6_gpio_watch(void *machine, uint32_t bank, uint32_t pin, uint32_t enabled);
int c6_gpio_trace(void *machine, uint64_t since, uint64_t *rows, uint32_t capacity, uint64_t *fields);
int c6_oled_frame(void *machine, uint8_t *data, uint64_t *bytes, uint32_t *fields);
uint64_t c6_oled_first_frame_cycle(void *machine);
/* Backing media only; guest accesses still travel through SPI0. Each chip is 16 MiB. */
int c6_nor_load(void *machine, uint32_t chip, uint32_t offset, const uint8_t *data, uint32_t size);
int c6_nor_read(void *machine, uint32_t chip, uint32_t offset, uint8_t *data, uint32_t size);
int c6_nor_stats(void *machine, uint32_t chip, uint64_t *fields);
/* fields[9]: starts, stops, TX bytes, RX bytes, NACKs, codec writes/resets/page/trace length. */
int c6_i2c_stats(void *machine, uint64_t *fields);
int c6_codec_register(void *machine, uint32_t page, uint32_t reg, uint32_t *value);
/* Oldest-first bounded trace; fields[3] = page, register, original written value. */
int c6_codec_write(void *machine, uint32_t index, uint64_t *cycle, uint32_t *fields);
/* fields[8]: TX/RX words, underruns, overruns, capture words, first cycle/slot, last cycle. */
int c6_audio_stats(void *machine, uint64_t *fields);
int c6_audio_copy(void *machine, uint32_t offset, uint32_t *words, uint32_t count);
/* Digital ADC backing, copied before RX starts. LE 32-bit slot pairs, at most 64 MiB. */
int c6_audio_input(void *machine, const uint8_t *data, uint32_t size, uint32_t loop);
/* fields[6]: source words, position, looping, consumed words, zero padding, nonzero RX words. */
int c6_audio_input_stats(void *machine, uint64_t *fields);
/* Private SDSC backing, power-of-two 2..64 MiB. Insert before execution; GP4[0] becomes low. */
int c6_sd_load(void *machine, const uint8_t *data, uint32_t size);
int c6_sd_read(void *machine, uint32_t offset, uint8_t *data, uint32_t size);
/* fields[7]: bytes, state, bus width, commands, card read/write bytes, trace length. */
int c6_sd_stats(void *machine, uint64_t *fields);
/* fields[4]: command (ACMD = 64 + index), argument, first response word, resulting card state. */
int c6_sd_command(void *machine, uint32_t index, uint64_t *cycle, uint32_t *fields);
uint64_t c6_mmio_count(void *machine);
int c6_mmio_access(void *machine, uint64_t sequence, uint64_t *cycle, uint32_t *fields);
int c6_packet_info(void *machine, uint32_t pc, uint32_t *fields, c6_instruction *instructions);

#ifdef __cplusplus
}
#endif
#endif
