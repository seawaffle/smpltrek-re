#!/usr/bin/env python3
"""Build a product's state after boot initialisation in c6sim: what a function sees when the app is running.

Order, as in a SYS/BIOS boot: the copy table's initialised data, the module start-up functions (Hwi, cache,
heaps, ...), then every C++ static constructor in `.init_array`. The SYS/BIOS heap returns NULL in the
simulation, so Memory_alloc / Memory_free are replaced by a bump allocator in an unused address range (never
freed). Code that polls hardware has to be replaced by stubs; each product lists the ones met so far.

What this does not run: main, the SYS/BIOS scheduler and tasks. Use Boot.machine() to run further code (a
start-up method, a page handler) on top of the built state.

Usage as a module:
  boot = sim_boot.Boot("cydrums", "firmware/cydrums/CyDrums_v1.1.84.zip")
  m = boot.machine(regs={"a4": this})       # fresh Machine on a copy of the built memory
  m.run(function)
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import c6sim

HEAP_BASE = 0x34000000

PRODUCTS = {
    "cydrums": dict(
        b14=0xC26B0EC0,
        startup=(0xC269E610, 13),          # SYS/BIOS module start-up function table
        init_array=(0xC26B1580, 181),
        memory_alloc=0xC25EC900, memory_free=0xC2618100,
        stubs={
            0xC25E3A80: "PSC1 module enable (polls the PSC)",
            0xC24C5390: "settings_load (flash request through the flash task)",
            0xC24C54D8: "flash_headers_request (flash task)",
            0xC25B42A0: "task_sleep",
            0xC2566FA4: "codec I2C transfer busy flag (cleared by the I2C interrupt)",
            0xC25D442C: "I2C bus-busy status poll",
            0xC256CF28: "peripheral status poll",
            0xC2544FE0: "USB0 soft reset poll",
            0xC25F92E0: "USB PHY clock-good poll (SYSCFG CFGCHIP2)",
        }),
    # CyDrums 2.0.97 beta: the same roles as "cydrums", each address re-derived for the 2.0 image. "match" is
    # the 1.1.84 -> 2.0.97 function match of analysis/func_match.py (similarity 1.0 unless noted).
    "cydrums-2.0.97": dict(
        b14=0xC273B670,                    # entry 0xC267D960: mvk -18832 / mvkh 0xC2730000 into b14
        startup=(0xC2728430, 13),          # the 13 matched 1.1.84 entries, in the same order, followed by 0
        init_array=(0xC273BD78, 185),      # the .init_array section, 0x2E4 bytes
        # .init_array entry 34 (0xC268F860) constructs 8 objects of 876 bytes with 0xC26489E0, float maths
        # that takes 9.7 million cycles on its own (returns; no polling)
        max_cycles=20000000,
        memory_alloc=0xC26722A0,           # match (0.97); same body apart from the callee
        memory_free=0xC269DA20,            # match by neighbours (0.83); same body apart from the two constants
        stubs={
            0xC2666F20: "PSC1 module enable (polls the PSC)",
            0xC2553774: "settings_load (flash request through the flash task)",     # not matched; the
            0xC2553948: "flash_headers_request (flash task)",   # two calls after task_sleep in the start-up
            0xC2636060: "task_sleep",                           # routine 0xC253F320, same bodies as 1.1.84
            0xC25E4E84: "codec I2C transfer busy flag (cleared by the I2C interrupt)",
            0xC265730C: "I2C bus-busy status poll",
            0xC25EAE28: "peripheral status poll",
            0xC25BFD60: "USB0 soft reset poll",
            0xC267DFA0: "USB PHY clock-good poll (SYSCFG CFGCHIP2)",
        }),
    "smpltrek": dict(
        b14=0xC16F3320,
        startup=(0xC16C8560, 13),          # g_startup_fxns
        init_array=(0xC16F39AC, 147),
        memory_alloc=0xC168CC20, memory_free=0xC16AD1A0,
        stubs={}),
    "lofi12": dict(
        b14=0xC2DA6758,
        startup=(0xC2D96220, 13),
        init_array=(0xC2DA6DD4, 172),
        memory_alloc=0xC2CC8E60, memory_free=0xC2CEC740,
        stubs={
            0xC2CC2480: "PSC1 module enable (polls the PSC)",
        }),
}


class BumpHeap:
    """Stands in for xdc Memory_alloc(heap, size, align, eb) / Memory_free. Never frees."""

    def __init__(self, base=HEAP_BASE):
        self.next = base

    def alloc(self, m):
        size, align = m.R.get("b4", 0), max(8, m.R.get("a6", 0) or 8)
        self.next = (self.next + align - 1) & ~(align - 1)
        m.R["a4"] = self.next
        self.next += max(size, 1)
        return m.R["b3"]


class Boot:
    def __init__(self, product, image, extra_stubs=(), max_cycles=None):
        self.cfg = PRODUCTS[product]
        max_cycles = max_cycles or self.cfg.get("max_cycles", 5000000)
        self.image = image
        self.program = c6sim.Program(image)
        self.heap = BumpHeap()
        self.stubs = dict(self.cfg["stubs"])
        for address in extra_stubs:
            self.stubs[address] = "caller-supplied stub"
        self.errors = []
        self.overlay = self._build(max_cycles)

    def hooks(self):
        hooks = {a: c6sim.returns(0) for a in self.stubs}
        hooks[self.cfg["memory_alloc"]] = self.heap.alloc
        hooks[self.cfg["memory_free"]] = c6sim.returns(0)
        return hooks

    def _entries(self):
        word = self.program.image.word
        (s, ns), (i, ni) = self.cfg["startup"], self.cfg["init_array"]
        return [word(s + 4 * k) for k in range(ns)] + [word(i + 4 * k) for k in range(ni)]

    def _build(self, max_cycles):
        overlay = None
        for entry in self._entries():
            m = c6sim.Machine(self.program, {"b14": self.cfg["b14"]}, hooks=self.hooks())
            if overlay is None:
                m.apply_init_data(self.image)
            else:
                m.mem.overlay = overlay
            try:
                m.run(entry, max_cycles=max_cycles)
            except c6sim.SimError as e:
                self.errors.append((entry, str(e)))
            overlay = m.mem.overlay
        return overlay

    def machine(self, regs=None, hooks=None, trace=False):
        """A Machine on a copy of the built memory, with the product's stubs, the heap and extra hooks."""
        all_hooks = self.hooks()
        all_hooks.update(hooks or {})
        m = c6sim.Machine(self.program, dict({"b14": self.cfg["b14"]}, **(regs or {})), hooks=all_hooks, trace=trace)
        m.mem.overlay = dict(self.overlay)
        return m
