"""Execute an unmodified, CRC-checked stock SYSTEM image from a documented bootloader handoff."""
import argparse
import json
from pathlib import Path
import sys
import time

from build import ROOT, WORK, digest
from cpu import CPU, CoreFault
from media import sd_input

DEFAULT_FIRMWARE = ROOT / "firmware/smpltrek/SmplTrek v3.2.174.zip"
SYMBOLS = ROOT / "symbols/smpltrek-3.2.174.json"


def firmware(path, profile="smpltrek"):
    sys.path.insert(0, str(ROOT / "tools"))
    sys.path.insert(0, str(ROOT / "analysis"))
    try:
        import sonicware_integrity as integrity
        import mmtd2elf
    finally:
        sys.path.pop(0); sys.path.pop(0)
    items = list(integrity.inputs([Path(path)]))
    if len(items) != 1:
        raise ValueError("expected one stock update")
    name, data = items[0]
    checks = integrity.verify(data, profile)
    if any(stored != calculated for _, stored, calculated in checks):
        raise ValueError("stock firmware CRC verification failed")
    version, entry, sections = mmtd2elf.mmtd_sections(data)
    metadata = {"name": name, "sha256": digest(data), "version": ".".join(map(str, version)),
                "entry": entry, "crc_fields_verified": len(checks),
                "sections": [{"address": base, "size": len(content), "sha256": digest(content)}
                             for base, content in sections]}
    return metadata, sections


