"""Run a user-supplied DSP program (a linked C6000 ELF) on the board model, from a bootloader-style handoff.

The emulator does not build firmware. Bring your own little-endian ELF32 C6000 executable: its loadable
sections must fall inside the device's RAM (DDR2 at 0xC0000000, L2 at 0x11800000/0x00800000, L1P/L1D,
shared RAM at 0x80000000) and its entry must set up its own stack. A complete stock-format update
(`.bin` or `.zip` with valid CRCs) runs through stock.py / stock_ui.py `--firmware` instead.
"""
import argparse
import json
from pathlib import Path
import struct
import sys
import time

from build import WORK, digest
from cpu import CPU, CoreFault
from media import sd_input

# The memories the stock bootloader hands over (the same map stock.py uses): DDR2, L2/L1P/L1D with their
# local aliases, and the 128 KiB shared RAM.
RAM = ((0xc0000000, 0x08000000, None), (0x11800000, 0x40000, 0x00800000), (0x11e00000, 0x8000, 0x00e00000),
       (0x11f00000, 0x8000, 0x00f00000), (0x80000000, 0x20000, None))
HANDOFF = {"stock": 0, "gpio": 1}


def elf_symbols(path):
    """{name: address} of the defined symbols in a little-endian ELF32 file, without external tools."""
    data = Path(path).read_bytes()
    if len(data) < 52 or data[:6] != b"\x7fELF\x01\x01":
        raise ValueError("expected a little-endian ELF32 file")
    offset, = struct.unpack_from("<I", data, 32)
    size, count, _ = struct.unpack_from("<HHH", data, 46)
    if size < 40 or offset + size * count > len(data):
        raise ValueError("invalid ELF section table")
    headers = [struct.unpack_from("<IIIIIIIIII", data, offset + size * i) for i in range(count)]
    names = {}
    for _, kind, _, _, start, length, link, _, _, entsize in headers:
        if kind != 2 or not entsize or link >= count:      # SHT_SYMTAB
            continue
        strings = data[headers[link][4]:headers[link][4] + headers[link][5]]
        for position in range(start, start + length - entsize + 1, entsize):
            name, value, _, info, _, section = struct.unpack_from("<IIIBBH", data, position)
            if name and section and info & 0xf in (0, 1, 2):     # defined NOTYPE/OBJECT/FUNC
                names.setdefault(strings[name:strings.index(b"\0", name)].decode("ascii", "replace"), value)
    return names


