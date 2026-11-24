# Stock register writes, in order (SmplTrek 3.2.174)

The stock firmware's register accesses to USB0, the codec and its I2C bus, McASP0 with its EDMA channels, and
MMC/SD, phase by phase. These are for diffing another firmware's drivers against the stock, write by write,
including what each write changes in the register's reset value. Captured 2026-11-24 in the emulator
(`emulator/stock_register_capture.py`, then `emulator/stock_register_tables.py`); every row here is
**emulated** unless marked otherwise. No row was measured on a unit.

| File | Contents |
|---|---|
| [usb0.csv](usb0.csv) | USB0 core and wrapper; SYSCFG0 KICK and CFGCHIP2; PSC1 module 1 |
| [i2c0.csv](i2c0.csv) | I2C0, its PINMUX4 fields, its EDMA claims |
| [codec.csv](codec.csv) | the AIC3106 register writes, decoded to page, register and value |
| [mcasp-edma.csv](mcasp-edma.csv) | McASP0; PINMUX0/1; PSC1 module 7; PSC0 modules 0-2; the EDMA3 controller; the PaRAM sets of channels 0 and 1 and the sets they link to |
| [mmcsd.csv](mmcsd.csv) | MMCSD0; PINMUX10; PSC0 module 5; EDMA channels 16/17 and their PaRAM sets |
| [sd-commands.csv](sd-commands.csv) | every SD command the card saw: argument, whether it answered, response, card state after |

## How to read the tables

- **Runs and phases.**
  - The *main* run goes through these phases:
    - `boot`: reset to the idle home screen, 6 s;
    - `attach`: the cable in, up to the host's bus reset;
    - `bus_reset`;
    - `enumeration`: rows tagged with the host's step (descriptor, SET_ADDRESS, SET_CONFIGURATION);
    - `bulk_out`: a USB MIDI note on 0x03;
    - `midi_menu`: CLOCK OUT and COMMAND turned on through the menus;
    - `bulk_in`: PLAY, clock events on 0x83, STOP;
    - `interface_on`, then `interface_off`: SET_INTERFACE 1 and 2 to alternate setting 1, then back to 0;
    - `suspend`: start-of-frame stopped until the device suspends, then resumed;
    - `detach`;
    - `rec_src_N`: REC SRC moved to source N, covering every input group: 0 built-in mic, 2 guitar, 5 dynamic mic, 7 stereo line, 9 mono line, 11 USB, 12 resampling;
    - `power_off`: the power key held 3 s.
  - The *card_reader* run repeats the opening phases (they are not listed again) and then enters SYSTEM MENU > CARD > CARD READER (NO to saving) with a host attached. The emulator stops at the stock's first CPPI queue-manager access (USB0 + 0x3200, not modelled), so card-reader mode is captured up to its DMA start. Leaving the mode, and the remount after it, are not captured.
- **Columns.**
  - `order`: the row's position in the file.
  - `access`: `write`, `read` or `poll` (identical reads in a row, `count` of them).
  - `address` and `register`: names from SPRUH79C. Registers that INDEX selects carry `[INDEX n]`. An access narrower than its register shows the bytes it covers. A wider access, such as a word store over 8-bit USB registers, is split into one row per register.
  - `value`.
  - `before`: the register's last value seen on the bus in this run, written or read back; otherwise its reset value. This is the software's view: status and self-clearing bits that hardware changed without a read can differ on the chip.
  - `reset`: SPRUH79C's value (SLAS509G's for the codec). It is empty for PaRAM, which is RAM, and for words the TRM does not document.
  - `changed`: the fields whose value differs between `before` and the write, named as in the TRM figure.
  - `count`: for a poll, the identical reads. For a data register (USB FIFOn, MMCDRR/MMCDXR), the consecutive accesses merged into the row. Its value is always `data`: the payload (descriptor bytes, MIDI events, card sectors holding Sonicware content) is left out on purpose. For any other row, 1 plus the later identical accesses (same PC, register and value) in the same phase that were folded into it, which is periodic interrupt work. So the order shows each access's first occurrence.
  - `pc` and `function`: names from `symbols/smpltrek-3.2.174.json`, otherwise `fn_<start>`; `(EDMA transfer)` for DMA.
- **Shared rows.** Controller-wide EDMA set-up and the SYSCFG KICK unlock appear in every file whose peripheral depends on them.
- **MMC/SD detail.** The MMC rows stop after the first mount and its first block read. The 1,300-odd file reads that follow repeat the same register pattern; they are listed command by command in `sd-commands.csv`.

## What they show

**POWER and the speed (usb0.csv).** The two configurations use different speeds:
- *Composite mode* (audio and MIDI), at boot: CFGCHIP2 = 0x0972, then a CTRLR reset. POWER then reads 0x20 (HSEN, its reset value), is written 0 (HSEN cleared, `fn_C1694CE4`), and then 0x40 (SOFTCONN) once the interrupt enables are set. The device stays full speed.
- *Card-reader mode*:
  - USB is reset: the interrupt enables go to 0, POWER = 0, the PHY is powered down (CFGCHIP2 0x30F72), PSC1 module 1 is cycled, CTRLR is reset and the PHY is powered up again.
  - The stock then writes **POWER = 0x20 and then 0x60: HSEN stays set, so mass storage negotiates high speed**, as the manual says ("Mass Storage Class: USB2.0 High Speed").
  - It sets endpoint 1's TX to generic RNDIS mode (MODE = 3, GENRNDISSZ1 = 0x1000) and sets up CPPI DMA: linking RAM, a descriptor region, RX channel 1, TX channel 0, and the scheduler (WORD[0..1], DMA_SCHED_CTRL = 0x80000007).

