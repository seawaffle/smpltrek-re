"""c6sim checks. Run: python3 -B -m unittest discover -s analysis -p "test_c6sim.py" -v

The oracle for Lofi-12 XT is the hand-read clamp sequence of its settings_validate (0xC2BD31AC; claim
XF-13, device-checked in C3). The CyDrums values pin claim XF-17. Every test needs the official updates in
firmware/ (not tracked) and skips without them; the SmplTrek self-check also needs the A4 dump in work.
"""
from pathlib import Path
import re
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import c6sim

LOFI = ROOT / "firmware/lofi12/Lofi-12XT_v1.5.205.zip"
CYDRUMS = ROOT / "firmware/cydrums/CyDrums_v1.1.84.zip"
SMPLTREK = ROOT / "firmware/smpltrek/SmplTrek v3.2.174.zip"
A4 = ROOT / "work/a4/A4DUMP.BIN"

# Lofi-12 XT settings_validate, read by hand (docs/01-platform-map.md, "Lofi-12 XT reading SmplTrek's
# settings"): (offset, lo, hi, fallback) in call order; +0x60 forced to 0 after the 19th clamp, +0x108 to 4
# after the +0x104 clamp, and +0x15C cleared unless +0x10 < 0 and +0x15C >= 0.
LOFI_CLAMPS = (
    [(0x04, 0, 2, 0), (0x08, 0, 1, 0), (0x0C, 0, 1, 0), (0x14, 0, 16, 6), (0x18, 0, 13, 3), (0x1C, 0, 2, 1),
     (0x20, 0, 2, 2), (0x24, 0, 1, 0), (0x28, 0, 1, 1), (0x30, 0, 4, 0), (0x44, 0, 127, 100), (0x48, 0, 1, 0),
     (0x4C, 0, 16, 3), (0x50, 1, 16, 4), (0x54, 1, 130, 129), (0x58, 1, 130, 129), (0x58, 0, 1, 0),
     (0x5C, 0, 1, 0), (0x188, 0, 1, 1), (0x164, -1, 15, -1)]
    + [(0x168 + 4 * i, 0, 127, d) for i, d in enumerate([36, 38, 47, 39, 58, 42, 46, 49])]
    + [(0x90 + 4 * i, 0, 15, i) for i in range(8)]
    + [(0xCC, -1, 15, 13), (0xD0, -1, 15, 15), (0xD8, -1, 15, 14), (0xD4, 0, 1, 0), (0x64, 0, 5, 5),
       (0x68, 0, 1, 0), (0x6C, 0, 1, 0), (0x70, 0, 1, 0), (0x7C, 0, 1, 1), (0x88, 0, 1, 0), (0xDC, 0, 3, 3),
       (0xE0, 0, 3, 3), (0xE8, 0, 1, 0), (0xEC, 0, 1, 0), (0xF0, 0, 1, 0), (0xF4, 0, 1, 0), (0xF8, 0, 3, 0),
       (0xFC, 0, 3, 0), (0x18C, 0, 3, 0), (0x100, 0, 2, 0), (0x104, 0, 4, 0), (0x10C, 0, 1, 1),
       (0x110, 0, 127, 100), (0x118, 0, 3, 0), (0x11C, 0, 127, 0), (0x120, 0, 1, 0), (0x124, 0, 1, 0),
       (0x128, 0, 1, 0), (0x12C, 0, 1, 1), (0x130, 0, 1, 1), (0x134, 0, 1, 0), (0x138, 0, 127, 100),
       (0x13C, 0, 127, 0), (0x140, 0, 127, 0), (0x144, 0, 1, 0), (0x148, 0, 127, 100), (0x14C, 0, 127, 0),
       (0x150, 0, 127, 0), (0x154, 0, 1, 1), (0x158, 0, 6, 3), (0x160, 0, 1, 0), (0x190, 0, 1, 1)])