class Stock:
    def __init__(self, image=DEFAULT_FIRMWARE, work=WORK, power_held_ms=600, flash_image=None,
                 audio_input=None, loop_audio_input=False, card=None, reserved_low_writes=False,
                 profile="smpltrek", reserved_low_reads=False, panel_stream=False, gp3_8_high=False):
        if type(power_held_ms) is not int or not 0 <= power_held_ms <= 10000:
            raise ValueError("power_held_ms must be 0..10000")
        flash_data = None
        if flash_image is not None:
            path = Path(flash_image)
            if path.stat().st_size != 0x2000000:
                raise ValueError("flash image must be exactly 32 MiB (CS0 followed by CS1)")
            flash_data = path.read_bytes()
        if loop_audio_input and audio_input is None:
            raise ValueError("loop_audio_input requires an audio input file")
        input_data = None
        self.audio_input_profile = {"profile": "digital silence"}
        if audio_input is not None:
            path = Path(audio_input)
            size = path.stat().st_size
            if not size or size % 8 or size > 64 * 1024 * 1024:
                raise ValueError("audio input requires complete 32-bit slot pairs, up to 64 MiB")
            input_data = path.read_bytes()
            self.audio_input_profile = {"profile": "raw digital ADC slots", "path": str(path),
                                        "size": len(input_data), "sha256": digest(input_data)}
        card_data, self.card_input = sd_input(card)
        self.input, sections = firmware(image, profile)
        self.cpu = CPU(work)
        self.cpu.enable_board()
        if reserved_low_writes:
            self.cpu.reserved_low_writes()
        if reserved_low_reads:
            self.cpu.reserved_low_reads()
        if panel_stream:
            self.cpu.panel_stream()
        if input_data is not None:
            self.cpu.audio_input(input_data, loop_audio_input)
        self.flash_input = {"profile": "two erased 16 MiB SPI NOR chips; physical part number unknown"}
        if flash_data is not None:
            self.cpu.nor_load(0, flash_data[:0x1000000]); self.cpu.nor_load(1, flash_data[0x1000000:])
            self.flash_input = {"path": str(flash_image), "size": len(flash_data), "sha256": digest(flash_data),
                                "profile": "private in-memory copy; CS0 followed by CS1"}
        self.cpu.map(0xc0000000, 0x08000000, 7)
        for global_base, local_base, size, flags in ((0x11800000, 0x00800000, 0x40000, 7),
                                                    (0x11e00000, 0x00e00000, 0x8000, 7),
                                                    (0x11f00000, 0x00f00000, 0x8000, 3)):
            self.cpu.map(global_base, size, flags)
            self.cpu.alias(local_base, global_base, size)
        self.cpu.map(0x80000000, 0x20000, 7)
        for address, content in sections:
            self.cpu.write(address, content)
        self.cpu.reset(self.input["entry"], return_address=None)
        if card_data is not None:
            self.cpu.sd_load(card_data)
        self.power_release = power_held_ms * 372000 if power_held_ms else None
        self.inputs = [{"cycles": 0, "type": "power_key", "down": bool(power_held_ms)}]
        self.cpu.gpio_input(3, 0, not power_held_ms)
        # GP3[8] is an input every product reads: the built-in microphone is monitored or used only while it is
        # high (docs/platform-map.md). SmplTrek 3.2.174 draws a speaker in the title bar while it is low and
        # headphones while it is high, so it reads as headphone detection; what drives the pin on the unit was
        # not measured. Low unless asked.
        self.cpu.gpio_input(3, 8, bool(gp3_8_high))
        self.inputs.append({"cycles": 0, "type": "gp3_8", "high": bool(gp3_8_high)})
        self.expected = {self.input["entry"]: "system_entry"}
        if SYMBOLS.exists():
            symbols = json.loads(SYMBOLS.read_text())
            if symbols["source"]["sha256"] == self.input["sha256"]:
                names = {item["name"]: int(item["address"], 0) for item in symbols["symbols"]}
                for name in ("__TI_auto_init", "hwi_module_startup", "task_handler_entry", "audio_render_main", "power_on_check", "audio_start_transfers"):
                    if name in names:
                        self.expected[names[name]] = name
                # The entry's actual return site after the stock runtime initializer.
                self.expected[0xc16945e8] = "auto_init_return_site"
                self.expected[0xc1686740] = "auto_init_actual_call_target"
                self.expected[0xc1677ee0] = "cache_module_startup"
                self.expected[0xc154a884] = "main_delegate_power_start_path"
                self.expected[0xc1672298] = "oled_driver_init"
                self.expected[0xc1621854] = "audio_hardware_setup"
                self.expected[0xc167bf24] = "i2c0_first_access"
                self.expected[0xc16155a0] = "mcasp0_first_access"
                self.expected[0xc154a7ac] = "startup_minimum_delay"
                self.expected[0xc154a7e0] = "startup_delay_done"
                self.expected[0xc158ee00] = "usb_controller_init"
                self.expected[0xc15e2030] = "usb_interrupt_status_control"
                self.expected[0xc154a828] = "usb_start_return"
                self.expected[0xc154a840] = "codec_unmute_return"
                self.expected[0xc154aa24] = "startup_return_site"
                self.expected[0xc154c4b4] = "controller_render"
        for address in self.expected:
            self.cpu.breakpoint(address)
        self.checkpoints = []

    def key_input(self, key, down):
        self.cpu.key_input(key, down)
        self.inputs.append(dict(cycles=self.cpu.state()["cycles"], type="key", key=key, down=bool(down)))

    def encoder_phase(self, encoder, phase):
        if type(encoder) is not int or not 0 <= encoder < 5 or type(phase) is not int or not 0 <= phase < 4:
            raise ValueError("encoder must be 0..4 and phase 0..3")
        pins = ((3, 14, 15), (3, 12, 10), (5, 2, 0), (5, 5, 4), (5, 7, 8))
        bank, first, second = pins[encoder]
        self.cpu.gpio_input(bank, first, bool(phase & 1))
        self.cpu.gpio_input(bank, second, bool(phase & 2))
        self.inputs.append(dict(cycles=self.cpu.state()["cycles"], type="encoder_phase", encoder=encoder, phase=phase))

    def uart_receive(self, index, data):
        if isinstance(data, int):
            raise ValueError("UART input must be bytes or an iterable of bytes")
        data = bytes(data)
        self.cpu.uart_receive(index, data)
        self.inputs.append(dict(cycles=self.cpu.state()["cycles"], type="uart_rx", uart=index, bytes=list(data)))

    def midi_in(self, data):
        """Bytes from a sender on the MIDI IN jack, paced a character time apart (cpu.midi_in)."""
        data = bytes(data)
        self.cpu.midi_in(data)
        self.inputs.append(dict(cycles=self.cpu.state()["cycles"], type="midi_in", bytes=list(data)))

    def panel_level(self, channel, value):
        """Level the panel stream reports for a channel from now on (0-14 pads, 15 battery)."""
        self.cpu.panel_level(channel, value)
        self.inputs.append(dict(cycles=self.cpu.state()["cycles"], type="panel_level", channel=channel, value=value))

    def step(self, cycles):
        """Run up to `cycles` without building a report; returns the CPU state. Releases the
        power key when due and records (then disarms) a reached startup checkpoint."""
        if self.power_release is not None:
            now = self.cpu.cycles()
            if now >= self.power_release:
                self.cpu.gpio_input(3, 0, True)
                self.inputs.append({"cycles": now, "type": "power_key", "down": False})
                self.power_release = None
            else:
                cycles = min(cycles, self.power_release - now)
        state = self.cpu.run(cycles)
        if state["status"] == "breakpoint":
            self.checkpoints.append({"name": self.expected[state["pc"]], "address": state["pc"], "cycles": state["cycles"]})
            self.cpu.breakpoint(state["pc"], False)
        return state

    def run(self, cycles, slice_cycles=1000000, until_frame=False, until_checkpoint=None):
        if type(cycles) is not int or not 1 <= cycles <= 10000000000:
            raise ValueError("cycles must be 1..10000000000")
        if type(slice_cycles) is not int or not 1 <= slice_cycles <= 100000000:
            raise ValueError("slice_cycles must be 1..100000000")
        start_cycle = self.cpu.state()["cycles"]
        end = start_cycle + cycles
        error = None
        stop_reason = "cycle_budget"
        started = time.perf_counter()
        try:
            while self.cpu.state()["cycles"] < end:
                state = self.step(min(slice_cycles, end - self.cpu.state()["cycles"]))
                if state["status"] == "breakpoint":
                    if until_checkpoint == self.expected[state["pc"]]:
                        stop_reason = "checkpoint"
                        break
                elif state["status"] != "budget":
                    stop_reason = state["status"]
                    break
                if until_frame and self.cpu.oled_frame()[1]["complete_frames"]:
                    stop_reason = "first_frame"
                    break
        except CoreFault as fault:
            error = str(fault)
            stop_reason = "fault"
        state = self.cpu.state()
        frame, oled = self.cpu.oled_frame()
        raw_audio, audio = self.cpu.audio_output()
        audio.update(sha256=digest(raw_audio), rate_hz=48000, slot_bits=32,
                     input_profile=self.audio_input_profile["profile"],
                     input={**self.audio_input_profile, **self.cpu.audio_input_state()})
        oled["ram_sha256"] = digest(frame)
        elapsed = time.perf_counter() - started
        return {"target": "unmodified stock SmplTrek SYSTEM", "input": self.input,
                "profile": "C6748 bootloader SYSTEM handoff; RAM initialized to zero before loading sections",
                "core": self.cpu.manifest, "memory_regions": self.cpu.regions, "checkpoints": self.checkpoints,
                "inputs": self.inputs, "scheduled_power_release_cycle": self.power_release,
                "mmio_trace": self.cpu.mmio_trace(),
                "reserved_low": self.cpu.reserved_low_state(),
                "reserved_low_reads": self.cpu.reserved_low_read_state(),
                "usb": self.cpu.usb_state(),
                "oled": oled,
                "flash": {"input": self.flash_input, "chips": self.cpu.nor_stats()},
                "codec": self.cpu.codec_state(),
                "audio": audio,
                "sd": {"input": self.card_input, **self.cpu.sd_state()},
                "emifa": self.cpu.emifa_state(),
                "panel_stream": self.cpu.panel_stream_state(),
                "stop_reason": stop_reason,
                "state": state, "error": error, "elapsed_seconds": elapsed,
                "execution_window": {"start_cycle": start_cycle, "cycles": state["cycles"] - start_cycle,
                                     "realtime_ratio": (state["cycles"] - start_cycle) / 372000000 / elapsed},
                "clocks_hz": {"dsp": 372000000, "peripherals": 186000000, "oscillator": 24000000},
                "guest_seconds": state["cycles"] / 372000000,
                "complete_emulation": False, "guest_function_hooks": [],
                "conditional_execution": self.cpu.reserved_low_state()["count"] != 0 or self.cpu.reserved_low_read_state()["count"] != 0,
                "limitations": ["no boot ROM or bootloader execution", "additional ISA coverage pending",
                                "maskable interrupts drain and restart hardware loops (SPRUFE8B 7.13) but wait for a reloaded loop invocation and for protected waits; NMI pending",
                                "MMCSD0 supports SD 2.0 SDSC, block PIO/DMA and CMD12; high speed, erase, hotplug and SDIO pending",
                                "MMCSD DMA supports DMATRIG combined with data commands; standalone trigger programming remains unsupported",
                                "SPI NOR profile supports 03/05/06/04/02/20/52/D8; other commands fault; functional busy timing",
                                "I2C0 supports 7-bit, 8-bit, nonrepeat master transfers; slave/DMA/loopback/IGNACK modes unsupported",
                                "codec models the documented AIC3106-compatible control subset; physical part/reset wiring and analog timing unverified",
                                "McASP supports stock external 48 kHz, two 32-bit slots, AXR13/14; input is supplied at the digital ADC boundary",
                                "codec 24.576 MHz MCLK is inferred; analog processing and other McASP formats pending",
                                "USB0 models the wrapper, the MUSB core in peripheral mode (control, bulk and interrupt endpoints, FIFOs) and a scripted full-speed host; isochronous traffic, high speed, host/OTG, queues and DMA transfers are not modelled (DMA set-up registers hold, DMAEN faults)",
                                "reserved-low writes require explicit opt-in and guards; silicon bus response remains unverified",
                                "EDMA FIFO only supports aligned single 32-bit words; QDMA/chaining modes pending",
                                "OLED models the documented stock command/frame stream; controller identity and further commands unverified",
                                "UART peers are silent unless the panel stream is on (its rate is measured; channel order, spacing and idle levels are assumed); receive timeout/modem behavior not modeled",
                                "UART registers remain accessible while PSC functional clock is disabled (profile assumption)",
                                "coherent RAM; no physical cache timing; PSC transition latency is functional"]}

    def close(self):
        self.cpu.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware", type=Path, default=DEFAULT_FIRMWARE)
    parser.add_argument("--profile", choices=("smpltrek", "lofi12", "cydrums"), default="smpltrek",
                        help="update checksum profile; lofi12 and cydrums run a Lofi-12 XT or CyDrums image on the same board model")
    parser.add_argument("--cycles", type=int, default=10000000, help="guest cycle budget, up to 10 billion for startup delays")
    parser.add_argument("--slice-cycles", type=int, default=1000000)
    parser.add_argument("--power-held-ms", type=int, default=600, help="initial power-key hold in guest milliseconds; 0 starts released")
    parser.add_argument("--until-frame", action="store_true", help="stop after receiving the first complete stock framebuffer")
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--flash", type=Path, help="32 MiB flash backing image, copied into private memory; default erased")
    parser.add_argument("--export-flash", action="store_true", help="export the private flash state as flash.img beside the report")
    parser.add_argument("--audio-input", type=Path, help="48 kHz raw little-endian 32-bit ADC slot pairs, copied before RX starts")
    parser.add_argument("--loop-audio-input", action="store_true", help="repeat complete input slot pairs; default pads EOF with silence")
    parser.add_argument("--card", type=Path, help="private power-of-two SDSC image, 2 MiB to 1 GiB")
    parser.add_argument("--export-card", action="store_true")
    parser.add_argument("--reserved-low-writes", action="store_true",
                        help="explicit guarded continuation: log/discard low CPU stores; silicon response remains unverified")
    parser.add_argument("--reserved-low-reads", action="store_true",
                        help="explicit assumption: low CPU reads return the previous RAM load's data (inferred from the M1 bench) and are logged")
    parser.add_argument("--panel-stream", action="store_true",
                        help="the panel MCU sends every analogue channel continuously on UART1, as on the unit (about 4194 messages a second)")
    args = parser.parse_args(argv)
    try:
        destination = args.output or args.work / "stock/result.json"
        if args.export_flash and args.flash is not None and args.flash.resolve() == (destination.parent / "flash.img").resolve():
            raise ValueError("flash export must not overwrite the input image; choose a different --output directory")
        if args.audio_input is not None and args.audio_input.resolve() in {
            (destination.parent / name).resolve() for name in ("audio.pcm32", "audio.wav")
        }:
            raise ValueError("audio export must not overwrite the input file; choose a different --output directory")
        if args.export_card and args.card is not None and args.card.resolve() == (destination.parent / "card.img").resolve():
            raise ValueError("card export must not overwrite the input image; choose a different --output directory")
        with Stock(args.firmware, args.work, args.power_held_ms, args.flash,
                   args.audio_input, args.loop_audio_input, args.card, args.reserved_low_writes,
                   args.profile, args.reserved_low_reads, args.panel_stream) as stock:
            report = stock.run(args.cycles, args.slice_cycles, args.until_frame)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if args.export_card and report["sd"]["present"]:
                path = destination.parent / "card.img"
                data = stock.cpu.sd_read(); path.write_bytes(data)
                report["sd"]["artifact"] = {"path": str(path), "sha256": digest(data)}
            if args.export_flash:
                path = destination.parent / "flash.img"
                data = stock.cpu.nor_read(0) + stock.cpu.nor_read(1)
                path.write_bytes(data)
                report["flash"]["artifact"] = {"path": str(path), "sha256": digest(data)}
            frame, oled = stock.cpu.oled_frame()
            raw_audio, audio = stock.cpu.audio_output()
            if raw_audio:
                from audio_capture import stereo_wav
                path = destination.parent / "audio.pcm32"
                path.write_bytes(raw_audio)
                report["audio"]["artifact"] = str(path)
                wav, info = stereo_wav(raw_audio, audio["first_capture_slot"])
                path = destination.parent / "audio.wav"; path.write_bytes(wav)
                report["audio"]["wav"] = {**info, "path": str(path)}
            if oled["complete_frames"]:
                from display import png
                raw, rendered = destination.parent / "frame.bin", destination.parent / "frame.png"
                raw.write_bytes(frame); rendered.write_bytes(png(frame))
                report["oled"]["artifacts"] = {"raw": str(raw), "png": str(rendered)}
            destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
            state = report["state"]
            for checkpoint in report["checkpoints"]:
                print(f'{checkpoint["cycles"]:10d}  {checkpoint["name"]} ({checkpoint["address"]:#010x})')
            print(f'Stock SYSTEM: {report["stop_reason"]}, PC {state["pc"]:#010x}, {state["cycles"]} cycles')
            print(f"Report: {destination}")
            if report["oled"]["complete_frames"]:
                print(f'Stock display: {report["oled"]["complete_frames"]} complete frame(s), {rendered}')
            if report["error"]:
                print(report["error"], file=sys.stderr)
                return 1
        return 0
    except (ValueError, RuntimeError, OSError) as error:
        print(f"stock emulator: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
