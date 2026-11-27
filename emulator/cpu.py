"""Persistent C++ CPU sessions, memory access and ELF loading through a fixed C interface."""
import ctypes as C
import hashlib
from pathlib import Path
import struct

from build import WORK
from core_build import build_core
from ir import Instruction, REGISTER, REGISTERS, State

READ, WRITE, EXECUTE = 1, 2, 4
CYCLES_PER_SECOND = 372000000
RET = 0xDEAD0000
STATUSES = ("budget", "decode", "returned", "fault", "breakpoint")
USB_FRAME_CYCLES = CYCLES_PER_SECOND // 1000
USB_STATUSES = ("pending", "ok", "stall", "timeout", "disconnected", "error")
USB_PORTS = ("detached", "powered", "debounce", "reset", "enabled")


class CoreFault(RuntimeError):
    pass


class UsbError(RuntimeError):
    """A scripted USB transfer that had to succeed did not; `result` is what the host got."""
    def __init__(self, message, result=None):
        super().__init__(message)
        self.result = result


class CPU:
    def __init__(self, work=WORK, decode=True):
        self.work = Path(work)
        library, self.manifest = build_core(work)
        self.lib = C.CDLL(str(library))
        signatures = {
            "abi_version": (C.c_uint32, []), "create": (C.c_void_p, []),
            "destroy": (None, [C.c_void_p]), "error": (C.c_char_p, [C.c_void_p]),
            "map": (C.c_int, [C.c_void_p, C.c_uint32, C.c_uint64, C.c_uint32]),
            "alias": (C.c_int, [C.c_void_p, C.c_uint32, C.c_uint32, C.c_uint64]),
            "read": (C.c_int, [C.c_void_p, C.c_uint32, C.c_void_p, C.c_uint32]),
            "write": (C.c_int, [C.c_void_p, C.c_uint32, C.c_void_p, C.c_uint32]),
            "reset": (C.c_int, [C.c_void_p, C.c_uint32, C.c_uint32, C.c_uint32]),
            "set_register": (C.c_int, [C.c_void_p, C.c_uint32, C.c_uint32]),
            "get_state": (C.c_int, [C.c_void_p, C.POINTER(State)]),
            "install": (C.c_int, [C.c_void_p, C.c_uint32, C.c_uint32, C.c_uint32, C.c_uint32,
                                  C.c_uint32, C.POINTER(Instruction), C.c_uint32]),
            "run": (C.c_int, [C.c_void_p, C.c_uint64]),
            "decode_address": (C.c_uint32, [C.c_void_p]),
            "breakpoint": (C.c_int, [C.c_void_p, C.c_uint32, C.c_uint32]),
            "enable_board": (C.c_int, [C.c_void_p]),
            "enable_board_profile": (C.c_int, [C.c_void_p, C.c_uint32]),
            "board_eager_polling": (C.c_int, [C.c_void_p, C.c_uint32]),
            "blocks": (C.c_int, [C.c_void_p, C.c_uint32, C.c_uint32]),
            "micro": (C.c_int, [C.c_void_p, C.c_uint32]),
            "block_hot": (C.c_int, [C.c_void_p, C.POINTER(C.c_uint32), C.POINTER(C.c_uint64), C.c_uint32, C.POINTER(C.c_uint32)]),
            "block_source": (C.c_int, [C.c_void_p, C.c_uint32, C.c_char_p, C.c_uint32, C.POINTER(C.c_uint32)]),
            "block_install": (C.c_int, [C.c_void_p, C.c_uint32, C.c_void_p]),
            "block_stats": (C.c_int, [C.c_void_p, C.POINTER(C.c_uint64)]),
            "reserved_low_writes": (C.c_int, [C.c_void_p, C.c_uint32]),
            "reserved_low_stats": (C.c_int, [C.c_void_p, C.POINTER(C.c_uint64)]),
            "reserved_low_reads": (C.c_int, [C.c_void_p, C.c_uint32]),
            "reserved_low_read_stats": (C.c_int, [C.c_void_p, C.POINTER(C.c_uint64)]),
            "reserved_low_read": (C.c_int, [C.c_void_p, C.c_uint32, C.POINTER(C.c_uint64)]),
            "emifa_stores": (C.c_int, [C.c_void_p, C.POINTER(C.c_uint64)]),
            "reserved_low_write": (C.c_int, [C.c_void_p, C.c_uint32, C.POINTER(C.c_uint64)]),
            "usb_stats": (C.c_int, [C.c_void_p, C.POINTER(C.c_uint64)]),
            "usb_reserved_status_stats": (C.c_int, [C.c_void_p, C.POINTER(C.c_uint64)]),
            "usb_attach": (C.c_int, [C.c_void_p, C.c_uint32]),
            "usb_bus_reset": (C.c_int, [C.c_void_p]),
            "usb_sof": (C.c_int, [C.c_void_p, C.c_uint32]),
            "usb_toggle_reset": (C.c_int, [C.c_void_p, C.c_uint32]),
            "usb_submit": (C.c_int, [C.c_void_p, C.c_uint32, C.c_uint32, C.c_void_p, C.c_void_p, C.c_uint32, C.c_uint32,
                                     C.c_uint32, C.c_uint64, C.POINTER(C.c_uint32)]),
            "usb_transfer": (C.c_int, [C.c_void_p, C.c_uint32, C.POINTER(C.c_uint64), C.c_void_p, C.c_uint32]),
            "usb_run": (C.c_int, [C.c_void_p, C.c_uint32, C.c_uint64]),
            "usb_host_stats": (C.c_int, [C.c_void_p, C.POINTER(C.c_uint64)]),
            "usb_iso_out": (C.c_int, [C.c_void_p, C.c_uint32, C.c_void_p, C.POINTER(C.c_uint32), C.c_uint32]),
            "usb_iso_in": (C.c_int, [C.c_void_p, C.c_uint32, C.c_uint32, C.c_uint32, C.c_uint32]),
            "usb_iso_stop": (C.c_int, [C.c_void_p, C.c_uint32]),
            "usb_iso_interval": (C.c_int, [C.c_void_p, C.c_uint32, C.c_uint32]),
            "usb_iso_read": (C.c_int, [C.c_void_p, C.c_uint32, C.POINTER(C.c_uint64), C.c_uint32, C.c_void_p, C.c_uint32, C.POINTER(C.c_uint64)]),
            "usb_iso_stats": (C.c_int, [C.c_void_p, C.c_uint32, C.POINTER(C.c_uint64)]),
            "usb_endpoint": (C.c_int, [C.c_void_p, C.c_uint32, C.POINTER(C.c_uint64)]),
            "usb_reserved_status_read": (C.c_int, [C.c_void_p, C.c_uint32, C.POINTER(C.c_uint64)]),
            "gpio_input": (C.c_int, [C.c_void_p, C.c_uint32, C.c_uint32, C.c_uint32]),
            "key_input": (C.c_int, [C.c_void_p, C.c_uint32, C.c_uint32]),
            "interrupt_count": (C.c_uint64, [C.c_void_p]),
            "loop_interrupt_count": (C.c_uint64, [C.c_void_p]),
            "fast_forward": (C.c_int, [C.c_void_p, C.c_uint32]),
            "fast_forward_stats": (C.c_int, [C.c_void_p, C.POINTER(C.c_uint64)]),
            "guest_profile": (C.c_int, [C.c_void_p, C.c_uint32]),
            "guest_profile_stats": (C.c_int, [C.c_void_p, C.POINTER(C.c_uint64)]),
            "guest_profile_pc": (C.c_int, [C.c_void_p, C.c_uint32, C.POINTER(C.c_uint64)]),
            "uart_receive": (C.c_int, [C.c_void_p, C.c_uint32, C.c_uint32]),
            "panel_stream": (C.c_int, [C.c_void_p, C.c_uint32]),
            "panel_level": (C.c_int, [C.c_void_p, C.c_uint32, C.c_uint32]),
            "panel_stream_stats": (C.c_int, [C.c_void_p, C.POINTER(C.c_uint64)]),
            "uart_sent": (C.c_int, [C.c_void_p, C.c_uint32, C.c_uint64, C.c_void_p, C.c_uint32, C.POINTER(C.c_uint64)]),
            "uart_sent_cycles": (C.c_int, [C.c_void_p, C.c_uint32, C.c_uint64, C.POINTER(C.c_uint64), C.c_uint32, C.POINTER(C.c_uint64)]),
            "midi_in": (C.c_int, [C.c_void_p, C.c_void_p, C.c_uint32]),
            "midi_loopback": (C.c_int, [C.c_void_p, C.c_uint32]),
            "midi_stats": (C.c_int, [C.c_void_p, C.POINTER(C.c_uint64)]),
            "gpio_schedule": (C.c_int, [C.c_void_p, C.c_uint32, C.c_uint32, C.c_uint32, C.c_uint64]),
            "gpio_schedule_clear": (C.c_int, [C.c_void_p, C.c_uint32, C.c_uint32]),
            "gpio_watch": (C.c_int, [C.c_void_p, C.c_uint32, C.c_uint32, C.c_uint32]),
            "gpio_trace": (C.c_int, [C.c_void_p, C.c_uint64, C.POINTER(C.c_uint64), C.c_uint32, C.POINTER(C.c_uint64)]),
            "oled_frame": (C.c_int, [C.c_void_p, C.c_void_p, C.POINTER(C.c_uint64), C.POINTER(C.c_uint32)]),
            "oled_first_frame_cycle": (C.c_uint64, [C.c_void_p]),
            "nor_load": (C.c_int, [C.c_void_p, C.c_uint32, C.c_uint32, C.c_void_p, C.c_uint32]),
            "nor_read": (C.c_int, [C.c_void_p, C.c_uint32, C.c_uint32, C.c_void_p, C.c_uint32]),
            "nor_stats": (C.c_int, [C.c_void_p, C.c_uint32, C.POINTER(C.c_uint64)]),
            "i2c_stats": (C.c_int, [C.c_void_p, C.POINTER(C.c_uint64)]),
            "codec_register": (C.c_int, [C.c_void_p, C.c_uint32, C.c_uint32, C.POINTER(C.c_uint32)]),
            "codec_write": (C.c_int, [C.c_void_p, C.c_uint32, C.POINTER(C.c_uint64), C.POINTER(C.c_uint32)]),
            "audio_stats": (C.c_int, [C.c_void_p, C.POINTER(C.c_uint64)]),
            "audio_copy": (C.c_int, [C.c_void_p, C.c_uint32, C.POINTER(C.c_uint32), C.c_uint32]),
            "audio_input": (C.c_int, [C.c_void_p, C.c_void_p, C.c_uint32, C.c_uint32]),
            "audio_input_stats": (C.c_int, [C.c_void_p, C.POINTER(C.c_uint64)]),
            "sd_load": (C.c_int, [C.c_void_p, C.c_void_p, C.c_uint32]),
            "sd_read": (C.c_int, [C.c_void_p, C.c_uint32, C.c_void_p, C.c_uint32]),
            "sd_stats": (C.c_int, [C.c_void_p, C.POINTER(C.c_uint64)]),
            "sd_command": (C.c_int, [C.c_void_p, C.c_uint32, C.POINTER(C.c_uint64), C.POINTER(C.c_uint32)]),
            "mmio_count": (C.c_uint64, [C.c_void_p]),
            "mmio_access": (C.c_int, [C.c_void_p, C.c_uint64, C.POINTER(C.c_uint64), C.POINTER(C.c_uint32)]),
            "psc_violations": (C.c_int, [C.c_void_p, C.c_uint64, C.POINTER(C.c_uint64), C.c_uint32, C.POINTER(C.c_uint64)]),
            "psc_strict": (C.c_int, [C.c_void_p, C.c_uint32]),
            "psc_modules": (C.c_int, [C.c_void_p, C.POINTER(C.c_uint32)]),
            "capture_start": (C.c_int, [C.c_void_p, C.POINTER(C.c_uint32), C.c_uint32, C.c_uint32, C.c_uint64]),
            "capture_stop": (C.c_int, [C.c_void_p]),
            "capture_take": (C.c_int, [C.c_void_p, C.POINTER(C.c_uint64), C.c_uint32, C.POINTER(C.c_uint64)]),
            "codec_log": (C.c_int, [C.c_void_p, C.c_uint64, C.POINTER(C.c_uint64), C.c_uint32, C.POINTER(C.c_uint64)]),
            "sd_log": (C.c_int, [C.c_void_p, C.c_uint64, C.POINTER(C.c_uint64), C.c_uint32, C.POINTER(C.c_uint64)]),
            "packet_info": (C.c_int, [C.c_void_p, C.c_uint32, C.POINTER(C.c_uint32), C.POINTER(Instruction)]),
        }
        for name, (result, args) in signatures.items():
            function = getattr(self.lib, "c6_" + name)
            function.restype, function.argtypes = result, args
        if self.lib.c6_abi_version() != 2:
            raise ValueError("incompatible compiled core ABI")
        self.handle = self.lib.c6_create()
        if not self.handle:
            raise MemoryError("could not create the compiled machine")
        self.decoder = None
        self._state = State()
        self.regions = []
        self.usb_ep0_packet, self.usb_packets, self.usb_interfaces, self.usb_setups = 64, {}, {}, {}
        self.usb_iso_packets, self.usb_iso_intervals = {}, {}
        self.artifacts = []
        self.decode_enabled = decode

    def checked(self, result):
        if result < 0:
            raise ValueError(self.lib.c6_error(self.handle).decode())

    def nor_load(self, chip, data, offset=0):
        self.ensure_open()
        self.address(chip); self.address(offset)
        data = bytes(data)
        if len(data) > 0x1000000:
            raise ValueError("SPI NOR backing load is limited to 16 MiB per chip")
        buffer = C.create_string_buffer(data)
        self.checked(self.lib.c6_nor_load(self.handle, chip, offset, buffer, len(data)))

    def codec_register(self, page, reg):
        self.ensure_open()
        self.address(page); self.address(reg)
        value = C.c_uint32()
        self.checked(self.lib.c6_codec_register(self.handle, page, reg, C.byref(value)))
        return value.value

    def codec_state(self):
        self.ensure_open()
        fields = (C.c_uint64 * 9)()
        self.checked(self.lib.c6_i2c_stats(self.handle, fields))
        result = dict(zip(("starts", "stops", "bytes_sent", "bytes_received", "nacks",
                           "register_writes", "software_resets", "page", "trace_length"), fields))
        result["registers"] = {
            str(page): {str(reg): self.codec_register(page, reg) for reg in regs}
            for page, regs in ((0, (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 16, 17, 18, 19, 21, 22, 24,
                                   37, 41, 42, 43, 44, 86, 93, 107)), (1, range(65, 77)))
        }
        result["trace"] = []
        for index in range(result.pop("trace_length")):
            cycle, row = C.c_uint64(), (C.c_uint32 * 4)()
            self.checked(self.lib.c6_codec_write(self.handle, index, C.byref(cycle), row))
            if not row[3]:   # writes only; codec_log() has the reads too
                result["trace"].append(dict(cycles=cycle.value, page=row[0], register=row[1], value=row[2]))
        return result

    def codec_log(self, since=0):
        """The codec's I2C register writes and reads in order from sequence number `since` on (the model keeps
        the latest 65536): returns (rows, next_since). Each row: sequence, cycles, page, register, value, read.
        Raises if rows from `since` on were already dropped. A software reset (page 0 register 1 bit 7) is
        logged as the write it is."""
        return self._log(self.lib.c6_codec_log, since, 5, lambda n, r: dict(
            sequence=n, cycles=r[0], page=r[1], register=r[2], value=r[3], read=bool(r[4])), "codec")

    def audio_output(self):
        self.ensure_open()
        fields = (C.c_uint64 * 8)()
        self.checked(self.lib.c6_audio_stats(self.handle, fields))
        info = dict(zip(("transmitted_words", "received_words", "underruns", "overruns", "captured_words",
                         "first_capture_cycle", "first_capture_slot", "last_capture_cycle"), fields))
        samples = (C.c_uint32 * info["captured_words"])()
        self.checked(self.lib.c6_audio_copy(self.handle, 0, samples, len(samples)))
        return struct.pack(f"<{len(samples)}I", *samples), info

    def nor_read(self, chip, offset=0, size=0x1000000):
        self.ensure_open()
        self.address(chip); self.address(offset)
        if type(size) is not int or not 0 <= size <= 0x1000000:
            raise ValueError("SPI NOR backing read is limited to 16 MiB per chip")
        buffer = (C.c_ubyte * size)()
        self.checked(self.lib.c6_nor_read(self.handle, chip, offset, buffer, size))
        return bytes(buffer)

    def nor_stats(self):
        self.ensure_open()
        result = []
        for chip in range(2):
            fields = (C.c_uint64 * 5)()
            self.checked(self.lib.c6_nor_stats(self.handle, chip, fields))
            result.append(dict(zip(("commands", "bytes_read", "programs", "erases", "status"), fields)))
        return result

    def ensure_open(self):
        if not self.handle:
            raise RuntimeError("the compiled CPU session is closed")

    @staticmethod
    def address(value):
        if type(value) is not int or not 0 <= value <= 0xffffffff:
            raise ValueError("address must be a 32-bit unsigned integer")
        return value

    def map(self, address, size, flags=READ | WRITE):
        self.ensure_open()
        self.address(address)
        if type(size) is not int or not 1 <= size <= 0x100000000:
            raise ValueError("mapping size must be between 1 and 2**32")
        self.checked(self.lib.c6_map(self.handle, address, size, flags))
        self.regions.append({"address": address, "size": size, "permissions": flags})

    def alias(self, address, target, size):
        self.ensure_open()
        self.checked(self.lib.c6_alias(self.handle, self.address(address), self.address(target), size))
        self.regions.append({"address": address, "size": size, "alias_of": target})

    def read(self, address, size):
        self.ensure_open()
        self.address(address)
        if type(size) is not int or not 0 <= size <= 64 * 1024 * 1024:
            raise ValueError("host reads are limited to 64 MiB")
        if not size:
            return b""
        data = (C.c_ubyte * size)()
        self.checked(self.lib.c6_read(self.handle, address, data, size))
        return bytes(data)

    def write(self, address, data):
        self.ensure_open()
        self.address(address)
        if not data:
            return
        data = bytes(data)
        if len(data) > 64 * 1024 * 1024:
            raise ValueError("host writes are limited to 64 MiB")
        buffer = C.create_string_buffer(data)
        self.checked(self.lib.c6_write(self.handle, address, buffer, len(data)))

    def reset(self, entry, return_address=RET):
        self.ensure_open()
        self.address(entry)
        if return_address is not None:
            self.address(return_address)
        self.checked(self.lib.c6_reset(self.handle, entry, return_address or 0, return_address is not None))

    def set_register(self, name, value):
        self.ensure_open()
        if name not in REGISTER or type(value) is not int:
            raise ValueError("expected a named register and integer value")
        self.checked(self.lib.c6_set_register(self.handle, REGISTER[name], value & 0xffffffff))

    def fast_forward(self, enabled=True):
        """Exact skipping of provably repeating guest state; disable for a reference run."""
        self.ensure_open()
        self.checked(self.lib.c6_fast_forward(self.handle, bool(enabled)))

    def fast_forward_state(self):
        self.ensure_open()
        fields = (C.c_uint64 * 9)()
        self.checked(self.lib.c6_fast_forward_stats(self.handle, fields))
        result = dict(zip(("enabled", "skips", "skipped_cycles", "skipped_packets", "snapshots",
                           "abandoned_snapshots", "proofs", "events_run_ahead", "events_held_back"), fields))
        result["enabled"] = bool(result["enabled"])
        return result

    def micro(self, enabled=True):
        """The lean path for common instructions. Off, every instruction takes the general path: slower, and
        meant for checking that the two agree. Set it before any code is decoded."""
        self.ensure_open()
        self.checked(self.lib.c6_micro(self.handle, bool(enabled)))

    def blocks(self, enabled=True, heat=False):
        """Experimental compiled blocks; `heat` counts candidate entry points. See blocks.py."""
        self.ensure_open()
        self.checked(self.lib.c6_blocks(self.handle, bool(enabled), bool(heat)))

    def block_hot(self, capacity=65536):
        self.ensure_open()
        pcs, counts, count = (C.c_uint32 * capacity)(), (C.c_uint64 * capacity)(), C.c_uint32()
        self.checked(self.lib.c6_block_hot(self.handle, pcs, counts, capacity, C.byref(count)))
        return [(pcs[i], counts[i]) for i in range(count.value)]

    def block_source(self, pc):
        """Host C++ for the block at pc, its static ticks and continuation pc; None if not compilable."""
        self.ensure_open()
        if not hasattr(self, "block_buffer"):
            self.block_buffer = C.create_string_buffer(1 << 20)
        buffer, fields = self.block_buffer, (C.c_uint32 * 3)()
        self.checked(self.lib.c6_block_source(self.handle, pc, buffer, len(buffer), fields))
        return (buffer.value.decode(), fields[1], fields[2]) if fields[0] else None

    def block_refusal(self, pc):
        """Why block_source(pc) has no host code (diagnostic text), or None if it has."""
        return None if self.block_source(pc) else self.block_buffer.value.decode()

    def block_install(self, pc, function):
        self.ensure_open()
        self.checked(self.lib.c6_block_install(self.handle, pc, function))

    def block_state(self):
        self.ensure_open()
        fields = (C.c_uint64 * 6)()
        self.checked(self.lib.c6_block_stats(self.handle, fields))
        return dict(zip(("enabled", "installed", "entries", "block_cycles", "refused_entries", "loop_cycles"), fields))

    def profile_guest(self, sample_period=1009):
        """Start a fresh observation window; zero freezes the current window."""
        self.ensure_open()
        if type(sample_period) is not int or not 0 <= sample_period <= 1000000:
            raise ValueError("guest sample period must be 0..1000000")
        self.checked(self.lib.c6_guest_profile(self.handle, sample_period))

    def guest_profile(self):
        self.ensure_open()
        fields = (C.c_uint64 * 16)()
        self.checked(self.lib.c6_guest_profile_stats(self.handle, fields))
        result = dict(zip(("enabled", "sample_period", "cycles", "packets", "interrupts", "issue_cycles",
                           "wait_cycles", "software_loop_cycles", "interrupt_entry_cycles", "draining_cycles",
                           "software_loop_packets", "wait_advances", "wait_ticks_coalesced", "samples",
                           "dropped_samples", "pc_rows"), fields))
        result["enabled"] = bool(result["enabled"])
        result["pcs"] = []
        for index in range(result.pop("pc_rows")):
            row = (C.c_uint64 * 3)()
            self.checked(self.lib.c6_guest_profile_pc(self.handle, index, row))
            result["pcs"].append(dict(pc=row[0], kind="software_loop" if row[1] else "ordinary_or_drain", samples=row[2]))
        result["limitations"] = ["PCs are jittered packet samples, not a cycle-weighted histogram",
                                 "software-loop samples use the SPLOOP control PC; drain work overlaps ordinary issue/wait cycles",
                                 "diagnostic profiling has host overhead; disabled execution uses a separate uninstrumented loop",
                                 "PC table holds at most 65536 locations; omitted samples are reported"]
        return result

    def cycles(self):
        """The guest cycle count alone; cheaper than building the full state."""
        self.ensure_open()
        self.checked(self.lib.c6_get_state(self.handle, C.byref(self._state)))
        return self._state.cycles

    def state(self):
        self.ensure_open()
        result = State()
        self.checked(self.lib.c6_get_state(self.handle, C.byref(result)))
        return {"pc": result.pc, "cycles": result.cycles, "packets": result.packets,
                "interrupt_count": self.lib.c6_interrupt_count(self.handle),
                "loop_interrupt_count": self.lib.c6_loop_interrupt_count(self.handle),
                "status": STATUSES[result.status], "idle_cycles": result.idle_cycles,
                "pending_writes": result.pending_writes, "pending_branches": result.pending_branches,
                "fault_address": result.fault_address,
                "registers": {name: result.registers[i] for i, name in enumerate(REGISTERS)}}

    def install(self, pc, next_pc, protected, dependency_start, dependency_size, instructions):
        self.ensure_open()
        self.checked(self.lib.c6_install(self.handle, pc, next_pc, protected, dependency_start,
                                        dependency_size, instructions, len(instructions)))

    def breakpoint(self, address, enabled=True):
        self.ensure_open()
        self.checked(self.lib.c6_breakpoint(self.handle, self.address(address), bool(enabled)))

    def enable_board(self, profile=0):
        self.ensure_open()
        if type(profile) is not int or profile not in (0, 1):
            raise ValueError("unknown board handoff profile")
        self.checked(self.lib.c6_enable_board_profile(self.handle, profile))

    def gpio_input(self, bank, pin, high):
        self.ensure_open()
        if type(bank) is not int or not 0 <= bank <= 8 or type(pin) is not int or not 0 <= pin <= 15:
            raise ValueError("expected GPIO bank 0..8 and pin 0..15")
        self.checked(self.lib.c6_gpio_input(self.handle, bank, pin, bool(high)))

    def board_eager_polling(self, enabled=True):
        self.ensure_open()
        self.checked(self.lib.c6_board_eager_polling(self.handle, bool(enabled)))

    def reserved_low_writes(self, enabled=True):
        self.ensure_open()
        self.checked(self.lib.c6_reserved_low_writes(self.handle, bool(enabled)))

    def key_input(self, key, down):
        self.ensure_open()
        if type(key) is not int or not 0 <= key < 48:
            raise ValueError("key index must be 0..47")
        self.checked(self.lib.c6_key_input(self.handle, key, bool(down)))

    def reserved_low_state(self):
        self.ensure_open()
        fields = (C.c_uint64 * 2)()
        self.checked(self.lib.c6_reserved_low_stats(self.handle, fields))
        rows = []
        for index in range(fields[1]):
            row = (C.c_uint64 * 5)()
            self.checked(self.lib.c6_reserved_low_write(self.handle, index, row))
            rows.append(dict(zip(("cycles", "pc", "address", "size", "value"), row)))
        return dict(enabled=bool(fields[0]), begin=0, end_exclusive=0x00700000,
                    writes=rows, count=fields[1], hardware_response_verified=False,
                    policy="guarded CPU write discard; low reads/fetches and unresolved error observations fault")

    def reserved_low_reads(self, enabled=True):
        self.ensure_open()
        self.checked(self.lib.c6_reserved_low_reads(self.handle, bool(enabled)))

    def reserved_low_read_state(self):
        self.ensure_open()
        fields = (C.c_uint64 * 3)()
        self.checked(self.lib.c6_reserved_low_read_stats(self.handle, fields))
        rows = []
        for index in range(fields[2]):
            row = (C.c_uint64 * 5)()
            self.checked(self.lib.c6_reserved_low_read(self.handle, index, row))
            rows.append(dict(zip(("cycles", "pc", "address", "size", "value"), row)))
        return dict(enabled=bool(fields[0]), begin=0, end_exclusive=0x00700000, reads=rows, count=fields[1],
                    hardware_response_verified=True,
                    policy="CPU reads below L2 ROM and of EMIFA chip select 0 return the held data of earlier loads on the "
                           "same data path (T1 for a side A destination register, T2 for side B), eight byte lanes each "
                           "replaced by the loads that read it, picked by address bits 2:0, as measured on the unit "
                           "(bench M2 and M3)")

    def emifa_state(self):
        """CPU stores dropped at the empty EMIFA chip select 0, as measured harmless on the unit."""
        self.ensure_open()
        fields = (C.c_uint64 * 3)()
        self.checked(self.lib.c6_emifa_stores(self.handle, fields))
        return dict(stores_dropped=fields[0], last_address=fields[1], last_pc=fields[2])

    def usb_state(self):
        """USB0 and the scripted host on its cable. `address` and `configuration` are the host's view (what
        SET_ADDRESS and SET_CONFIGURATION last succeeded with); `device_address` is the address the controller
        answers to. `naks`, `stalls`, `errors` (no answer, or a packet that broke the protocol) and
        `toggle_errors` (a packet dropped as a repeat because its DATA0/DATA1 did not alternate) count since
        the board was enabled. `iso_errors` and `iso_missed` sum the isochronous streams' counts
        (usb_iso_state); `iso_underruns` and `iso_overruns` count how often the device set UNDERRUN or
        OVERRUN. `speed` is what the last bus reset negotiated: "high" when POWER.HSENAB was set then (the
        core chirps; POWER.HSMODE reads 1), else "full"; the host runs the connection at that speed (SOF
        every 1 ms or every 125 us microframe, the speed's packet sizes and bit rate). `sofs` counts SOF
        packets (microframes at high speed); `frame` is the 1 ms frame number FRAME reads.
        `high_speed_resets` counts bus resets that went to high speed. `iso_double_sends`
        counts isochronous IN tokens that found both halves of a double-buffered FIFO loaded and not held by ISOUPDATE: both packets
        leave at once and the stream records an error (babble), as unit session 6 suggests. Reading this
        changes nothing."""
        self.ensure_open()
        fields = (C.c_uint64 * 6)()
        self.checked(self.lib.c6_usb_stats(self.handle, fields))
        host = (C.c_uint64 * 27)()
        self.checked(self.lib.c6_usb_host_stats(self.handle, host))
        endpoints = []
        for number in range(1, 5):
            row = (C.c_uint64 * 14)()
            self.checked(self.lib.c6_usb_endpoint(self.handle, number, row))
            fifo = lambda size, address: dict(address=address * 8, packet=8 << (size & 15), packets=2 if size & 16 else 1)
            endpoints.append(dict(number=number, tx_max_packet=row[0], rx_max_packet=row[1],
                                  tx_fifo=fifo(row[2], row[4]), rx_fifo=fifo(row[3], row[5]),
                                  tx_packets=row[6], rx_packets=row[7], tx_stall=bool(row[8]), rx_stall=bool(row[9]),
                                  tx_iso=bool(row[10] & 0x40), rx_iso=bool(row[11] & 0x40),
                                  tx_underrun=bool(row[12]), rx_overrun=bool(row[13])))
        return dict(profile=f'USB0 peripheral with a scripted {"high" if host[24] else "full"}-speed host', cable_connected=bool(host[1]),
                    reserved_status=self.usb_reserved_status_state(),
                    **dict(zip(("soft_resets", "phy_ready", "soft_connect", "interrupt_mask", "interrupt_source", "interrupts"), fields)),
                    port=USB_PORTS[host[0]], address=host[2], configuration=host[3], device_address=host[4],
                    bus_resets=host[5], sof=bool(host[6]), sofs=host[7], frame=host[8], suspended=bool(host[9]),
                    naks=host[10], stalls=host[11], errors=host[12], toggle_errors=host[13], transfers=host[14],
                    queued=host[15], fifo_overflows=host[16], fifo_underflows=host[17],
                    interrupt_mode="core registers (UINT = 1)" if host[18] & 8 else "wrapper (UINT = 0)",
                    pull_up=bool(host[19]), iso_errors=host[20], iso_missed=host[21], iso_underruns=host[22],
                    iso_overruns=host[23], speed="high" if host[24] else "full", high_speed_resets=host[25],
                    iso_double_sends=host[26],
                    endpoints=endpoints)

    def usb_attach(self):
        """Plug the cable into a full-speed host: VBUS now. Once the device's pull-up shows (SOFTCONN, with
        the clock and PHY up) the host debounces for 100 ms, resets the bus for 10 ms and enables the port;
        the first transfer starts 10 ms later. Transfers queued before that wait for it."""
        self.ensure_open()
        self.checked(self.lib.c6_usb_attach(self.handle, 1))

    def usb_detach(self):
        """Unplug: VBUS off, the session ends (DISCON), a transfer under way finishes as "disconnected"."""
        self.ensure_open()
        self.checked(self.lib.c6_usb_attach(self.handle, 0))

    def usb_reset(self):
        """Reset the bus of an enabled port again; the device is back at address 0, unconfigured."""
        self.ensure_open()
        self.checked(self.lib.c6_usb_bus_reset(self.handle))

    def usb_sof(self, enabled=True):
        """The host's start-of-frame, one every 1 ms (372,000 cycles) from the end of reset, or every 125 us
        (46,500 cycles) on a high-speed connection; on by default.
        Off, the bus is idle between transfers and the device sees suspend 3 ms after the last activity,
        then resume with the next packet."""
        self.ensure_open()
        self.checked(self.lib.c6_usb_sof(self.handle, bool(enabled)))

    def usb_submit(self, kind, endpoint=0, setup=None, data=b"", length=0, max_packet=None, timeout_ms=1000):
        """Queue a transfer ("control", "out" or "in") and return its id; the host runs queued transfers one
        after another as the guest runs. usb_result reads it, usb_wait runs the guest until it has finished.
        `max_packet` (default: the size usb_enumerate found, else 64) is 1 to 64 for control and at full
        speed, and 1 to 1024 for bulk and interrupt on a high-speed connection."""
        self.ensure_open()
        kinds = ("control", "out", "in")
        if kind not in kinds or type(endpoint) is not int or not 0 <= endpoint <= 255:
            raise ValueError('expected a transfer kind of "control", "out" or "in" and an endpoint address')
        if type(timeout_ms) not in (int, float) or not 0 < timeout_ms <= 600000:
            raise ValueError("timeout_ms must be above 0 and at most 600000")
        if type(length) is not int or not 0 <= length <= 65535:
            raise ValueError("an IN transfer reads 0 to 65535 bytes")
        number = endpoint & 15
        if kind != "control" and bool(endpoint & 0x80) != (kind == "in") and endpoint > 15:
            raise ValueError("an endpoint address with bit 7 set is an IN endpoint")
        if max_packet is None:
            max_packet = self.usb_ep0_packet if kind == "control" else self.usb_packets.get(number | (0x80 if kind == "in" else 0), 64)
        setup, data = bytes(setup or bytes(8)), bytes(data)
        if len(setup) != 8:
            raise ValueError("a SETUP packet is 8 bytes")
        identity = C.c_uint32()
        self.checked(self.lib.c6_usb_submit(self.handle, kinds.index(kind), number, C.create_string_buffer(setup, 8),
                                            C.create_string_buffer(data, len(data) or 1), len(data), length, max_packet,
                                            int(timeout_ms * USB_FRAME_CYCLES), C.byref(identity)))
        self.usb_setups[identity.value] = setup if kind == "control" else None
        return identity.value

    def usb_result(self, transfer):
        """A transfer's outcome: `status` is "pending", "ok", "stall", "timeout", "disconnected" (unplugged,
        pull-up dropped or bus reset under way) or "error" (no answer, or a packet that broke the protocol);
        `data` is what an IN transfer or a read request returned, `sent` how many OUT bytes were
        acknowledged, `naks` how often the device answered NAK, `submitted` and `completed` guest cycles.
        A finished transfer can be read once."""
        self.ensure_open()
        fields, data = (C.c_uint64 * 7)(), (C.c_ubyte * 65536)()
        self.checked(self.lib.c6_usb_transfer(self.handle, transfer, fields, data, 65536))
        status = USB_STATUSES[fields[0]]
        result = dict(id=transfer, status=status, data=bytes(data[:fields[5]]), naks=fields[1], submitted=fields[2],
                      completed=fields[3] if status != "pending" else None, sent=fields[6])
        if status != "pending":
            setup = self.usb_setups.pop(transfer, None)
            if setup and status == "ok" and setup[0] == 0x01 and setup[1] == 11:   # SET_INTERFACE: toggles restart
                for address in self.usb_interfaces.get(setup[4], ()):
                    self.checked(self.lib.c6_usb_toggle_reset(self.handle, address))
        return result

    def usb_wait(self, transfer):
        """Run the guest until the transfer has finished (by its timeout at the latest; the guest stops within
        1,024 cycles of that) and return usb_result. If the run stops for another reason first, such as a
        breakpoint, the result is still "pending"."""
        self.ensure_open()
        self._run(self.cycles() + 601000 * USB_FRAME_CYCLES,
                  lambda remaining: self.lib.c6_usb_run(self.handle, transfer, remaining))
        return self.usb_result(transfer)

    def usb_control(self, setup, data_or_length=None, timeout_ms=1000, wait=True, max_packet=None):
        """A control transfer: SETUP, the data stage if wLength is not 0, then the status stage. `setup` is the
        8 bytes, or (bmRequestType, bRequest, wValue, wIndex) with wLength taken from `data_or_length`: the
        bytes of a write request, or how many to read. Returns usb_result (a "stall" in any stage ends it),
        or the transfer's id with wait=False."""
        if not isinstance(setup, (bytes, bytearray)):
            kind, request, value, index = setup
            size = data_or_length if type(data_or_length) is int else len(data_or_length or b"")
            setup = struct.pack("<BBHHH", kind, request, value, index, size)
        setup = bytes(setup)
        if len(setup) != 8:
            raise ValueError("a SETUP packet is 8 bytes")
        wanted = setup[6] | setup[7] << 8
        if setup[0] & 0x80:
            if data_or_length not in (None, wanted):
                raise ValueError("a read request returns wLength bytes")
            data = b""
        else:
            data = b"" if data_or_length in (None, 0) else bytes(data_or_length)
            if len(data) != wanted:
                raise ValueError("a write request sends wLength bytes")
        transfer = self.usb_submit("control", 0, setup, data, 0, max_packet, timeout_ms)
        return self.usb_wait(transfer) if wait else transfer

    def usb_out(self, endpoint, data, timeout_ms=1000, wait=True, max_packet=None):
        """Send `data` to a bulk or interrupt OUT endpoint in packets of its maximum size (from the
        descriptors usb_enumerate read, else 64); the host retries while the device answers NAK."""
        transfer = self.usb_submit("out", endpoint, None, data, 0, max_packet, timeout_ms)
        return self.usb_wait(transfer) if wait else transfer

    def usb_in(self, endpoint, max_length, timeout_ms=1000, wait=True, max_packet=None):
        """Read from a bulk or interrupt IN endpoint until `max_length` bytes or a short packet; the host
        polls back to back while the device answers NAK, and gives up with "timeout" after timeout_ms."""
        transfer = self.usb_submit("in", endpoint | 0x80, None, b"", max_length, max_packet, timeout_ms)
        return self.usb_wait(transfer) if wait else transfer

    def usb_set_interface(self, interface, alternate, timeout_ms=1000):
        """SET_INTERFACE: select an interface's alternate setting, as a host does to start (1) or stop (0)
        an audio streaming interface. Returns usb_result; the host's data toggles for the interface's bulk
        and interrupt endpoints restart."""
        return self.usb_control((0x01, 11, alternate, interface), None, timeout_ms)

    def usb_iso_stream_out(self, endpoint, packets, wait=False, interval=None):
        """Queue payloads for an isochronous OUT endpoint, one packet per 1 ms frame (0 to 1023 bytes each;
        an empty payload is a zero-length packet). At high speed: one per `interval` microframes (default:
        2^(bInterval-1) from usb_enumerate, else 1), 0 to 1024 bytes each. They go out after the coming
        SOFs, behind any still queued; nothing is retried and a frame with nothing queued carries no packet.
        With wait=True the guest runs until all are sent. Returns usb_iso_state(endpoint)."""
        self.ensure_open()
        packets = [bytes(packet) for packet in packets]
        number = self._usb_iso_number(endpoint, False)
        limit = self._usb_iso_limit()
        if any(len(packet) > limit for packet in packets):
            raise ValueError(f"a {self.usb_state()['speed']}-speed isochronous packet is at most {limit} bytes")
        self._usb_iso_set_interval(number, interval)
        if packets:
            data = b"".join(packets)
            self.checked(self.lib.c6_usb_iso_out(self.handle, number, C.create_string_buffer(data, len(data) or 1),
                                                 (C.c_uint32 * len(packets))(*map(len, packets)), len(packets)))
        if wait:
            self._usb_iso_wait(number)
        return self.usb_iso_state(number)

    def usb_iso_stream_in(self, endpoint, frames, wait=True, max_packet=None, short_below=0, interval=None):
        """Ask an isochronous IN endpoint for a packet in each of the next `frames` frames (at high speed,
        `frames` service intervals of `interval` microframes: default 2^(bInterval-1) from usb_enumerate,
        else 1). With wait=True the guest runs until they have passed and the packets are returned as
        usb_iso_collect does; otherwise collect them later. A packet above `max_packet` (the endpoint's
        size from usb_enumerate, else 1023, or 1024 at high speed) is an error; one with data but fewer
        than `short_below` bytes counts as short."""
        self.ensure_open()
        number = self._usb_iso_number(endpoint, True)
        if type(frames) is not int or frames < 0:
            raise ValueError("frames must be a count")
        if max_packet is None:
            max_packet = self.usb_iso_packets.get(number | 0x80, self._usb_iso_limit())
        self._usb_iso_set_interval(number | 0x80, interval)
        self.checked(self.lib.c6_usb_iso_in(self.handle, number, frames, max_packet, short_below))
        if wait:
            self._usb_iso_wait(number | 0x80)
            return self.usb_iso_collect(number)

    def usb_iso_collect(self, endpoint):
        """The outcome of each IN token sent since the last call, oldest first: `frame` (the frame number of
        the SOF before it), on a high-speed connection `microframe` (0 to 7), `cycles` (when the
        transaction ended), `data`, and `status`: "data", "empty"
        (a zero-length packet: the device had nothing loaded) or "error" (no answer, or a packet above
        max_packet)."""
        self.ensure_open()
        number = self._usb_iso_number(endpoint, True)
        found = []
        while True:
            rows, data, fields = (C.c_uint64 * (3 * 1024))(), (C.c_ubyte * (1024 * 1024))(), (C.c_uint64 * 3)()
            self.checked(self.lib.c6_usb_iso_read(self.handle, number, rows, 1024, data, len(data), fields))
            at = 0
            for index in range(fields[0]):
                size = rows[index * 3 + 2]
                row = rows[index * 3]
                found.append(dict(frame=row & 0xffff, status=("data", "empty", "error")[row >> 16 & 15],
                                  cycles=rows[index * 3 + 1], data=bytes(data[at:at + size])))
                if row >> 23 & 1:
                    found[-1]["microframe"] = row >> 20 & 7
                at += size
            if not fields[2]:
                return found

    def usb_iso_stop(self, endpoint):
        """Drop an isochronous stream's queued OUT packets, or (endpoint address with bit 7) the IN frames
        still asked for. Packets already collected stay."""
        self.ensure_open()
        self.checked(self.lib.c6_usb_iso_stop(self.handle, endpoint))

    def usb_iso_state(self, endpoint):
        """One isochronous stream's counts since the board was enabled (endpoint address with bit 7 for IN).
        OUT: `queued` packets waiting, `sent`, `packets` and `bytes` the device stored, `missed` lost
        because its FIFO was full (OVERRUN), `errors` not taken for another reason (the device not
        listening, the endpoint not isochronous, or the packet above its size). IN: `queued` frames still
        to ask in, `sent` tokens, `packets` and `bytes` that came with data, `missed` zero-length answers,
        `short` packets under short_below, `errors` (no answer, or a packet above max_packet), `waiting`
        outcomes not collected yet and `dropped` ones lost because more than 65536 waited."""
        self.ensure_open()
        if type(endpoint) is not int or not 1 <= endpoint & 0x7f <= 4 or endpoint & ~0x8f:
            raise ValueError("isochronous streams go to endpoints 1 to 4")
        fields = (C.c_uint64 * 9)()
        self.checked(self.lib.c6_usb_iso_stats(self.handle, endpoint, fields))
        return dict(zip(("queued", "sent", "packets", "bytes", "missed", "short", "errors", "waiting", "dropped"), fields))

    def _usb_iso_number(self, endpoint, into_host):
        if type(endpoint) is not int or not 1 <= endpoint & 0x7f <= 4 or endpoint & ~0x8f or (endpoint & 0x80 and not into_host):
            raise ValueError("expected an isochronous endpoint address: 1 to 4, with bit 7 for IN")
        return endpoint & 15

    def _usb_iso_limit(self):
        return 1024 if self.usb_state()["speed"] == "high" else 1023

    def _usb_iso_set_interval(self, address, interval):
        if interval is None:
            interval = self.usb_iso_intervals.get(address, 1)
        if type(interval) is not int or not 1 <= interval <= 32768 or interval & (interval - 1):
            raise ValueError("an isochronous interval is 1 to 32768 microframes, a power of two")
        self.checked(self.lib.c6_usb_iso_interval(self.handle, address, interval))

    def _usb_iso_wait(self, address):
        # Until the stream has nothing left to send, or the port goes down (which empties it).
        if not self.usb_state()["sof"]:
            raise UsbError("isochronous streams need the host's SOF (usb_sof)")
        while self.usb_iso_state(address)["queued"]:
            self.run(USB_FRAME_CYCLES)
        self.run(USB_FRAME_CYCLES)   # the last frame's transaction ends within it

    def usb_enumerate(self, address=1, configuration=None, timeout_ms=1000):
        """Enumerate as a host does: wait for the port (attach first), read 8 bytes of the device descriptor,
        SET_ADDRESS, read the device descriptor and the whole configuration descriptor, SET_CONFIGURATION
        (the descriptor's value unless given). Later transfers use the packet sizes found: at full speed at
        most 64 (bulk, interrupt) and 1023 (isochronous), at high speed the descriptors' sizes (up to 1024)
        and, for isochronous streams, the interval 2^(bInterval-1) microframes. On a high-speed connection
        it also reads the device qualifier and the other-speed configuration, as a USB 2.0 host does,
        and the result then also has `speed` ("high"), `qualifier` and `other_speed_configuration` (None
        if the device stalls them) and each endpoint's bInterval as `interval`. Raises UsbError if a step
        does not succeed; `timeout_ms` applies to each step. Each endpoint found is listed with its
        interface and that interface's alternate setting."""
        self.ensure_open()
        if not self.usb_state()["cable_connected"]:
            raise UsbError("the USB cable is not attached")
        end = self.cycles() + int(timeout_ms * USB_FRAME_CYCLES)
        while self.usb_state()["port"] != "enabled":
            if self.cycles() >= end:
                raise UsbError(f'the USB port did not come up within {timeout_ms} ms (port {self.usb_state()["port"]})')
            self.run(min(USB_FRAME_CYCLES, end - self.cycles()))
        self.usb_ep0_packet, self.usb_packets, self.usb_interfaces, self.usb_iso_packets = 8, {}, {}, {}
        self.usb_iso_intervals = {}
        high = self.usb_state()["speed"] == "high"
        steps = []

        def control(name, setup, size=None):
            result = self.usb_control(setup, size, timeout_ms)
            steps.append(dict(result, step=name))
            if result["status"] != "ok" or (size and len(result["data"]) < min(size, 8)):
                raise UsbError(f'USB enumeration: {name} ended as {result["status"]} with {len(result["data"])} bytes', result)
            return result["data"]

        self.usb_ep0_packet = control("device descriptor, 8 bytes", (0x80, 6, 0x0100, 0), 8)[7]
        if self.usb_ep0_packet not in (8, 16, 32, 64):
            raise UsbError(f"USB enumeration: bMaxPacketSize0 is {self.usb_ep0_packet}")
        control("set address", (0x00, 5, address, 0))
        device = control("device descriptor", (0x80, 6, 0x0100, 0), 18)
        total = struct.unpack_from("<H", control("configuration descriptor, 9 bytes", (0x80, 6, 0x0200, 0), 9), 2)[0]
        descriptor = control("configuration descriptor", (0x80, 6, 0x0200, 0), total)
        qualifier = other_speed = None
        if high:   # a stall means a device that only runs at one speed (USB 2.0 9.6.2)
            result = self.usb_control((0x80, 6, 0x0600, 0), 10, timeout_ms)
            steps.append(dict(result, step="device qualifier"))
            if result["status"] == "ok" and len(result["data"]) >= 10:
                qualifier = result["data"]
                result = self.usb_control((0x80, 6, 0x0700, 0), 9, timeout_ms)
                steps.append(dict(result, step="other-speed configuration, 9 bytes"))
                if result["status"] == "ok" and len(result["data"]) >= 9:
                    other_total = struct.unpack_from("<H", result["data"], 2)[0]
                    other_speed = control("other-speed configuration", (0x80, 6, 0x0700, 0), other_total)
            elif result["status"] not in ("ok", "stall"):
                raise UsbError(f'USB enumeration: device qualifier ended as {result["status"]}', result)
        endpoints, interface, alternate, at = [], None, 0, 0
        while at + 2 <= len(descriptor) and descriptor[at]:
            size, kind = descriptor[at], descriptor[at + 1]
            if kind == 4 and size >= 9:
                interface, alternate = descriptor[at + 2], descriptor[at + 3]
            elif kind == 5 and size >= 7:
                number, attributes, packet = descriptor[at + 2], descriptor[at + 3], struct.unpack_from("<H", descriptor, at + 4)[0]
                endpoints.append(dict(address=number, interface=interface, alternate=alternate, max_packet=packet & 0x7ff,
                                      type=("control", "isochronous", "bulk", "interrupt")[attributes & 3]))
                if high:
                    endpoints[-1]["interval"] = descriptor[at + 6]
                if attributes & 3 in (2, 3):
                    self.usb_packets[number] = min(packet & 0x7ff, 1024 if high else 64)
                    self.usb_interfaces.setdefault(interface, []).append(number)
                elif attributes & 3 == 1:
                    self.usb_iso_packets[number] = max(self.usb_iso_packets.get(number, 0), min(packet & 0x7ff, 1024 if high else 1023))
                    if high:
                        interval = 1 << (min(max(descriptor[at + 6], 1), 16) - 1)
                        self.usb_iso_intervals[number] = min(self.usb_iso_intervals.get(number, interval), interval)
            at += size
        value = descriptor[5] if configuration is None else configuration
        control("set configuration", (0x00, 9, value, 0))
        found = dict(device=device, configuration=descriptor, vendor=struct.unpack_from("<H", device, 8)[0],
                     product=struct.unpack_from("<H", device, 10)[0], address=address, configuration_value=value,
                     max_packet0=self.usb_ep0_packet, endpoints=endpoints, steps=steps)
        if high:
            found.update(speed="high", qualifier=qualifier, other_speed_configuration=other_speed)
        return found

    def usb_reserved_status_state(self):
        self.ensure_open()
        fields = (C.c_uint64 * 2)()
        self.checked(self.lib.c6_usb_reserved_status_stats(self.handle, fields))
        rows = []
        for index in range(fields[1]):
            row = (C.c_uint64 * 5)()
            self.checked(self.lib.c6_usb_reserved_status_read(self.handle, index, row))
            rows.append(dict(zip(("cycles", "pc", "address", "size", "assumed_value"), row)))
        return dict(hardware_response_verified=True, reads=rows, count=fields[0],
                    addresses=[0x01e0080c, 0x01e0084c, 0x01e00808, 0x01e00848],
                    policy="two reserved USB words read 0 and stores of 0 to their disable words are ignored, as measured "
                           "on the unit with no host attached (M1 bench I5, 2026-11-16); `reads` lists the first 4096 of both kinds")

    def audio_input(self, data, loop=False):
        self.ensure_open()
        data = bytes(data)
        if not data or len(data) % 8 or len(data) > 64 * 1024 * 1024:
            raise ValueError("audio input requires complete 32-bit slot pairs, up to 64 MiB")
        buffer = C.create_string_buffer(data)
        self.checked(self.lib.c6_audio_input(self.handle, buffer, len(data), bool(loop)))

    def audio_input_state(self):
        self.ensure_open()
        fields = (C.c_uint64 * 6)()
        self.checked(self.lib.c6_audio_input_stats(self.handle, fields))
        result = dict(zip(("source_words", "position_words", "loop", "words_from_source",
                           "zero_padding_words", "nonzero_words_received"), fields))
        result["loop"] = bool(result["loop"])
        return result

    def sd_load(self, data):
        self.ensure_open()
        data = bytes(data)
        if len(data) < 2 * 1024 * 1024 or len(data) > 1024 * 1024 * 1024 or len(data) & (len(data) - 1):
            raise ValueError("SDSC backing must be a power-of-two size from 2 MiB to 1 GiB")
        self.checked(self.lib.c6_sd_load(self.handle, C.create_string_buffer(data), len(data)))

    def sd_state(self):
        self.ensure_open()
        fields = (C.c_uint64 * 7)()
        self.checked(self.lib.c6_sd_stats(self.handle, fields))
        result = dict(zip(("size", "state", "bus_width", "commands", "bytes_read", "bytes_written", "trace_length"), fields))
        result["present"] = bool(result["size"])
        result["trace"] = []
        for index in range(result.pop("trace_length")):
            cycle, row = C.c_uint64(), (C.c_uint32 * 4)()
            self.checked(self.lib.c6_sd_command(self.handle, index, C.byref(cycle), row))
            result["trace"].append(dict(cycles=cycle.value, command=row[0], argument=row[1], response=row[2], state=row[3]))
        return result

    def sd_log(self, since=0):
        """SD commands in order from sequence number `since` on (the card keeps the latest 65536): returns
        (rows, next_since). Each row: sequence, cycles, command (ACMDs as "ACMD41"), index, argument, response
        (the first response word; for R2 its bits 31:0), state (the card state after it), answered, long."""
        def row(n, r):
            index = r[1] - 64 if r[1] >= 64 else r[1]
            return dict(sequence=n, cycles=r[0], command=("ACMD" if r[1] >= 64 else "CMD") + str(index), index=index,
                        argument=r[2], response=r[3], state=r[4], answered=bool(r[5]), long=bool(r[6]))
        return self._log(self.lib.c6_sd_log, since, 7, row, "SD command")

    def _log(self, function, since, width, make, name):
        self.ensure_open()
        rows, fields = (C.c_uint64 * (width * 4096))(), (C.c_uint64 * 4)()
        found = []
        while True:
            self.checked(function(self.handle, since, rows, 4096, fields))
            if fields[2] > since:
                raise RuntimeError(f"{name} log rows {since}..{fields[2] - 1} were dropped before they were read")
            found += [make(since + i, rows[width * i:width * i + width]) for i in range(fields[0])]
            since = fields[1]
            if fields[0] < 4096:
                return found, since

    def sd_read(self, offset=0, size=None):
        self.ensure_open()
        self.address(offset)
        if size is None:
            size = self.sd_state()["size"] - offset
        if type(size) is not int or not 0 < size <= 1024 * 1024 * 1024:
            raise ValueError("invalid SD backing read length")
        buffer = C.create_string_buffer(size)
        self.checked(self.lib.c6_sd_read(self.handle, offset, buffer, size))
        return buffer.raw

    def uart_receive(self, index, data):
        self.ensure_open()
        if type(index) is not int or not 0 <= index < 3:
            raise ValueError("expected UART index 0..2")
        if isinstance(data, int):
            raise ValueError("UART input must be bytes or an iterable of bytes")
        for byte in bytes(data):
            self.checked(self.lib.c6_uart_receive(self.handle, index, byte))

    def panel_stream(self, enabled=True):
        """The panel MCU's continuous analogue reports on UART1 (rate from the M1 bench; the rest assumed)."""
        self.ensure_open()
        self.checked(self.lib.c6_panel_stream(self.handle, bool(enabled)))

    def panel_level(self, channel, value):
        self.ensure_open()
        if type(channel) is not int or type(value) is not int or not 0 <= channel <= 15 or not 0 <= value <= 16383:
            raise ValueError("expected panel channel 0..15 and level 0..16383")
        self.checked(self.lib.c6_panel_level(self.handle, channel, value))

    def panel_stream_state(self):
        self.ensure_open()
        fields = (C.c_uint64 * 18)()
        self.checked(self.lib.c6_panel_stream_stats(self.handle, fields))
        return {"enabled": bool(fields[0]), "messages": fields[1], "levels": list(fields[2:18]),
                "messages_per_second": 4194, "rate_measured": True, "order_spacing_and_levels_measured": False}

    def uart_sent(self, index, since=0, cycles=False):
        """Bytes the guest transmitted on a UART from sequence `since` (the latest 4096 are kept): returns
        (bytes, total sent). With `cycles`, returns (bytes, total sent, cycles): the guest cycle each of those
        bytes finished at, the end of its last stop bit."""
        self.ensure_open()
        if type(index) is not int or not 0 <= index < 3 or type(since) is not int or since < 0:
            raise ValueError("expected UART index 0..2 and a non-negative sequence")
        data, fields = (C.c_ubyte * 4096)(), (C.c_uint64 * 2)()
        self.checked(self.lib.c6_uart_sent(self.handle, index, since, data, len(data), fields))
        if not cycles:
            return bytes(data[:fields[1]]), fields[0]
        stamps = (C.c_uint64 * 4096)()
        self.checked(self.lib.c6_uart_sent_cycles(self.handle, index, since, stamps, len(stamps), fields))
        return bytes(data[:fields[1]]), fields[0], list(stamps[:fields[1]])

    def midi_in(self, data):
        """Queue bytes from a sender on the MIDI IN jack (UART0). They arrive back to back, one per character
        time of the divisor and format the guest programmed (119,040 cycles, 31,250 baud 8N1, before it has
        programmed any), the first starting now if nothing is queued. uart_receive(0, ...) is the unpaced path."""
        self.ensure_open()
        if isinstance(data, int):
            raise ValueError("MIDI input must be bytes or an iterable of bytes")
        data = bytes(data)
        self.checked(self.lib.c6_midi_in(self.handle, C.create_string_buffer(data, len(data) or 1), len(data)))

    def midi_loopback(self, enabled=True):
        """A cable from MIDI OUT to MIDI IN: each byte UART0 transmits is received as it finishes."""
        self.ensure_open()
        self.checked(self.lib.c6_midi_loopback(self.handle, bool(enabled)))

    def midi_state(self):
        """The MIDI IN peer and UART0's receiver. `overruns` counts bytes lost to a full FIFO since the board
        was enabled or the guest reset the UART; `line_errors` is what LSR would now report (OE 2, PE 4, FE 8,
        BI 16) and is cleared when the guest reads LSR. Reading this changes nothing."""
        self.ensure_open()
        fields = (C.c_uint64 * 10)()
        self.checked(self.lib.c6_midi_stats(self.handle, fields))
        result = dict(zip(("queued", "delivered", "ignored", "looped", "loopback", "next_cycle", "character_cycles",
                           "fifo", "overruns", "line_errors"), fields))
        result["loopback"] = bool(result["loopback"])
        result["next_cycle"] = result["next_cycle"] if result["queued"] else None
        return result

    def gpio_schedule(self, bank, pin, high, cycle):
        """Apply an external pin level at a guest cycle (not in the past), as gpio_input would then."""
        self.ensure_open()
        if type(bank) is not int or not 0 <= bank <= 8 or type(pin) is not int or not 0 <= pin <= 15:
            raise ValueError("expected GPIO bank 0..8 and pin 0..15")
        if type(cycle) is not int or not 0 <= cycle < 1 << 63:
            raise ValueError("expected a guest cycle")
        self.checked(self.lib.c6_gpio_schedule(self.handle, bank, pin, bool(high), cycle))

    def gpio_schedule_clear(self, bank, pin):
        """Drop a pin's scheduled levels that have not been applied; the pin stays as it is."""
        self.ensure_open()
        if type(bank) is not int or not 0 <= bank <= 8 or type(pin) is not int or not 0 <= pin <= 15:
            raise ValueError("expected GPIO bank 0..8 and pin 0..15")
        self.checked(self.lib.c6_gpio_schedule_clear(self.handle, bank, pin))

    def sync_in(self, bpm, pulses, start=None, per_quarter=2, width_ms=15, active_high=True):
        """Schedule a pulse train on SYNC IN (GP7[8]): `pulses` pulses of `width_ms` at `per_quarter` to the
        quarter note, the first one's leading edge at cycle `start` (now by default). Pulse times are rounded
        from the exact tempo, so they do not drift. Returns the cycle the next pulse would start at: pass it
        as `start` to carry on at another tempo, or schedule nothing more for a clock that stops. The pin
        idles low (high with active_high=False); how the jack's level maps to the pin was not measured."""
        if not isinstance(bpm, (int, float)) or not 1 <= bpm <= 1000 or type(pulses) is not int or not 0 <= pulses <= 16384:
            raise ValueError("expected a tempo of 1..1000 BPM and 0..16384 pulses")
        if type(per_quarter) is not int or not 1 <= per_quarter <= 96 or not isinstance(width_ms, (int, float)) or width_ms <= 0:
            raise ValueError("expected 1..96 pulses per quarter note and a positive pulse width")
        from fractions import Fraction
        start = self.cycles() if start is None else start
        period = Fraction(CYCLES_PER_SECOND * 60) / (Fraction(bpm) * per_quarter)
        width = round(Fraction(width_ms) * CYCLES_PER_SECOND / 1000)
        if not 0 < width < period:
            raise ValueError("the pulse width must be shorter than the pulse period")
        for pulse in range(pulses):
            edge = start + round(pulse * period)
            self.gpio_schedule(7, 8, active_high, edge)
            self.gpio_schedule(7, 8, not active_high, edge + width)
        return start + round(pulses * period)

    def sync_in_stop(self, active_high=True):
        """Stop the SYNC IN clock now: drop the edges not yet applied and return the pin to its idle level,
        which cuts short a pulse under way."""
        self.gpio_schedule_clear(7, 8)
        self.gpio_input(7, 8, not active_high)

    def gpio_watch(self, bank, pin, enabled=True):
        """Record an output pin's level changes in gpio_trace (GP7[9], SYNC OUT, is watched from the start)."""
        self.ensure_open()
        if type(bank) is not int or not 0 <= bank <= 8 or type(pin) is not int or not 0 <= pin <= 15:
            raise ValueError("expected GPIO bank 0..8 and pin 0..15")
        self.checked(self.lib.c6_gpio_watch(self.handle, bank, pin, bool(enabled)))

    def gpio_trace(self, since=0):
        """Level changes of watched output pins from sequence `since` (the latest 4096 are kept): returns
        (rows, total), each row a dict of bank, pin, high and the guest cycle of the register write. A pin's
        first row is the level it drives when it becomes an output."""
        self.ensure_open()
        if type(since) is not int or since < 0:
            raise ValueError("expected a non-negative sequence")
        rows, fields = (C.c_uint64 * 8192)(), (C.c_uint64 * 3)()
        self.checked(self.lib.c6_gpio_trace(self.handle, since, rows, 4096, fields))
        return [dict(bank=rows[i * 2 + 1] >> 16, pin=rows[i * 2 + 1] >> 8 & 255, high=bool(rows[i * 2 + 1] & 1), cycles=rows[i * 2])
                for i in range(fields[1])], fields[0]

    def gpio_scheduled(self):
        """How many scheduled input levels are still to be applied."""
        self.ensure_open()
        rows, fields = (C.c_uint64 * 2)(), (C.c_uint64 * 3)()
        self.checked(self.lib.c6_gpio_trace(self.handle, 1 << 62, rows, 0, fields))
        return fields[2]

    def audio_tail(self, since):
        """Slot words transmitted after the first `since` words: (little-endian uint32 bytes,
        slot of the first returned word, total transmitted, words lost before the capture window)."""
        self.ensure_open()
        fields = (C.c_uint64 * 8)()
        self.checked(self.lib.c6_audio_stats(self.handle, fields))
        total, captured, first_slot = fields[0], fields[4], fields[6]
        wanted = max(0, total - since)
        count = min(wanted, captured)
        if not count:
            return b"", 0, total, wanted
        words = (C.c_uint32 * count)()
        self.checked(self.lib.c6_audio_copy(self.handle, captured - count, words, count))
        data = bytes(words) if struct.pack("=I", 1) == struct.pack("<I", 1) else struct.pack(f"<{count}I", *words)
        return data, (first_slot + captured - count) & 1, total, wanted - count

    def oled_frame(self):
        self.ensure_open()
        data, count, fields = (C.c_ubyte * 8192)(), C.c_uint64(), (C.c_uint32 * 4)()
        self.checked(self.lib.c6_oled_frame(self.handle, data, C.byref(count), fields))
        return bytes(data), {"bytes_received": count.value, "complete_frames": count.value // 8192,
                             "first_frame_cycle": self.lib.c6_oled_first_frame_cycle(self.handle),
                             "on": bool(fields[0]), "contrast": fields[1], "remap": fields[2], "cursor": fields[3]}

    def mmio_trace(self):
        self.ensure_open()
        count = self.lib.c6_mmio_count(self.handle)
        result = []
        for sequence in range(max(0, count - 1024), count):
            cycle, fields = C.c_uint64(), (C.c_uint32 * 5)()
            self.checked(self.lib.c6_mmio_access(self.handle, sequence, C.byref(cycle), fields))
            result.append({"sequence": sequence, "cycles": cycle.value, "pc": fields[0], "address": fields[1],
                           "value": fields[2], "size": fields[3], "write": bool(fields[4])})
        return result

    PSC_STATES = {0: "SwRstDisable", 1: "SyncReset", 2: "Disable", 3: "Enable"}

    def psc_violations(self, since=0):
        """Guest or DMA accesses to a peripheral whose PSC module was not enabled (MDSTAT state other than Enable),
        in order from sequence `since` on: (rows, next_since). Each row: sequence, cycles, pc (0xfffffff0 for DMA),
        address, write, psc, module, state (its name). Peripherals with no PSC module (I2C0, the timers, SYSCFG)
        are never flagged. Recording is always on and never stops the guest unless psc_strict(True)."""
        return self._log(self.lib.c6_psc_violations, since, 7, lambda n, r: dict(
            sequence=n, cycles=r[0], pc=r[1], address=r[2], write=bool(r[3]), psc=r[4], module=r[5],
            state=self.PSC_STATES.get(r[6], str(r[6]))), "PSC violation")

    def psc_strict(self, enabled=True):
        """Fault on the first access to a peripheral whose PSC module is not enabled (off by default)."""
        self.ensure_open()
        self.checked(self.lib.c6_psc_strict(self.handle, int(bool(enabled))))

    def psc_modules(self):
        """Every PSC module: psc, module, mdctl_next and state (names), and assumed: True where the state the board
        started with is an assumed bootloader hand-off (DDR, and GPIO with the hand-off) rather than SPRUH79C's
        default. What the stock bootloader really leaves is not known."""
        self.ensure_open()
        rows = (C.c_uint32 * (3 * 64))()
        self.checked(self.lib.c6_psc_modules(self.handle, rows))
        return [dict(psc=n // 32, module=n % 32, mdctl_next=self.PSC_STATES.get(rows[3 * n] & 7, str(rows[3 * n] & 7)),
                     state=self.PSC_STATES.get(rows[3 * n + 1] & 63, str(rows[3 * n + 1] & 63)), assumed=bool(rows[3 * n + 2]))
                for n in range(64) if n >= 32 or n < 16]

    def capture_start(self, ranges, writes_only=False, limit=1 << 22):
        """Capture every MMIO access to the given address ranges, [(start, end), ...] with end exclusive, for
        whole sequences (mmio_trace keeps only the latest 1024 of all accesses). Reads are captured too unless
        `writes_only`; identical consecutive reads (a poll) fold into one row with a `repeat` count. Take the
        rows with capture_take() as often as needed: nothing is lost unless `limit` rows wait untaken, and
        capture_take() reports any that were. Starting again clears the previous capture."""
        self.ensure_open()
        flat = [value for start, end in ranges for value in (start, end)]
        if not ranges or len(ranges) > 64:
            raise ValueError("give 1 to 64 address ranges")
        self.checked(self.lib.c6_capture_start(self.handle, (C.c_uint32 * len(flat))(*flat), len(ranges),
                                               int(bool(writes_only)), limit))

    def capture_take(self, stop=False):
        """The captured rows so far, oldest first: cycles, pc (0xfffffff0 for DMA), address, value, size, write,
        repeat. With `stop`, ends the capture first so the last row is included. Raises if rows were dropped."""
        self.ensure_open()
        if stop:
            self.checked(self.lib.c6_capture_stop(self.handle))
        rows, fields, found = (C.c_uint64 * (7 * 4096))(), (C.c_uint64 * 4)(), []
        while True:
            self.checked(self.lib.c6_capture_take(self.handle, rows, 4096, fields))
            for i in range(fields[0]):
                r = rows[7 * i:7 * i + 7]
                found.append(dict(cycles=r[0], pc=r[1], address=r[2], value=r[3], size=r[4], write=bool(r[5]), repeat=r[6]))
            if fields[3]:
                raise RuntimeError(f"the MMIO capture dropped {fields[3]} rows: take them more often or raise the limit")
            if fields[0] < 4096:
                return found

    def packet_info(self, address):
        self.ensure_open()
        fields, instructions = (C.c_uint32 * 4)(), (Instruction * 8)()
        self.checked(self.lib.c6_packet_info(self.handle, address, fields, instructions))
        return {"next": fields[0], "protected": bool(fields[1]), "valid": bool(fields[3]),
                "instructions": [{"address": ins.address, "opcode": ins.opcode, "reserved": ins.reserved}
                                 for ins in instructions[:fields[2]]]}

    def run(self, cycles):
        self.ensure_open()
        if type(cycles) is not int or not 0 <= cycles <= 1000000000:
            raise ValueError("cycle budget must be an integer from 0 to 1000000000")
        return self._run(self.cycles() + cycles, lambda remaining: self.lib.c6_run(self.handle, remaining))

    def _run(self, end, call):
        while True:
            remaining = end - self.cycles()
            status = call(remaining)
            state = self.state()
            if status == 3:
                detail = self.decoder.text.get(state["fault_address"], "") if self.decoder else ""
                raise CoreFault(f'{self.lib.c6_error(self.handle).decode()}: {detail} (PC {state["pc"]:#010x}, cycle {state["cycles"]})')
            if status != 1 or not self.decode_enabled:
                return state
            if self.decoder is None:
                from decoder import Decoder
                self.decoder = Decoder(self)
            try:
                address = self.lib.c6_decode_address(self.handle)
                self.decoder.populate(address)
            except (ValueError, OSError) as error:
                raise CoreFault(f'decode failed at {address:#010x} (PC {state["pc"]:#010x}): {error}') from error

    def load_elf(self, path, map_allocations=True):
        self.ensure_open()
        path = Path(path)
        data = path.read_bytes()
        if len(data) < 52 or data[:7] != b"\x7fELF\x01\x01\x01" or struct.unpack_from("<H", data, 18)[0] != 140:
            raise ValueError("expected a little-endian ELF32 C6000 executable")
        kind, = struct.unpack_from("<H", data, 16)
        if kind != 2:
            raise ValueError("ELF must be linked (ET_EXEC)")
        entry, = struct.unpack_from("<I", data, 24)
        offset, = struct.unpack_from("<I", data, 32)
        size, count = struct.unpack_from("<HH", data, 46)
        if size < 40 or offset + size * count > len(data):
            raise ValueError("invalid ELF section table")
        sections, pages = [], {}
        for i in range(count):
            _, kind, flags, address, file_offset, length = struct.unpack_from("<IIIIII", data, offset + size * i)
            if not flags & 2 or not length:
                continue
            if address + length > 0x100000000 or length > 64 * 1024 * 1024:
                raise ValueError("invalid ELF allocation range")
            if kind != 8 and file_offset + length > len(data):
                raise ValueError("ELF section extends past the file")
            sections.append((address, length, None if kind == 8 else data[file_offset:file_offset + length]))
            for page in range(address & ~4095, (address + length + 4095) & ~4095, 4096):
                pages[page] = pages.get(page, READ | WRITE) | (EXECUTE if flags & 4 else 0)
        for page, flags in sorted(pages.items()):
            if map_allocations:
                self.map(page, 4096, flags)
            elif not any(region["address"] <= page and page + 4096 <= region["address"] + region["size"]
                         and (region["permissions"] & flags) == flags for region in self.regions if "permissions" in region):
                raise ValueError(f"ELF allocation at {page:#010x} lacks mapped RAM permissions")
        for address, _, content in sections:
            if content:
                self.write(address, content)
        self.artifacts.append({"name": path.name, "sha256": hashlib.sha256(data).hexdigest(), "entry": entry})
        return entry

    def close(self):
        if self.handle:
            self.lib.c6_destroy(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