def lofi_oracle(words):
    w = list(words)
    for n, (off, lo, hi, dv) in enumerate(LOFI_CLAMPS):
        if n == 19:
            w[0x60 // 4] = 0
        if not lo <= w[off // 4] <= hi:
            w[off // 4] = dv
        if off == 0x104:
            w[0x108 // 4] = 4
    if w[0x10 // 4] >= 0 or w[0x15C // 4] < 0:
        w[0x15C // 4] = 0
    return w


def block(fill):
    return b"PREF" + struct.pack("<1023i", *([fill] * 1023))


def words(data):
    return list(struct.unpack(f"<{len(data) // 4}i", data))


# The corpus tests decode code with tools/tic6x objdump (tools/toolchain/build_tic6x_binutils.sh).
OBJDUMP_OK = (Path(__file__).resolve().parents[1] / "tools/tic6x/bin/tic6x-elf-objdump").exists()


@unittest.skipUnless(LOFI.exists() and OBJDUMP_OK, "official Lofi-12 XT 1.5.205 update not present (or tools/tic6x objdump missing)")
class LofiSettings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.program = c6sim.Program(LOFI)

    def check(self, fill):
        result, data = c6sim.run_settings(self.program, "lofi12", block(fill))
        self.assertEqual(result, 0)
        expected = lofi_oracle([0x50524546 if i == 0 else fill for i in range(101)])
        got = words(data)
        diffs = [(4 * i, got[i], expected[i]) for i in range(1, 101) if got[i] != expected[i]]
        self.assertEqual(diffs, [])

    def test_high_values_take_every_fallback(self):
        self.check(0x7FFFFFF0)

    def test_low_values_take_every_fallback(self):
        self.check(-0x7FFFFFF0)

    def test_in_range_values_are_kept(self):
        self.check(1)

    def test_tag_mismatch_returns_minus_one_and_clamps_ram(self):
        result, data = c6sim.run_settings(self.program, "lofi12", b"\xff" * 4096)
        self.assertEqual(result, -1)
        self.assertEqual(words(data)[1:], lofi_oracle([0] * 101)[1:])

    def test_factory_defaults(self):
        _, data = c6sim.run_settings(self.program, "lofi12")
        w = {4 * i: v for i, v in enumerate(words(data))}
        self.assertEqual([w[o] for o in (0x50, 0x54, 0xDC, 0xE0, 0xCC, 0xD0, 0xD8, 0x10C, 0x110, 0x10)],
                         [4, 129, 3, 3, 13, 15, 14, 1, 100, 7])
        self.assertEqual([w[0x168 + 4 * i] for i in range(8)], [36, 38, 47, 39, 58, 42, 46, 49])


@unittest.skipUnless(LOFI.exists() and OBJDUMP_OK, "official Lofi-12 XT 1.5.205 update not present (or tools/tic6x objdump missing)")
class LofiLoops(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.program = c6sim.Program(LOFI)

    def test_spkernel_delay_matches_objdump_for_32_bit_forms(self):
        """objdump decodes the 32-bit field correctly; the decoder must agree on every one in the image."""
        m = c6sim.Machine(self.program)
        text = self.program.text
        addresses = sorted(text)
        checked = 0
        for n, a in enumerate(addresses):
            mm = re.match(r"spkernel (\d+),(\d+)$", text[a])
            if not mm or self.program.raw(a)[1] != 4:
                continue
            ii = next(int(re.search(r"sploop\w*\s+(\d+)", text[b]).group(1))
                      for b in reversed(addresses[max(0, n - 400):n]) if re.search(r"\bsploop\w*\s+\d+", text[b]))
            self.assertEqual(m.spkernel_delay(a, ii), int(mm.group(1)) * ii + int(mm.group(2)), hex(a))
            checked += 1
        self.assertGreater(checked, 100)

    def test_compact_spkernel_uses_figure_h7_bit_order(self):
        """0xC2BF71B2 is 0x1C67 after 'sploop 1': fstg 1, although objdump prints 'spkernel 32,0'."""
        self.assertEqual(self.program.raw(0xC2BF71B2), (0x1C67, 2))
        self.assertEqual(self.program.text[0xC2BF71B2], "spkernel 32,0")
        self.assertEqual(c6sim.Machine(self.program).spkernel_delay(0xC2BF71B2, 1), 1)

    def test_sploopd_word_copy_fills_the_shadow(self):
        """settings_validate ends by copying 404 bytes to the shadow with an SPLOOPD word copy."""
        m = c6sim.Machine(self.program, {"b14": c6sim.PRODUCTS["lofi12"]["b14"]})
        m.mem.write(c6sim.BLOCK, block(1))
        m.R.update({"a4": c6sim.BLOCK, "b4": 4096})
        m.run(c6sim.PRODUCTS["lofi12"]["validate"])
        settings = m.mem.read(0xC2B74984, 404)
        self.assertEqual(m.mem.read(0xC2B74B18, 404), settings)
        self.assertEqual(m.mem.read(0xC2B74B18 + 404, 4), bytes(4))


@unittest.skipUnless(LOFI.exists() and OBJDUMP_OK, "official Lofi-12 XT 1.5.205 update not present (or tools/tic6x objdump missing)")
class LofiConstructors(unittest.TestCase):
    def test_page_constructors_store_their_vtables(self):
        """The .init_array entry 0xC2CB7060 builds the static pages (about 55,000 cycles of mixed code)."""
        program = c6sim.Program(LOFI)
        stub = 0xDEAD1000
        m = c6sim.Machine(program, {"b14": c6sim.PRODUCTS["lofi12"]["b14"]}, hooks={stub: c6sim.returns(0)})
        m.apply_init_data(LOFI)
        for lock in (0xC2D2F73C, 0xC2D3139C):     # run-time-support lock hooks, set later by SYS/BIOS
            m.mem.write(lock, struct.pack("<I", stub))
        m.run(0xC2CB7060, max_cycles=1000000)
        # primary vtable address points from the RTTI (analysis/rtti_recover.py output)
        expected = {0xC2B7F088: 0xC2D93480,    # AppSystemMenu
                    0xC2B7EFFC: 0xC2D935E0,    # AppProjectMenu
                    0xC2B7F04C: 0xC2D93798,    # AppSampleRecording
                    0xC2B7E440: 0xC2D93D70,    # AppMixer
                    0xC2B7E414: 0xC2D8E740,    # AppAudioFileSelect
                    0xC2B7F198: 0xC2D933D0}    # AppFileRename
        self.assertEqual({a: m.mem.word(a) for a in expected}, expected)


@unittest.skipUnless(CYDRUMS.exists() and OBJDUMP_OK, "official CyDrums 1.1.84 update not present (or tools/tic6x objdump missing)")
class CyDrumsSettings(unittest.TestCase):
    """Pins claim XF-17."""

    @classmethod
    def setUpClass(cls):
        cls.program = c6sim.Program(CYDRUMS)

    def test_unclamped_words(self):
        hi = words(c6sim.run_settings(self.program, "cydrums", block(0x7FFFFFF0))[1])
        lo = words(c6sim.run_settings(self.program, "cydrums", block(-0x7FFFFFF0))[1])
        kept = [4 * i for i in range(1, 94) if hi[i] == 0x7FFFFFF0 and lo[i] == -0x7FFFFFF0]
        self.assertEqual(kept, [0x10, 0x2C, 0x34, 0x38, 0x3C, 0x40, 0x64, 0x68, 0xB0, 0xB4, 0xB8, 0xBC, 0xC0,
                                0xC4, 0xC8, 0xE4, 0x114])
        self.assertEqual([hi[o // 4] for o in (0x4C, 0x108, 0x6C, 0x70, 0x74)], [3, 4, 9, 36, 37])

    def test_erased_flash(self):
        result, data = c6sim.run_settings(self.program, "cydrums", b"\xff" * 4096)
        self.assertEqual(result, -1)
        w = words(data)
        self.assertEqual({4 * i: v for i, v in enumerate(w) if i and v}, {0x50: 4, 0x54: 128, 0x108: 4})

    def test_factory_defaults(self):
        w = words(c6sim.run_settings(self.program, "cydrums")[1])
        self.assertEqual([w[o // 4] for o in (0x4C, 0x6C, 0x104, 0x10C, 0x110)], [10, 9, 0, 1, 100])
        self.assertEqual([w[(0x70 + 4 * i) // 4] for i in range(8)], [36, 38, 47, 39, 58, 42, 46, 49])


@unittest.skipUnless(CYDRUMS.exists() and OBJDUMP_OK, "official CyDrums 1.1.84 update not present (or tools/tic6x objdump missing)")
class CyDrumsNestedReload(unittest.TestCase):
    """0xC253FA24: [b2] SPLOOPD 7 with SPMASKR in the post-loop code, RILC 22, outer count 2 (SPRUFE8B 7.9.6).

    Oracle, read by hand from the loop body's iteration-relative timing: record i at p = 0xC26851D8 + 200 i
    with count n = word(p) fills the four halfwords at 0xC2427108 + 8 i with h(p+12) if n > 0, h(p+60) if
    n >= 2, h(p+108) if n > 2 and h(p+156) if n >= 4, else 0. The outer code resets every source pointer
    and moves the destination by 176, so the reloaded invocation writes the same values to the second row.
    """
    FUNC, SRC, DST = 0xC253FA24, 0xC26851D8, 0xC2427108

    @classmethod
    def setUpClass(cls):
        cls.program = c6sim.Program(CYDRUMS)

    def run_table(self, machine_class=c6sim.Machine):
        m = machine_class(self.program, {"b14": c6sim.PRODUCTS["cydrums"]["b14"]})
        for i in range(22):                         # counts 0..5 and a distinct value in every field
            p = self.SRC + 200 * i
            m.mem.write(p, struct.pack("<i", i % 6))
            for k, off in enumerate((12, 60, 108, 156)):
                m.mem.write(p + off, struct.pack("<H", 0x100 * (i + 1) + k + 1))
        stores = []
        write = m.mem.write
        m.mem.write = lambda a, d: (stores.append(a), write(a, d))
        m.run(self.FUNC, max_cycles=5000)
        return m, stores

    def expected(self):
        out = []
        for i in range(22):
            n = i % 6
            v = [0x100 * (i + 1) + k + 1 for k in range(4)]
            out += [v[0] if n > 0 else 0, v[1] if n >= 2 else 0, v[2] if n > 2 else 0, v[3] if n >= 4 else 0]
        return out

    def table(self, m, row):
        return list(struct.unpack("<88H", m.mem.read(self.DST + 176 * row, 176)))

    def test_two_invocations_fill_both_rows(self):
        m, stores = self.run_table()
        self.assertEqual(self.table(m, 0), self.expected())
        self.assertEqual(self.table(m, 1), self.expected())
        self.assertEqual(sorted(stores), list(range(self.DST, self.DST + 352, 2)))
        self.assertEqual(m.g("ilc"), 0)

    def test_negative_controls(self):
        class NoReload(c6sim.Machine):
            def reload(self, address):
                self.loopbuf["reload"] = False
                super().reload(address)

        class OffByOne(c6sim.Machine):
            def g(self, r):
                return super().g(r) + 1 if r == "rilc" else super().g(r)
        m, stores = self.run_table(NoReload)
        self.assertEqual(len(stores), 88)           # one invocation only
        self.assertNotEqual(self.table(m, 1), self.expected())
        m, stores = self.run_table(OffByOne)
        self.assertNotEqual(sorted(stores), list(range(self.DST, self.DST + 352, 2)))


@unittest.skipUnless(SMPLTREK.exists() and A4.exists() and OBJDUMP_OK, "SmplTrek 3.2.174 update or A4 dump not present (or tools/tic6x objdump missing)")
class SmplTrekSelfCheck(unittest.TestCase):
    def test_own_block_is_unchanged(self):
        """SmplTrek wrote this block itself, so its validator must keep every word."""
        program = c6sim.Program(SMPLTREK)
        blk = A4.read_bytes()[0x1FFF000:0x1FFF000 + 4096]
        result, data = c6sim.run_settings(program, "smpltrek", blk)
        self.assertEqual(result, 0)
        self.assertEqual(data, blk[:len(data)])


@unittest.skipUnless(SMPLTREK.exists() and OBJDUMP_OK, "SmplTrek 3.2.174 update not present (or tools/tic6x objdump missing)")
class SmplTrekProtPerFetchPacket(unittest.TestCase):
    """PROT applies to the loads of its own fetch packet (SPRUFE8B 3.10.2.2, Table 3-14). The SPI pin-control
    store 0xC167140C has an execute packet (ldw at 0xC1671414 || bnop at 0xC1671420) that crosses from a fetch
    packet without PROT into one with it; its SPIPC0 store sits in the bnop's last delay slot (claim HW-32)."""
    def test_spipc0_store_in_last_delay_slot(self):
        import mmio_trace
        t = mmio_trace.Trace(str(SMPLTREK), "smpltrek")
        t.boot()
        self.assertFalse(t.boot_state.program.packet(0xC1671414)[2])
        t.state = dict(t.boot_state.overlay)
        t.regs = {}
        word = 0xC0000100
        for i, b in enumerate((0x01, 0x0E, 0, 0)):
            t.state[word + i] = b
        _, log = t.run(0xC167140C, {"a4": 0x01F0E000, "b4": 0, "a6": 0, "b6": word}, hooks={}, max_cycles=10000)
        self.assertEqual([(a.kind, a.address, a.value) for a in log], [("W", 0x01F0E014, 0x0E01)])


if __name__ == "__main__":
    unittest.main()
