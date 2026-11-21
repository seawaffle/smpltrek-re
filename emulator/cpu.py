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


class CoreFault(RuntimeError):
    pass


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
            cycle, row = C.c_uint64(), (C.c_uint32 * 3)()
            self.checked(self.lib.c6_codec_write(self.handle, index, C.byref(cycle), row))
            result["trace"].append(dict(cycles=cycle.value, page=row[0], register=row[1], value=row[2]))
        return result

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
        self.ensure_open()
        fields = (C.c_uint64 * 6)()
        self.checked(self.lib.c6_usb_stats(self.handle, fields))
        return dict(profile="disconnected USB0 peripheral", cable_connected=False,
                    reserved_status=self.usb_reserved_status_state(),
                    **dict(zip(("soft_resets", "phy_ready", "soft_connect", "interrupt_mask", "interrupt_source", "interrupts"), fields)))

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
        end = self.cycles() + cycles
        while True:
            remaining = end - self.cycles()
            status = self.lib.c6_run(self.handle, remaining)
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
