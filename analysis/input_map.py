#!/usr/bin/env python3
"""The panel's key matrix and encoders as SmplTrek 3.2.174 reads them, run in c6sim with modelled GPIO inputs.
Read-only and simulated.

Both were first read by hand (docs/04-hardware-access.md, "Key matrix" and "Encoders"); this tool runs the stock
code instead, so the bit numbering and the decoding are what the app computes, not a reading of it.

Key matrix: `control_switch_poll` (0xC16534C0) on `g_control_switch_scanner` (0xC1501DB0), which drives
`ControlScan` (`g_control_scan` 0xC1503ED8): one row per poll, GP2[row] high through SET_DATA23 / CLR_DATA23, the
columns read from IN_DATA23 (SPRUH79C Table 19-2: bank pair 2/3 at 0x01E26038.., GP3[n] = bit 16 + n). The model:
a pressed key (row, GP3 pin) reads high while its row is driven high; GP5[10] (IN_DATA45 bit 26) is the extra
key, pressed when low. The held word is scanner+64. `key_timing` measures, per key, how many scans of its row a press or release takes and
whether a one-scan bounce gets through (04-hardware-access.md "Key timing and debounce").

Encoders: `encoder_poll_all` (0xC166DA48) on `g_encoders` (0xC10E1288, 5 x 24 bytes) reads IN_DATA23 and
IN_DATA45; each encoder's two pins are modelled as levels (rest = both high, phase 3). A stand-in delegate
records what slot 0 (`post_encoder_event` in the app) would receive: the encoder object and the step count.

Power key: `power_on_check` (0xC1646FCC) on `g_power_manager` with GP3[0] (IN_DATA23 bit 16) modelled per read and
`task_sleep` recorded. SD card detect: `sd_card_detect_raw` (0xC16724EC) with GP4[0] (IN_DATA45 bit 0).

Usage (from the repository root; needs firmware/ and the work listing, as hw_compare.py):
  python3 -B analysis/input_map.py
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

GPIO = 0x01E26000
SET23, CLR23, IN23, IN45 = GPIO + 0x40, GPIO + 0x44, GPIO + 0x48, GPIO + 0x70
POLL_KEYS, SCANNER = 0xC16534C0, 0xC1501DB0
POLL_ENCODERS, ENCODERS = 0xC166DA48, 0xC10E1288
COLUMNS = [1, 2, 3, 4, 5, 6, 9, 11]                       # GP3 pins of columns 0-7
ENCODER_PINS = [((3, 14), (3, 15)), ((3, 12), (3, 10)), ((5, 2), (5, 0)), ((5, 5), (5, 4)), ((5, 7), (5, 8))]
FAKE_DELEGATE, FAKE_VTABLE, DELEGATE_SLOT0 = 0xC0000100, 0xC0000140, 0xC0000180   # unused DDR (zero-filled)
POWER_ON_CHECK, POWER_MANAGER, TASK_SLEEP, TICK_COUNT = 0xC1646FCC, 0xC15036E8, 0xC1667D20, 0xC16ACDA0
SD_DETECT_RAW = 0xC16724EC
SET45 = GPIO + 0x68


class Session:
    def __init__(self):
        import c6sim
        import hw_compare
        import mmio_trace
        self.c6sim, self.hw_compare = c6sim, hw_compare
        t = self.t = mmio_trace.Trace(str(hw_compare.ROOT / hw_compare.PRODUCTS["smpltrek"]["image"]), "smpltrek")
        t.boot()
        t.state, t.regs = dict(t.boot_state.overlay), {}
        self.rows, self.pressed, self.gp5_10_low, self.level, self.power_key = 0, set(), False, {}, []
        base = t.memory_class
        session = self

        def memory_class():
            class InputMemory(base()):
                def write(self, address, data):
                    v = int.from_bytes(bytes(data), "little")
                    if address == SET23:
                        session.rows |= v & 0xFFFF
                    elif address == CLR23:
                        session.rows &= ~v & 0xFFFF
                    super().write(address, data)

                def read(self, address, size):
                    if address == IN23:
                        t.regs[IN23] = session.bank_word(3) | session.rows
                    elif address == IN45:
                        t.regs[IN45] = session.bank_word(5) | session.bank_word(4) >> 16
                    return super().read(address, size)
            return InputMemory
        t.memory_class = memory_class
        self.events = []

        def delegate(m):
            self.events.append(((m.R.get("b4", 0) - ENCODERS) // 24, c6sim.s32(m.R.get("b6", 0))))
            return m.R["b3"]
        self.hooks = {a: c6sim.returns(0) for a in hw_compare.HOOKS}
        self.hooks[DELEGATE_SLOT0] = delegate
        self.poke(FAKE_DELEGATE, FAKE_VTABLE)
        self.poke(FAKE_VTABLE, DELEGATE_SLOT0)
        for i in range(5):
            self.poke(ENCODERS + 24 * i + 4, FAKE_DELEGATE)

    def poke(self, address, value):
        for i in range(4):
            self.t.state[address + i] = (value >> (8 * i)) & 0xFF

    def word(self, address, size=4):
        return sum(self.t.state.get(address + i, 0) << (8 * i) for i in range(size))

    def bank_word(self, bank):
        """IN_DATA bits 16-31 for GP3 or GP5 (the odd bank of its pair) from the modelled inputs."""
        v = 0
        for pin in range(16):
            if bank == 3 and pin == 0 and self.power_key:
                high = self.power_key.pop(0) if len(self.power_key) > 1 else self.power_key[0]
            elif bank == 4:
                high = self.level.get((4, pin), 1)
            elif bank == 3:
                high = any(self.rows >> r & 1 and p == pin for r, p in self.pressed) or \
                    self.level.get((3, pin), 0 if pin in COLUMNS else 1)
            else:
                high = not self.gp5_10_low if pin == 10 else self.level.get((5, pin), 1)
            v |= int(bool(high)) << (16 + pin)
        return v

    # --- keys ---------------------------------------------------------------------------------------
    def keys(self, pressed=(), gp5_10_low=False, polls=14):
        """The 64-bit held-switch word after `polls` scans with these keys ((row, GP3 pin)) held."""
        self.pressed, self.gp5_10_low = set(pressed), gp5_10_low
        for _ in range(polls):
            self.t.run(POLL_KEYS, {"a4": SCANNER}, hooks=self.hooks, max_cycles=200000)
        return self.word(SCANNER + 64, 8)

    def key_bits(self):
        """{(row, GP3 pin): [bits set]} for every single key, plus ('GP5', 10) for the extra one."""
        out = {}
        for r in range(6):
            for pin in COLUMNS:
                h = self.keys([(r, pin)])
                self.keys([])
                out[(r, pin)] = [b for b in range(64) if h >> b & 1]
        h = self.keys([], gp5_10_low=True)
        self.keys([])
        out[("GP5", 10)] = [b for b in range(64) if h >> b & 1]
        return out

    # --- key timing (debounce) ---------------------------------------------------------------------
    def install_switch_delegate(self):
        """Give the scanner a delegate at +24, as MainDelegate's set-up does at run time; its slots return at once.
        (The boot state leaves +24 null; the poll then takes the same decisions, but this matches the app.)"""
        delegate, vtable, hook = 0xC0000200, 0xC0000240, 0xC0000280
        self.poke(SCANNER + 24, delegate)
        self.poke(delegate, vtable)
        for k in range(4):
            self.poke(vtable + 4 * k, hook + 4 * k)
            self.hooks[hook + 4 * k] = self.c6sim.returns(0)

    def poll_once(self, closed, key):
        """One control_switch_poll with `key` ((row, GP3 pin)) closed or open. Returns (the matrix row this poll
        read, whether the key's bit is set in the held word afterwards)."""
        row, pin = key
        read = (self.rows & 0x3F).bit_length() - 1        # the row driven while this poll reads the columns
        self.pressed = {key} if closed else set()
        self.t.run(POLL_KEYS, {"a4": SCANNER}, hooks=self.hooks, max_cycles=200000)
        bit = 8 * row + COLUMNS.index(pin)
        return read, bool(self.word(SCANNER + 64, 8) >> bit & 1)

    def key_timing(self, key, settle=14, limit=30):
        """How the stock scan filters one key, counted in scans of the key's own row (one row per poll, one poll
        per 1 ms tick, so a row is read every 6 polls), over all six starting phases. Returns
        {"press": sorted set of row scans from closing to the held bit, "release": the same from opening to the
        bit clearing, "press_glitch": whether a close lasting one row scan sets the bit,
        "release_glitch": whether an opening lasting one row scan clears it}. Loops are bounded by `limit`."""
        row = key[0]
        out = {"press": set(), "release": set(), "press_glitch": set(), "release_glitch": set()}

        def run(closed, polls):
            return [self.poll_once(closed, key) for _ in range(polls)]

        def until(closed, want):
            scans = 0
            for _ in range(limit):
                read, held = self.poll_once(closed, key)
                scans += read == row
                if held == want:
                    return scans
            raise RuntimeError(f"key {key}: held bit never became {want} within {limit} polls")

        def one_scan(closed):
            """Hold the opposite state until just before the row's scan, flip for exactly that one poll."""
            for _ in range(7):
                if (self.rows & 0x3F).bit_length() - 1 == row:
                    break
                self.poll_once(not closed, key)
            return [self.poll_once(closed, key)]

        for phase in range(6):
            run(False, settle + phase)
            out["press"].add(until(True, True))
            run(True, settle)
            out["release"].add(until(False, False))
            run(False, settle + phase)
            one_scan(True)
            out["press_glitch"].add(any(held for _, held in run(False, 12)))
            run(True, settle + phase)
            one_scan(False)
            out["release_glitch"].add(not all(held for _, held in run(True, 12)))
            run(False, settle)
        return {k: sorted(v) for k, v in out.items()}

    # --- power key and SD card detect --------------------------------------------------------------
    def power_on_check(self, key_levels, started=False, max_cycles=400000):
        """(return value or None if it does not return, [task_sleep ms], GPIO writes) with GP3[0] reading
        key_levels in turn (the last one repeats); started = byte +28 already set."""
        s = self.t
        state = dict(s.state)
        self.power_key = list(key_levels)
        if started:
            s.state[POWER_MANAGER + 28] = 1
        sleeps = []

        def sleep(m):
            sleeps.append(m.R.get("a4", 0))
            m.R["a4"] = 0
            return m.R["b3"]
        hooks = {**self.hooks, TASK_SLEEP: sleep, TICK_COUNT: self.c6sim.returns(1234)}
        try:
            r, log = s.run(POWER_ON_CHECK, {"a4": POWER_MANAGER}, hooks=hooks, max_cycles=max_cycles)
        except self.c6sim.SimError:
            r, log = None, []
        writes = [(a.address, a.value) for a in log if a.kind == "W" and GPIO <= a.address < GPIO + 0x1000]
        s.state, self.power_key = state, []
        return r, sleeps, writes

    def sd_card_present(self, gp4_0):
        self.level[(4, 0)] = gp4_0
        return self.t.run(SD_DETECT_RAW, {}, hooks=self.hooks, max_cycles=100000)[0]

    # --- encoders -----------------------------------------------------------------------------------
    def poll_encoders(self, n=1):
        for _ in range(n):
            self.t.run(POLL_ENCODERS, {"a4": ENCODERS}, hooks=self.hooks, max_cycles=200000)

    def turn(self, i, phases, polls_per_phase=2, settle=32):
        """[(encoder object, steps)] reported for encoder i driven through `phases` (bit 0 = first pin,
        bit 1 = second pin of ENCODER_PINS[i]), then `settle` idle polls."""
        self.poll_encoders(settle)
        self.events.clear()
        a, b = ENCODER_PINS[i]
        for ph in phases:
            self.level[a], self.level[b] = ph & 1, ph >> 1 & 1
            self.poll_encoders(polls_per_phase)
        self.poll_encoders(settle)
        return list(self.events)


def main():
    s = Session()
    for name, levels, started in (("GP3[0] high", [1], False), ("GP3[0] low", [0], False),
                                  ("low, released after 3 reads", [0, 0, 0, 1], False), ("+28 set", [0], True)):
        r, sleeps, writes = s.power_on_check(levels, started)
        print(f"power_on_check, {name}: returns {r}, task_sleep {sleeps[:10]}{'...' if len(sleeps) > 10 else ''}, "
              f"GPIO writes {[(hex(a), hex(v)) for a, v in writes]}")
    print(f"sd_card_detect_raw: GP4[0] low -> {s.sd_card_present(0)}, high -> {s.sd_card_present(1)}")
    bits = s.key_bits()
    for k, v in bits.items():
        print(f"key {k}: bits {v}")
    for i in range(5):
        print(f"encoder {i} {ENCODER_PINS[i]}: 3-1-0-2-3 -> {s.turn(i, [1, 0, 2, 3])}, "
              f"3-2-0-1-3 -> {s.turn(i, [2, 0, 1, 3])}")
    for seq in ([3, 1, 3], [1, 0, 1, 3], [1, 0, 1, 0, 2, 3], [2, 0, 2, 0, 1, 3], [0, 3]):
        print(f"encoder 2 {seq}: reported {s.turn(2, seq)}")


if __name__ == "__main__":
    main()