**Endpoint FIFOs (composite mode).** Written in `enumeration` (FIFOs) and `interface_on` (the audio endpoints' modes):

| Endpoint | FIFO size register | Start (bytes) | Packets | Packet size | CSR mode |
|---|---|---|---|---|---|
| 0 | fixed | 0 | 1 | 64 | — |
| 1 OUT (audio) | RXFIFOSZ 0x15: 256 bytes, DPB | 64 | 2 | RXMAXP 196 | RXCSR ISO (0x4000), CLRDATATOG |
| 2 IN (audio) | TXFIFOSZ 0x05: 256 bytes | 576 | 1 | TXMAXP 196 | TXCSR ISO (0x4000), CLRDATATOG |
| 3 IN (MIDI) | TXFIFOSZ 0x03: 64 bytes | 832 | 1 | TXMAXP 64 | TXCSR bulk, CLRDATATOG |
| 3 OUT (MIDI) | RXFIFOSZ 0x03: 64 bytes | 896 | 1 | RXMAXP 64 | RXCSR bulk, CLRDATATOG |

POWER.ISOUPDATE is never set. Card-reader mode's endpoint set-up comes after the point where the emulator stops.

**How the stock knows an IN packet has gone (bulk_in rows).** It loads only when TXPKTRDY reads 0 (`USBEndpointDataPut` reads TXCSR first), sets TXPKTRDY (`USBEndpointDataSend`), and takes the endpoint's TX interrupt as completion: INTSRCR's TX bit, a TXCSR/RXCSR read (`USBEndpointStatus`), a status clear, the next load. It never looks at FIFONOTEMPTY. That is safe only because every stock bulk and isochronous IN FIFO is single-buffered: there, TXPKTRDY clearing and the packet leaving are the same moment. In card-reader mode the bulk endpoints move through CPPI DMA, where completion comes from the DMA's completion queue. That part is beyond what the emulator runs.

**SD card (sd-commands.csv).** The first mount:
- CMD0 (no answer);
- CMD55(0), answered, sent twice;
- CMD0 again;
- CMD8(0x1AA);
- CMD55(0), then ACMD41(0x40FF8000);
- CMD2, then CMD3 (RCA 1);
- CMD9, CMD7 and CMD16(512), all with RCA 0x10000;
- CMD55, then ACMD51;
- CMD55, then ACMD6(2);
- CMD6(0x80FFFFF1);
- CMD13;
- then file reads.

Entering card-reader mode first reads 128 sectors (0x200 to 0x10000: the card information page). It then runs **the same sequence again, from CMD0, through the same functions**, including CMD55 with RCA 0 until CMD3 publishes the RCA.

The remount after leaving card-reader mode was not reached (static, inference): mounting goes through `card_mount` → `f_mount(..., 1)` → the disk driver's card init `0xC15D2EC8`, the function both captured sequences come from. So it should be the same sequence again. Whether the exit path calls `card_mount` itself, or the card observer does, was not traced.

**Codec (codec.csv).**
- *Boot* is the documented start-up (docs/04-hardware-access.md "Codec registers").
- *Each REC SRC change* rewrites the ADC input routing (17/18 MIC3, 19/21/22/24 LINE1, 15/16 PGA) in a fixed order. The read-modify-writes of 19 and 22 come from shadow bytes, so a route can pass through an intermediate state (power bit off, then on).
- *Closing the audio interfaces* (`interface_off`) writes the PLL back to nominal: 4 = 0x20, 5 = 6 = 0. That undoes the clock trim of HW-40's loop.
- *Power-off* writes 43 = 44 = 0x80 (DAC mute) and nothing else.
- I2C0's own register sequence per transfer is in i2c0.csv.

**McASP and EDMA (mcasp-edma.csv).** The order documented in docs/04-hardware-access.md ("McASP0"), with each write's field changes. The periodic interrupt work (IPR reads, ICR writes, PaRAM link reads) is folded into `count`.

## What needs a unit session

- **Reset values the emulator does not take from the TRM** (emulator/README.md, "Register capture"). The stock overwrites all of them before relying on them, so its behaviour is not affected:
  - INTRTXE/INTRRXE/INTRUSBE: TRM 0x1F/0x1E/0x06; the emulator has 0x01/0/0.
  - McASP ACLKXCTL/ACLKRCTL/AHCLKxCTL: TRM 0x60/0x20/0x8000.
  - I2C ICSAR: TRM 0x3FF.
  - CFGCHIP2: TRM 0xEF00, which means "force host, VBUS low" with the PHY powered down.
  - MMCST1: TRM 0x2, against the emulator's 0x26.

  On the chip, any of these can differ from the TRM as well: POWER = 0x20 was confirmed on the unit only because it mattered. A session would read each before the app writes it, from a test image that runs before the stock's set-up, or by reading the register first thing in Enaga.
- **What the bootloader leaves**: KICK (the emulator starts unlocked), CFGCHIP2, PSC states. None of these were traced.
- **Card-reader mode past its DMA start**: the high-speed enumeration, the RNDIS/CPPI transfers and the remount on exit. The stock image would have to run on the unit with a USB analyser, or the emulator would need CPPI.
- **Status and self-clearing bits in `before`**: these come from the software's view, as above.

Regenerate (needs firmware/ and the emulator build):

```bash
python3 -B emulator/stock_register_capture.py --conditional   # about 10 minutes; work/register-capture/raw.json
python3 -B emulator/stock_register_tables.py
```