class Custom:
    def __init__(self, elf, work=WORK, card=None, audio_input=None, loop_audio_input=False,
                 breakpoints=("main",), watch=(), handoff="gpio", reserved_low_reads=False):
        if handoff not in HANDOFF:
            raise ValueError(f"handoff must be one of {', '.join(HANDOFF)}")
        self.elf = Path(elf).resolve()
        if not self.elf.is_file():
            raise ValueError(f"ELF not found: {elf}")
        card_data, self.card_input = sd_input(card)
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
            self.audio_input_profile = dict(profile="raw digital ADC slots", path=str(path), size=size,
                                            sha256=digest(input_data))
        self.names = elf_symbols(self.elf)
        missing = [name for name in watch if name not in self.names]
        if missing:
            raise ValueError(f"watched symbols not in the ELF: {', '.join(missing)}")
        self.watch = tuple(watch)
        self.program = dict(path=str(self.elf), sha256=digest(self.elf.read_bytes()), handoff=handoff)
        self.cpu = CPU(work)
        # Profile 0 is the stock SYSTEM handoff; profile 1 also leaves the GPIO functional clock enabled.
        self.cpu.enable_board(profile=HANDOFF[handoff])
        if reserved_low_reads:
            # The unit returns held load data for reads below the L2 (bench M2, M3); off means they fault.
            self.cpu.reserved_low_reads(True)
        if input_data is not None:
            self.cpu.audio_input(input_data, loop_audio_input)
        for address, size, alias in RAM:
            self.cpu.map(address, size, 7)
            if alias is not None:
                self.cpu.alias(alias, address, size)
        self.entry = self.cpu.load_elf(self.elf, map_allocations=False)
        self.program["entry"] = self.entry
        self.cpu.reset(self.entry, return_address=None)
        if card_data is not None:
            self.cpu.sd_load(card_data)
        self.checkpoints = []
        self.inputs = []
        self.execution_seconds = 0.0
        self.expected = {self.names[name]: name for name in breakpoints if name in self.names}
        for address in self.expected:
            self.cpu.breakpoint(address)

    def word(self, name):
        return int.from_bytes(self.cpu.read(self.names[name], 4), "little")

    def key_input(self, key, down):
        self.cpu.key_input(key, down)
        self.inputs.append(dict(cycles=self.cpu.state()["cycles"], key=key, down=bool(down)))

    def run(self, cycles, slice_cycles=1000000):
        if type(cycles) is not int or not 1 <= cycles <= 1000000000 or not 1 <= slice_cycles <= 100000000:
            raise ValueError("cycles must be 1..1000000000 and slice_cycles 1..100000000")
        start_cycle = self.cpu.state()["cycles"]
        end = start_cycle + cycles
        start = time.perf_counter(); error = None
        try:
            while self.cpu.state()["cycles"] < end:
                state = self.cpu.run(min(slice_cycles, end - self.cpu.state()["cycles"]))
                if state["status"] == "breakpoint" and state["pc"] in self.expected:
                    self.checkpoints.append(dict(name=self.expected[state["pc"]], cycles=state["cycles"], address=state["pc"]))
                    self.cpu.breakpoint(state["pc"], False)
                elif state["status"] != "budget":
                    break
        except CoreFault as fault:
            error = str(fault)
        elapsed = time.perf_counter() - start
        self.execution_seconds += elapsed
        frame, oled = self.cpu.oled_frame()
        raw_audio, audio = self.cpu.audio_output()
        window = self.cpu.state()["cycles"] - start_cycle
        return dict(target="user-supplied DSP program", program=self.program, core=self.cpu.manifest,
                    state=self.cpu.state(), error=error, elapsed_seconds=elapsed, checkpoints=self.checkpoints,
                    total_execution_host_seconds=self.execution_seconds,
                    execution_window=dict(start_cycle=start_cycle, cycles=window,
                                          realtime_ratio=window / 372000000 / elapsed if elapsed else None),
                    watch={name: self.word(name) for name in self.watch},
                    oled={**oled, "sha256": digest(frame)}, mmio_trace=self.cpu.mmio_trace(),
                    inputs=self.inputs.copy(),
                    audio={**audio, "sha256": digest(raw_audio),
                           "input": {**self.audio_input_profile, **self.cpu.audio_input_state()}},
                    codec=self.cpu.codec_state(),
                    sd={"input": self.card_input, **self.cpu.sd_state()},
                    limitations=["SD supports SDSC block PIO/DMA; high speed, erase, hotplug and SDIO pending",
                                 "no panel MCU replies", "key switches are ideal; bounce, ghosting and settling not modeled",
                                 "audio is digital slot capture; analog output and physical channel routing unverified",
                                 "no host audio playback"])

    def close(self): self.cpu.close()
    def __enter__(self): return self
    def __exit__(self, *_): self.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--elf", type=Path, required=True, help="linked little-endian C6000 ELF executable")
    parser.add_argument("--cycles", type=int, default=100000000, help="guest cycles to run (372 million per second)")
    parser.add_argument("--slice-cycles", type=int, default=1000000)
    parser.add_argument("--break", dest="breakpoints", action="append", metavar="SYMBOL",
                        help="record when execution first reaches SYMBOL; repeat as needed (default: main)")
    parser.add_argument("--watch", action="append", default=[], metavar="SYMBOL",
                        help="report the 32-bit word at SYMBOL after the run; repeat as needed")
    parser.add_argument("--handoff", choices=tuple(HANDOFF), default="gpio",
                        help="board state at entry: the stock SYSTEM handoff, or that plus the GPIO clock enabled (default)")
    parser.add_argument("--reserved-low-reads", action="store_true",
                        help="return held load data for reads below the L2, as the unit does, instead of faulting")
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--output", type=Path, help="report folder (default: work/emulator/custom)")
    parser.add_argument("--card", type=Path, help="private power-of-two SDSC image, 2 MiB to 1 GiB")
    parser.add_argument("--export-card", action="store_true")
    parser.add_argument("--audio-input", type=Path, help="48 kHz raw little-endian 32-bit ADC slot pairs")
    parser.add_argument("--loop-audio-input", action="store_true")
    args = parser.parse_args(argv)
    destination = args.output or args.work / "custom"
    try:
        if args.export_card and args.card is not None and args.card.resolve() == (destination / "card.img").resolve():
            raise ValueError("card export must not overwrite the input image")
        if args.audio_input is not None and args.audio_input.resolve() in {
            (destination / name).resolve() for name in ("audio.pcm32", "audio.wav")
        }:
            raise ValueError("audio export must not overwrite the input file")
        with Custom(args.elf, args.work, args.card, args.audio_input, args.loop_audio_input,
                    args.breakpoints or ("main",), args.watch, args.handoff, args.reserved_low_reads) as custom:
            report = custom.run(args.cycles, args.slice_cycles)
            destination.mkdir(parents=True, exist_ok=True)
            if args.export_card and report["sd"]["present"]:
                path = destination / "card.img"; data = custom.cpu.sd_read(); path.write_bytes(data)
                report["sd"]["artifact"] = {"path": str(path), "sha256": digest(data)}
            frame, oled = custom.cpu.oled_frame()
            if oled["complete_frames"]:
                from display import png
                (destination / "frame.bin").write_bytes(frame); (destination / "frame.png").write_bytes(png(frame))
            raw_audio, audio = custom.cpu.audio_output()
            if raw_audio:
                from audio_capture import stereo_wav
                path = destination / "audio.pcm32"; path.write_bytes(raw_audio)
                report["audio"]["artifact"] = str(path)
                wav, info = stereo_wav(raw_audio, audio["first_capture_slot"])
                path = destination / "audio.wav"; path.write_bytes(wav)
                report["audio"]["wav"] = {**info, "path": str(path)}
            (destination / "result.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
            reached = ", ".join(row["name"] for row in report["checkpoints"]) or "none"
            print(f'Custom DSP: {report["state"]["cycles"]} cycles; {oled["complete_frames"]} frames; '
                  f'reached {reached}; watch {report["watch"]}')
            print(f'Report: {destination / "result.json"}')
            if report["error"]:
                print(report["error"], file=sys.stderr); return 1
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        print(f"custom emulator: {error}", file=sys.stderr); return 1


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
